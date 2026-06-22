"""即時價格估值引擎 (Real-Time Price Valuation Engine)。

依稀有度分層採用不同估值策略，並引入流動性折價：
- 高階 (SAR/UR/SR)：7 日成交量加權移動平均 (VWMA)，抵禦操盤與閃崩。
- 中階 (AR/RR)：目前在售掛單中位數。
- 散卡 (U/C)：固定流動性底價，除非被標記為 meta 卡。

價格優先讀 Redis 快取（每日批次寫入），miss 才回 price_history 聚合，
並把結果回填快取（TTL 24h）。
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.scan import MarketValue

# 稀有度 → 估值策略分層
HIGH_TIER = {"SAR", "UR", "SR"}
MID_TIER = {"AR", "RR"}
BULK_TIER = {"U", "C"}

# 散卡底價（NT$），meta 卡會在 DB 端用旗標覆寫。
BULK_FLOOR = Decimal("10.00")
BULK_META_FLOOR = Decimal("30.00")

PRICE_CACHE_TTL = 60 * 60 * 24  # 24 小時


def _cache_key(card_id: str) -> str:
    return f"price:{card_id}"


async def _load_from_cache(
    redis: aioredis.Redis, card_id: str
) -> Optional[MarketValue]:
    cached = await redis.get(_cache_key(card_id))
    if not cached:
        return None
    try:
        data = json.loads(cached)
        return MarketValue(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        # 快取格式毀損就當作 miss，後面會重算並覆寫。
        return None


async def _store_cache(
    redis: aioredis.Redis, card_id: str, value: MarketValue
) -> None:
    await redis.set(
        _cache_key(card_id),
        value.model_dump_json(),
        ex=PRICE_CACHE_TTL,
    )


async def _compute_high_tier(
    session: AsyncSession, card_id: str
) -> tuple[Decimal, dict]:
    """7 日成交量加權移動平均 (VWMA = Σ(price*volume) / Σ(volume))。"""
    sql = text(
        """
        SELECT
            COALESCE(SUM(price * volume), 0) AS pv,
            COALESCE(SUM(volume), 0)         AS vol,
            MAX(price)                       AS hi,
            MIN(price)                       AS lo
        FROM price_history
        WHERE card_id = :cid
          AND recorded_date >= CURRENT_DATE - INTERVAL '7 days'
        """
    )
    r = (await session.execute(sql, {"cid": card_id})).mappings().first()
    vol = int(r["vol"]) if r and r["vol"] else 0
    if vol > 0:
        vwma = (Decimal(r["pv"]) / Decimal(vol)).quantize(Decimal("0.01"))
    else:
        # 7 日內零成交：退回最後一筆已知價，避免回傳 0。
        vwma = await _last_known_price(session, card_id)
    meta = {"avg_7d": vwma, "hi": r["hi"] if r else None,
            "lo": r["lo"] if r else None}
    return vwma, meta


async def _compute_mid_tier(
    session: AsyncSession, card_id: str
) -> tuple[Decimal, dict]:
    """目前在售掛單中位數（以最近 1 日的 listing 為準）。"""
    sql = text(
        """
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY price) AS med,
               MAX(price) AS hi, MIN(price) AS lo
        FROM price_history
        WHERE card_id = :cid
          AND recorded_date >= CURRENT_DATE - INTERVAL '1 day'
        """
    )
    r = (await session.execute(sql, {"cid": card_id})).mappings().first()
    med = r["med"] if r and r["med"] is not None else await _last_known_price(
        session, card_id
    )
    med = Decimal(med).quantize(Decimal("0.01"))
    return med, {"avg_7d": None, "hi": r["hi"] if r else None,
                 "lo": r["lo"] if r else None}


async def _last_known_price(session: AsyncSession, card_id: str) -> Decimal:
    """最後防線：取 cards.current_price，再不行回 0。"""
    r = (
        await session.execute(
            text("SELECT current_price FROM cards WHERE card_id = :cid"),
            {"cid": card_id},
        )
    ).first()
    if r and r[0] is not None:
        return Decimal(r[0]).quantize(Decimal("0.01"))
    return Decimal("0.00")


async def value_card(
    session: AsyncSession,
    redis: aioredis.Redis,
    card_id: str,
    rarity: str,
    liquidity_score: float,
    is_meta: bool = False,
    use_cache: bool = True,
) -> MarketValue:
    """估值主入口：依稀有度分流 → 流動性折價 → 回填快取。"""
    if use_cache:
        cached = await _load_from_cache(redis, card_id)
        if cached is not None:
            return cached

    rarity = rarity.upper()
    extra: dict = {"avg_7d": None, "hi": None, "lo": None}

    if rarity in HIGH_TIER:
        base, extra = await _compute_high_tier(session, card_id)
        strategy = "high_tier_vwma_7d"
    elif rarity in MID_TIER:
        base, extra = await _compute_mid_tier(session, card_id)
        strategy = "mid_tier_listing_median"
    elif rarity in BULK_TIER:  # 散卡 C/U：有在地實價就用實價，否則退回固定底價
        last = await _last_known_price(session, card_id)
        if last > 0:
            base, strategy = last, "bulk_local_price"
        else:
            base = BULK_META_FLOOR if is_meta else BULK_FLOOR
            strategy = "bulk_flat_floor"
    else:
        # 其他/特殊高稀有度（MUR/MA/SSR/HR/BWR/ACE… 或未知）→ 直接採用在地實價，
        # 不可落到散卡底價而低估特卡。
        base = await _last_known_price(session, card_id)
        if base <= 0:
            base = BULK_META_FLOOR if is_meta else BULK_FLOOR
        strategy = "local_market_price"

    # 流動性折價：只對「會進神秘包演算法」的估值生效，掛單估值不打折以免低估售價。
    # 這裡回傳兩種角度由呼叫端取用，estimated_price 為市場掛牌估值（不折），
    # liquidity_score 另外帶出讓 optimizer 自行折算貢獻度。
    estimated = base.quantize(Decimal("0.01"))

    value = MarketValue(
        estimated_price=estimated,
        currency="TWD",
        avg_7d=extra.get("avg_7d"),
        highest_deal=extra.get("hi"),
        lowest_ask=extra.get("lo"),
        liquidity_score=round(float(liquidity_score), 2),
        tier_strategy=strategy,
        is_stale=False,
    )

    if use_cache:
        await _store_cache(redis, card_id, value)
    return value
