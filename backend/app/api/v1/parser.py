"""/api/v1/parser/scan 端點。

職責：接收 OCR 原始字串 → 解析/模糊比對 → 查百科 + 庫存 + 估價 → 回傳統一格式。
任何下游錯誤都轉成結構化回應或標準 HTTP 例外，不讓 stack trace 外洩。
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db, get_redis
from app.schemas.scan import (
    CardProfile,
    MatchMethod,
    ScanRequest,
    ScanResponse,
)
from app.services.parser import resolve_card
from app.services.valuation import value_card

logger = logging.getLogger("ptcg.parser")

router = APIRouter(prefix="/api/v1/parser", tags=["parser"])


async def _load_card_row(session: AsyncSession, card_id: str) -> dict | None:
    """讀百科主檔的卡片基本資料 + 流動性 + meta 旗標。"""
    sql = text(
        """
        SELECT card_id, set_code, card_number, rarity, name_zh,
               liquidity_score,
               COALESCE(is_meta, FALSE) AS is_meta
        FROM cards
        WHERE card_id = :cid
        """
    )
    row = (await session.execute(sql, {"cid": card_id})).mappings().first()
    return dict(row) if row else None


async def _collection_count(
    session: AsyncSession, user_id: str | None, card_id: str
) -> int:
    """查該使用者已持有數量；未登入回 0。"""
    if not user_id:
        return 0
    sql = text(
        """
        SELECT COALESCE(SUM(quantity), 0) AS qty
        FROM user_inventory
        WHERE user_id = CAST(:uid AS uuid) AND card_id = :cid
        """
    )
    r = (await session.execute(sql, {"uid": user_id, "cid": card_id})).first()
    return int(r[0]) if r and r[0] else 0


@router.post(
    "/scan",
    response_model=ScanResponse,
    status_code=status.HTTP_200_OK,
    summary="解析 OCR 字串並回傳卡片檔案與即時市值",
)
async def scan(
    payload: ScanRequest,
    session: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> ScanResponse:
    try:
        method, card_id, candidates = await resolve_card(
            session, payload.raw_text, payload.client_confidence
        )
    except SQLAlchemyError:
        # DB 層錯誤：記錄細節但對外只回 503，避免洩漏 schema。
        logger.exception("resolve_card DB error for raw=%r", payload.raw_text)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="資料庫暫時無法服務，請稍後再試",
        )

    # --- 找不到 -------------------------------------------------------------
    if method == MatchMethod.NOT_FOUND:
        return ScanResponse(
            success=False,
            method=method,
            message=f"無法辨識卡片：{payload.raw_text}",
        )

    # --- 模糊但多候選：回傳候選讓前端開「你是不是要找？」抽屜 ----------------
    if method == MatchMethod.AMBIGUOUS:
        return ScanResponse(
            success=False,
            method=method,
            candidates=candidates,
            message="辨識結果不唯一，請從候選中確認",
        )

    # --- 唯一命中：組裝完整檔案 ---------------------------------------------
    assert card_id is not None  # 上面非 ambiguous/not_found 必有 card_id
    card = await _load_card_row(session, card_id)
    if card is None:
        # 理論上 resolve_card 已驗證存在；防禦性處理資料不一致。
        logger.error("resolve 命中 %s 但百科查無資料", card_id)
        return ScanResponse(
            success=False,
            method=MatchMethod.NOT_FOUND,
            message="卡片索引與百科資料不一致",
        )

    try:
        market = await value_card(
            session=session,
            redis=redis,
            card_id=card["card_id"],
            rarity=card["rarity"],
            liquidity_score=float(card["liquidity_score"]),
            is_meta=bool(card["is_meta"]),
        )
    except (SQLAlchemyError, aioredis.RedisError):
        # 估價失敗不應讓整個掃描失敗：降級回傳百科的 last known price。
        logger.exception("估價失敗，降級處理 card_id=%s", card_id)
        market = await _fallback_value(session, card)

    count = await _collection_count(session, payload.user_id, card_id)

    profile = CardProfile(
        card_id=card["card_id"],
        set_code=card["set_code"],
        card_number=card["card_number"],
        rarity=card["rarity"],
        name_zh=card["name_zh"],
        market_value=market,
        in_collection_count=count,
    )
    return ScanResponse(
        success=True,
        method=method,
        profile=profile,
        message="命中",
    )


async def _fallback_value(session: AsyncSession, card: dict):
    """估價引擎掛掉時的降級估值，標記 is_stale 讓前端顯示警示。"""
    from decimal import Decimal

    from app.schemas.scan import MarketValue

    r = (
        await session.execute(
            text("SELECT current_price FROM cards WHERE card_id = :cid"),
            {"cid": card["card_id"]},
        )
    ).first()
    price = Decimal(r[0]) if r and r[0] is not None else Decimal("0.00")
    return MarketValue(
        estimated_price=price,
        currency="TWD",
        liquidity_score=round(float(card["liquidity_score"]), 2),
        tier_strategy="fallback_last_known",
        is_stale=True,
    )
