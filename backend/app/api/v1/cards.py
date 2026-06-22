"""/api/v1/cards/{card_id} —— 卡片詳情與歷史價格（Screen 3）。"""
from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.pricing import price_expr
from app.schemas.portfolio import CardDetail, CardSearchItem, PricePoint

logger = logging.getLogger("ptcg.cards")

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])


# 此路由必須宣告在 /{card_id:path} 之前，否則 'search' 會被當成 card_id 吃掉。
@router.get("/search", response_model=list[CardSearchItem])
async def search_cards(
    q: str = Query(..., min_length=1, description="卡名 / 卡號 / set_code 關鍵字"),
    user_id: str | None = Query(default=None),
    lang: str | None = Query(default="tw"),
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> list[CardSearchItem]:
    """卡片百科搜尋：用卡名或卡號比對，供手動加入庫存。"""
    kw = q.strip()
    if not kw:
        return []
    like = f"%{kw}%"
    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT card_id, set_code, card_number, rarity, name_zh,
                           image_url,
                           {price_expr(lang, 'cards')} AS market_value
                    FROM cards
                    WHERE name_zh ILIKE :like
                       OR card_id ILIKE :like
                       OR set_code ILIKE :like
                       OR card_number ILIKE :like
                       OR (set_code || ' ' || card_number) ILIKE :like
                    ORDER BY
                        -- 名稱開頭命中優先，其次卡號開頭，再依市值高到低
                        (name_zh ILIKE :prefix) DESC,
                        (card_number ILIKE :prefix) DESC,
                        {price_expr(lang, 'cards')} DESC
                    LIMIT :limit
                    """
                ),
                {"like": like, "prefix": f"{kw}%", "limit": limit},
            )
        ).mappings().all()

        owned: dict[str, int] = {}
        if user_id and rows:
            ids = [r["card_id"] for r in rows]
            crows = (
                await session.execute(
                    text(
                        """
                        SELECT card_id, COALESCE(SUM(quantity),0) AS qty
                        FROM user_inventory
                        WHERE user_id = CAST(:uid AS uuid)
                          AND card_id = ANY(:ids)
                        GROUP BY card_id
                        """
                    ),
                    {"uid": user_id, "ids": ids},
                )
            ).mappings().all()
            owned = {r["card_id"]: int(r["qty"]) for r in crows}
    except SQLAlchemyError:
        logger.exception("卡片搜尋失敗 q=%s", kw)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="搜尋暫時無法使用",
        )

    return [
        CardSearchItem(
            card_id=r["card_id"],
            set_code=r["set_code"],
            card_number=r["card_number"],
            rarity=r["rarity"],
            name_zh=r["name_zh"],
            image_url=r["image_url"],
            market_value=Decimal(r["market_value"]).quantize(Decimal("0.01")),
            owned_qty=owned.get(r["card_id"], 0),
        )
        for r in rows
    ]


# card_id 內含斜線（如 'SV8a_217/187'），用 :path 轉換器才能正確匹配整段
@router.get("/{card_id:path}", response_model=CardDetail)
async def card_detail(
    card_id: str,
    user_id: str | None = Query(default=None),
    history_days: int = Query(default=90, ge=1, le=365),
    lang: str | None = Query(default="tw"),
    session: AsyncSession = Depends(get_db),
) -> CardDetail:
    try:
        card = (
            await session.execute(
                text(
                    f"""
                    SELECT card_id, set_code, card_number, rarity, name_zh,
                           {price_expr(lang, 'cards')} AS current_price,
                           liquidity_score
                    FROM cards WHERE card_id = :cid
                    """
                ),
                {"cid": card_id},
            )
        ).mappings().first()
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="找不到卡片"
            )

        stats = (
            await session.execute(
                text(
                    """
                    SELECT
                        AVG(price) FILTER (
                            WHERE recorded_date >= CURRENT_DATE - INTERVAL '7 days'
                        ) AS avg_7d,
                        MAX(price) AS hi,
                        MIN(price) AS lo
                    FROM price_history WHERE card_id = :cid
                    """
                ),
                {"cid": card_id},
            )
        ).mappings().first()

        hist = (
            await session.execute(
                text(
                    """
                    SELECT recorded_date, price, volume
                    FROM price_history
                    WHERE card_id = :cid
                      AND recorded_date >= CURRENT_DATE - make_interval(days => :days)
                    ORDER BY recorded_date ASC
                    """
                ),
                {"cid": card_id, "days": history_days},
            )
        ).mappings().all()

        owned = {"qty": 0, "fav": False, "elig": True}
        if user_id:
            inv = (
                await session.execute(
                    text(
                        """
                        SELECT COALESCE(SUM(quantity),0) AS qty,
                               BOOL_OR(COALESCE(is_favorite,FALSE)) AS fav,
                               BOOL_OR(COALESCE(pack_eligible,TRUE)) AS elig
                        FROM user_inventory
                        WHERE user_id = CAST(:uid AS uuid) AND card_id = :cid
                        """
                    ),
                    {"uid": user_id, "cid": card_id},
                )
            ).mappings().first()
            if inv and inv["qty"]:
                owned = {
                    "qty": int(inv["qty"]),
                    "fav": bool(inv["fav"]),
                    "elig": bool(inv["elig"]),
                }
    except SQLAlchemyError:
        logger.exception("card detail 失敗 card=%s", card_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="無法載入卡片詳情",
        )

    def _dec(v) -> Decimal | None:
        return Decimal(v).quantize(Decimal("0.01")) if v is not None else None

    return CardDetail(
        card_id=card["card_id"],
        set_code=card["set_code"],
        card_number=card["card_number"],
        rarity=card["rarity"],
        name_zh=card["name_zh"],
        current_price=Decimal(card["current_price"]).quantize(Decimal("0.01")),
        liquidity_score=float(card["liquidity_score"]),
        avg_7d=_dec(stats["avg_7d"]) if stats else None,
        highest_deal=_dec(stats["hi"]) if stats else None,
        lowest_ask=_dec(stats["lo"]) if stats else None,
        owned_qty=owned["qty"],
        is_favorite=owned["fav"],
        pack_eligible=owned["elig"],
        price_history=[
            PricePoint(
                recorded_date=str(h["recorded_date"]),
                price=Decimal(h["price"]).quantize(Decimal("0.01")),
                volume=int(h["volume"]),
            )
            for h in hist
        ],
    )
