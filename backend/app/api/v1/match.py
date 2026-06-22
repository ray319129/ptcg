"""/api/v1/scan/match —— 卡片影像辨識掃描。

接收前端拍到的影像 → 偵測卡片 → SIFT 局部特徵 + RANSAC 幾何驗證比對卡圖庫 →
回傳最相近的卡片（及候選清單）。對 holo/AR 強反光遠比全域 embedding 穩健。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.pricing import price_expr
from app.schemas.imatch import MatchCandidate, MatchResponse
from app.services import sift_match

logger = logging.getLogger("ptcg.match")

router = APIRouter(prefix="/api/v1/scan", tags=["scan"])

MAX_UPLOAD = 6 * 1024 * 1024  # 6MB


async def _hydrate(
    session: AsyncSession,
    pairs: list[tuple[str, float]],
    user_id: str | None,
    lang: str | None,
) -> list[MatchCandidate]:
    """把 (card_id, similarity) 補上卡片資料與持有數（依語言取價）。"""
    if not pairs:
        return []
    ids = [cid for cid, _ in pairs]
    rows = (
        await session.execute(
            text(
                f"""
                SELECT card_id, set_code, card_number, rarity, name_zh,
                       image_url, {price_expr(lang, 'cards')} AS price
                FROM cards WHERE card_id = ANY(:ids)
                """
            ),
            {"ids": ids},
        )
    ).mappings().all()
    by_id = {r["card_id"]: r for r in rows}

    counts: dict[str, int] = {}
    if user_id:
        crows = (
            await session.execute(
                text(
                    """
                    SELECT card_id, COALESCE(SUM(quantity),0) AS qty
                    FROM user_inventory
                    WHERE user_id = CAST(:uid AS uuid) AND card_id = ANY(:ids)
                    GROUP BY card_id
                    """
                ),
                {"uid": user_id, "ids": ids},
            )
        ).mappings().all()
        counts = {r["card_id"]: int(r["qty"]) for r in crows}

    out: list[MatchCandidate] = []
    for cid, sim in pairs:
        r = by_id.get(cid)
        if not r:
            continue
        out.append(
            MatchCandidate(
                card_id=r["card_id"],
                set_code=r["set_code"],
                card_number=r["card_number"],
                rarity=r["rarity"],
                name_zh=r["name_zh"],
                image_url=r["image_url"],
                market_value=r["price"],
                in_collection_count=counts.get(cid, 0),
                similarity=round(sim, 4),
            )
        )
    return out


@router.post("/match", response_model=MatchResponse)
async def match_card(
    image: UploadFile = File(...),
    user_id: str | None = Form(default=None),
    lang: str | None = Form(default="tw"),
    session: AsyncSession = Depends(get_db),
) -> MatchResponse:
    data = await image.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "空的影像")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "影像過大")

    # 1) 偵測卡片 → SIFT 局部特徵 + 幾何驗證辨識（CPU 運算，放到執行緒避免阻塞事件迴圈）
    try:
        import anyio

        pairs, detected, confident = await anyio.to_thread.run_sync(_identify, data)
    except FileNotFoundError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "卡圖索引尚未建立（請先執行 python -m app.services.sift_match --build）",
        )
    except Exception:  # noqa: BLE001
        logger.exception("影像辨識失敗")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "影像無法辨識，請重拍")

    # 2) 補卡片資料
    try:
        candidates = await _hydrate(session, pairs, user_id, lang)
    except SQLAlchemyError:
        logger.exception("hydrate 候選失敗")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "資料庫忙碌")

    if not candidates:
        msg = (
            "找不到相符的卡片"
            if detected
            else "未偵測到卡片，請將整張卡片完整放入鏡頭"
        )
        return MatchResponse(success=False, detected=detected, message=msg)

    top = candidates[0]
    # confident=幾何內點數達門檻且明顯領先 → 採信並自動回報；否則由連續掃描下一幀再試
    if confident:
        return MatchResponse(
            success=True, best=top, candidates=candidates,
            detected=detected, message="命中",
        )
    return MatchResponse(
        success=False, candidates=candidates, detected=detected,
        message="信心不足，請重拍或從候選確認",
    )


# 內點數→0~1 顯示用信心（候選清單的百分比）。40 內點視為滿信心。
def _conf(inliers: int) -> float:
    return min(inliers / 40.0, 1.0)


def _identify(data: bytes) -> tuple[list[tuple[str, float]], bool, bool]:
    scored, detected, confident = sift_match.identify(data)
    pairs = [(cid, _conf(inl)) for cid, inl in scored]
    return pairs, detected, confident
