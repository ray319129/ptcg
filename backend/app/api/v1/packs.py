"""/api/v1/packs —— 神秘包最佳化與出貨單 PDF 端點。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.packs import (
    OptimizeRequest,
    OptimizeResponse,
    serialize_result,
)
from app.services.optimizer import optimize_mystery_packs
from app.services.packs_repo import (
    load_eligible_inventory,
    load_plan,
    save_plan,
)
from app.services.pdf import build_packing_list_pdf

logger = logging.getLogger("ptcg.packs")

router = APIRouter(prefix="/api/v1/packs", tags=["packs"])


@router.post(
    "/optimize",
    response_model=OptimizeResponse,
    summary="依參數把可用庫存最佳化分配成神秘包，並持久化計畫",
)
async def optimize(
    payload: OptimizeRequest,
    session: AsyncSession = Depends(get_db),
) -> OptimizeResponse:
    # 1. 載入可用庫存
    try:
        inventory = await load_eligible_inventory(
            session, payload.user_id, payload.exclude_favorites, payload.lang
        )
    except SQLAlchemyError:
        logger.exception("載入庫存失敗 user=%s", payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="無法讀取庫存，請稍後再試",
        )

    if not inventory:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="沒有可用於神秘包的庫存（請確認卡片資格或最愛設定）",
        )

    # 2. 跑最佳化（純運算，不碰 DB）
    result = optimize_mystery_packs(
        inventory=inventory,
        total_packs=payload.total_packs,
        pack_price=payload.pack_price,
        target_margin=payload.target_margin,
        floor_ratio=payload.floor_ratio,
        guaranteed_rarity=payload.guaranteed_rarity,
    )

    response = serialize_result(
        result,
        total_packs=payload.total_packs,
        pack_price=payload.pack_price,
        target_margin=payload.target_margin,
    )

    # 3. 持久化（即使不可行也存，方便使用者回看調參建議）
    try:
        plan_id = await save_plan(
            session,
            user_id=payload.user_id,
            total_packs=payload.total_packs,
            pack_price=payload.pack_price,
            target_margin=payload.target_margin,
            floor_ratio=payload.floor_ratio,
            response=response,
        )
        response.plan_id = plan_id
    except SQLAlchemyError:
        # 存檔失敗不應讓使用者拿不到結果：回傳結果但不附 plan_id。
        logger.exception("儲存計畫失敗 user=%s", payload.user_id)
        await session.rollback()

    return response


@router.get(
    "/{plan_id}/packing-list.pdf",
    summary="下載指定計畫的出貨單 PDF",
    response_class=StreamingResponse,
)
async def packing_list_pdf(
    plan_id: str,
    user_id: str | None = Query(
        default=None, description="擁有者驗證（建議帶上）"
    ),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    try:
        plan = await load_plan(session, plan_id, user_id)
    except SQLAlchemyError:
        logger.exception("讀取計畫失敗 plan=%s", plan_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="無法讀取計畫",
        )
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到計畫，或無權存取",
        )

    try:
        pdf_bytes = build_packing_list_pdf(plan)
    except Exception:
        logger.exception("產生 PDF 失敗 plan=%s", plan_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="產生 PDF 失敗",
        )

    filename = f"packing-list-{plan_id}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )
