"""/api/v1/scan/match —— 影像比對掃描（ManaBox 式）。

接收前端拍到的卡片影像 → MobileNet embedding → 與卡圖庫 cosine 比對 →
回傳最相近的卡片（及候選清單）。取代讀小字 OCR。
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
from app.services import image_match

logger = logging.getLogger("ptcg.match")

router = APIRouter(prefix="/api/v1/scan", tags=["scan"])

# 卡片視覺結構相近，候選相似度普遍偏高且彼此接近；Top-1 命中率高（模擬 92%），
# 故只要最佳相似度 >= MIN_SIM 就採用第 1 名，並一律附候選讓使用者一鍵更正。
MIN_SIM = 0.70
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

    # 1) 偵測卡片 → embedding → 比對（CPU 運算，放到執行緒避免阻塞事件迴圈）
    try:
        import anyio

        pairs, detected = await anyio.to_thread.run_sync(_embed_and_match, data)
    except FileNotFoundError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "卡圖索引尚未建立（請先執行 image_match --build）",
        )
    except Exception:  # noqa: BLE001
        logger.exception("影像比對失敗")
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
    hint = "" if detected else "（未偵測到卡片邊框，請讓整張卡入鏡）"
    if top.similarity >= MIN_SIM:
        return MatchResponse(
            success=True, best=top, candidates=candidates,
            detected=detected, message="命中",
        )
    return MatchResponse(
        success=False, candidates=candidates, detected=detected,
        message=f"相似度偏低，請重拍或從候選確認{hint}",
    )


def _embed_and_match(data: bytes) -> tuple[list[tuple[str, float]], bool]:
    q, detected = image_match.embed_query(data)
    if q is None:  # 畫面中沒偵測到卡片 → 不比對
        return [], detected
    return image_match.match(q, top_k=5), detected
