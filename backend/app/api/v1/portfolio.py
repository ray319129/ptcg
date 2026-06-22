"""/api/v1 —— 儀表板彙總、庫存清單與單項更新。"""
from __future__ import annotations

import logging
from decimal import Decimal

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.pricing import price_expr
from app.schemas.portfolio import (
    InventoryAdd,
    InventoryAddResult,
    InventoryBulk,
    InventoryBulkResult,
    InventoryClear,
    InventoryItem,
    InventoryPage,
    InventoryPatch,
    PortfolioSummary,
    RarityRatio,
    SpikeItem,
)

logger = logging.getLogger("ptcg.portfolio")

router = APIRouter(prefix="/api/v1", tags=["portfolio"])

# 流動性低於此值視為「滯銷」
DEAD_STOCK_THRESHOLD = 0.30


@router.get("/portfolio/summary", response_model=PortfolioSummary)
async def portfolio_summary(
    user_id: str = Query(...),
    lang: str | None = Query(default="tw"),
    session: AsyncSession = Depends(get_db),
) -> PortfolioSummary:
    try:
        # 1) 淨值 / 張數 / 平均流動性 / 滯銷數（單次彙總查詢，依語言取價）
        agg = (
            await session.execute(
                text(
                    f"""
                    SELECT
                        COALESCE(SUM(ui.quantity * {price_expr(lang, 'c')}), 0) AS net_worth,
                        COALESCE(SUM(ui.quantity), 0)                   AS total_cards,
                        COALESCE(
                            SUM(ui.quantity * c.liquidity_score)
                            / NULLIF(SUM(ui.quantity), 0), 0)           AS avg_liq,
                        COALESCE(SUM(ui.quantity) FILTER (
                            WHERE c.liquidity_score < :dead), 0)        AS dead_cnt
                    FROM user_inventory ui
                    JOIN cards c ON c.card_id = ui.card_id
                    WHERE ui.user_id = CAST(:uid AS uuid)
                    """
                ),
                {"uid": user_id, "dead": DEAD_STOCK_THRESHOLD},
            )
        ).mappings().first()

        # 2) 稀有度分布
        rar_rows = (
            await session.execute(
                text(
                    """
                    SELECT c.rarity, SUM(ui.quantity) AS cnt
                    FROM user_inventory ui
                    JOIN cards c ON c.card_id = ui.card_id
                    WHERE ui.user_id = CAST(:uid AS uuid)
                    GROUP BY c.rarity
                    ORDER BY cnt DESC
                    """
                ),
                {"uid": user_id},
            )
        ).mappings().all()

        # 3) 24h 變動 + 近 7 日淨值 sparkline（以 price_history 為準）
        spark_rows = (
            await session.execute(
                text(
                    """
                    WITH days AS (
                        SELECT generate_series(
                            CURRENT_DATE - INTERVAL '6 days',
                            CURRENT_DATE, INTERVAL '1 day')::date AS d
                    )
                    SELECT days.d AS day,
                        COALESCE(SUM(
                            ui.quantity * COALESCE(ph.price, c.current_price)
                        ), 0) AS value
                    FROM days
                    CROSS JOIN user_inventory ui
                    JOIN cards c ON c.card_id = ui.card_id
                    LEFT JOIN LATERAL (
                        SELECT price FROM price_history p
                        WHERE p.card_id = ui.card_id
                          AND p.recorded_date <= days.d
                        ORDER BY p.recorded_date DESC LIMIT 1
                    ) ph ON TRUE
                    WHERE ui.user_id = CAST(:uid AS uuid)
                    GROUP BY days.d
                    ORDER BY days.d
                    """
                ),
                {"uid": user_id},
            )
        ).mappings().all()

        # 4) 今日波動 > 10% 的持有卡
        spikes = (
            await session.execute(
                text(
                    """
                    WITH today AS (
                        SELECT DISTINCT ON (card_id) card_id, price
                        FROM price_history
                        WHERE recorded_date <= CURRENT_DATE
                        ORDER BY card_id, recorded_date DESC
                    ), yest AS (
                        SELECT DISTINCT ON (card_id) card_id, price
                        FROM price_history
                        WHERE recorded_date <= CURRENT_DATE - INTERVAL '1 day'
                        ORDER BY card_id, recorded_date DESC
                    )
                    SELECT c.card_id, c.name_zh, c.rarity, t.price,
                        ROUND(((t.price - y.price) / NULLIF(y.price,0) * 100)::numeric, 2)
                            AS change_pct
                    FROM user_inventory ui
                    JOIN cards c ON c.card_id = ui.card_id
                    JOIN today t ON t.card_id = ui.card_id
                    JOIN yest  y ON y.card_id = ui.card_id
                    WHERE ui.user_id = CAST(:uid AS uuid)
                      AND ABS((t.price - y.price) / NULLIF(y.price,0)) >= 0.10
                    GROUP BY c.card_id, c.name_zh, c.rarity, t.price, y.price
                    ORDER BY ABS((t.price - y.price) / NULLIF(y.price,0)) DESC
                    LIMIT 12
                    """
                ),
                {"uid": user_id},
            )
        ).mappings().all()
    except SQLAlchemyError:
        logger.exception("portfolio summary 失敗 user=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="無法載入儀表板",
        )

    total = int(agg["total_cards"]) if agg else 0
    rarity_dist = [
        RarityRatio(
            rarity=r["rarity"],
            count=int(r["cnt"]),
            pct=round(int(r["cnt"]) / total, 4) if total else 0.0,
        )
        for r in rar_rows
    ]

    sparkline = [Decimal(r["value"]).quantize(Decimal("0.01")) for r in spark_rows]
    # 24h 變動：sparkline 最後兩點
    change_24h = 0.0
    if len(sparkline) >= 2 and sparkline[-2] > 0:
        change_24h = float(
            (sparkline[-1] - sparkline[-2]) / sparkline[-2] * 100
        )

    return PortfolioSummary(
        net_worth=Decimal(agg["net_worth"]).quantize(Decimal("0.01")) if agg else Decimal("0.00"),
        change_24h_pct=round(change_24h, 2),
        sparkline=sparkline,
        total_cards=total,
        rarity_distribution=rarity_dist,
        avg_liquidity=round(float(agg["avg_liq"]), 3) if agg else 0.0,
        dead_stock_count=int(agg["dead_cnt"]) if agg else 0,
        recent_spikes=[
            SpikeItem(
                card_id=s["card_id"],
                name_zh=s["name_zh"],
                rarity=s["rarity"],
                price=Decimal(s["price"]).quantize(Decimal("0.01")),
                change_pct=float(s["change_pct"]),
            )
            for s in spikes
        ],
    )


@router.get("/inventory", response_model=InventoryPage)
async def list_inventory(
    user_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    favorites_only: bool = Query(False),
    lang: str | None = Query(default="tw"),
    session: AsyncSession = Depends(get_db),
) -> InventoryPage:
    try:
        total = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM user_inventory ui
                    WHERE ui.user_id = CAST(:uid AS uuid)
                      AND (:all OR COALESCE(ui.is_favorite, FALSE) = TRUE)
                    """
                ),
                {"uid": user_id, "all": not favorites_only},
            )
        ).scalar_one()

        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT ui.card_id, c.set_code, c.card_number, c.name_zh,
                           c.rarity, ui.quantity, c.image_url,
                           {price_expr(lang, 'c')} AS market_value,
                           c.liquidity_score,
                           COALESCE(ui.is_favorite, FALSE)   AS is_favorite,
                           COALESCE(ui.pack_eligible, TRUE)  AS pack_eligible
                    FROM user_inventory ui
                    JOIN cards c ON c.card_id = ui.card_id
                    WHERE ui.user_id = CAST(:uid AS uuid)
                      AND (:all OR COALESCE(ui.is_favorite, FALSE) = TRUE)
                    ORDER BY c.current_price DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    "uid": user_id,
                    "all": not favorites_only,
                    "limit": limit,
                    "offset": offset,
                },
            )
        ).mappings().all()
    except SQLAlchemyError:
        logger.exception("list inventory 失敗 user=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="無法載入庫存",
        )

    items = [
        InventoryItem(
            card_id=r["card_id"],
            set_code=r["set_code"],
            card_number=r["card_number"],
            name_zh=r["name_zh"],
            rarity=r["rarity"],
            quantity=int(r["quantity"]),
            market_value=Decimal(r["market_value"]).quantize(Decimal("0.01")),
            liquidity_score=float(r["liquidity_score"]),
            is_favorite=bool(r["is_favorite"]),
            pack_eligible=bool(r["pack_eligible"]),
            image_url=r["image_url"],
        )
        for r in rows
    ]
    return InventoryPage(items=items, total=int(total), limit=limit, offset=offset)


@router.post("/inventory/add", response_model=InventoryAddResult)
async def add_inventory(
    payload: InventoryAdd,
    session: AsyncSession = Depends(get_db),
) -> InventoryAddResult:
    """掃描自動入庫：同卡累加數量，回傳新數量與卡片資訊（給前端浮層顯示）。"""
    try:
        # 先確認卡片存在於百科
        card = (
            await session.execute(
                text(
                    "SELECT name_zh, rarity, COALESCE(current_price,0) AS price"
                    " FROM cards WHERE card_id = :cid"
                ),
                {"cid": payload.card_id},
            )
        ).mappings().first()
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="卡片不存在"
            )
        new_qty = (
            await session.execute(
                text(
                    """
                    INSERT INTO user_inventory (user_id, card_id, quantity)
                    VALUES (CAST(:uid AS uuid), :cid, :q)
                    ON CONFLICT (user_id, card_id) DO UPDATE
                        SET quantity = user_inventory.quantity + EXCLUDED.quantity
                    RETURNING quantity
                    """
                ),
                {"uid": payload.user_id, "cid": payload.card_id, "q": payload.quantity},
            )
        ).scalar_one()
        await session.commit()
    except HTTPException:
        raise
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("add inventory 失敗 user=%s card=%s",
                         payload.user_id, payload.card_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="入庫失敗"
        )

    return InventoryAddResult(
        card_id=payload.card_id,
        new_quantity=int(new_qty),
        name_zh=card["name_zh"],
        rarity=card["rarity"],
        market_value=Decimal(card["price"]).quantize(Decimal("0.01")),
    )


@router.post("/inventory/bulk", response_model=InventoryBulkResult)
async def bulk_inventory(
    payload: InventoryBulk,
    session: AsyncSession = Depends(get_db),
) -> InventoryBulkResult:
    """批次編輯選取的庫存卡：delete=True 刪除，否則套用最愛 / 神秘包資格。"""
    try:
        if payload.delete:
            res = await session.execute(
                text(
                    """
                    DELETE FROM user_inventory
                    WHERE user_id = CAST(:uid AS uuid)
                      AND card_id = ANY(:ids)
                    """
                ),
                {"uid": payload.user_id, "ids": payload.card_ids},
            )
        else:
            sets = []
            params: dict = {"uid": payload.user_id, "ids": payload.card_ids}
            if payload.is_favorite is not None:
                sets.append("is_favorite = :fav")
                params["fav"] = payload.is_favorite
            if payload.pack_eligible is not None:
                sets.append("pack_eligible = :elig")
                params["elig"] = payload.pack_eligible
            if not sets:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="沒有可更新的欄位",
                )
            res = await session.execute(
                text(
                    f"""
                    UPDATE user_inventory SET {', '.join(sets)}
                    WHERE user_id = CAST(:uid AS uuid)
                      AND card_id = ANY(:ids)
                    """
                ),
                params,
            )
        await session.commit()
    except HTTPException:
        raise
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("bulk inventory 失敗 user=%s", payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="批次更新失敗"
        )
    return InventoryBulkResult(affected=res.rowcount or 0)


@router.post("/inventory/clear", response_model=InventoryBulkResult)
async def clear_inventory(
    payload: InventoryClear,
    session: AsyncSession = Depends(get_db),
) -> InventoryBulkResult:
    """一鍵清空使用者的整個收藏。"""
    try:
        res = await session.execute(
            text(
                "DELETE FROM user_inventory WHERE user_id = CAST(:uid AS uuid)"
            ),
            {"uid": payload.user_id},
        )
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("clear inventory 失敗 user=%s", payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="清空失敗"
        )
    return InventoryBulkResult(affected=res.rowcount or 0)


@router.get("/inventory/export.csv", response_class=StreamingResponse)
async def export_inventory_csv(
    user_id: str = Query(...),
    lang: str | None = Query(default="tw"),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """把使用者庫存匯出成 CSV（含單價/小計，依語言取價）。"""
    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT c.set_code, c.card_number, c.rarity, c.name_zh,
                           ui.quantity, {price_expr(lang, 'c')} AS unit_price
                    FROM user_inventory ui
                    JOIN cards c ON c.card_id = ui.card_id
                    WHERE ui.user_id = CAST(:uid AS uuid)
                    ORDER BY c.set_code, c.card_number
                    """
                ),
                {"uid": user_id},
            )
        ).mappings().all()
    except SQLAlchemyError:
        logger.exception("export csv 失敗 user=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="匯出失敗"
        )

    buf = io.StringIO()
    buf.write("﻿")  # BOM，讓 Excel 正確顯示中文
    w = csv.writer(buf)
    lang_label = "日文版" if (lang or "tw").lower() == "jp" else "繁中版"
    w.writerow(["展開", "卡號", "稀有度", "名稱", "數量", f"單價({lang_label})", "小計"])
    total = 0.0
    for r in rows:
        unit = float(r["unit_price"] or 0)
        sub = unit * int(r["quantity"])
        total += sub
        w.writerow([
            r["set_code"], r["card_number"], r["rarity"], r["name_zh"],
            r["quantity"], f"{unit:.0f}", f"{sub:.0f}",
        ])
    w.writerow([])
    w.writerow(["", "", "", "", "", "總價值", f"{total:.0f}"])

    data = buf.getvalue().encode("utf-8")
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="inventory.csv"'},
    )


@router.patch("/inventory/{card_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def patch_inventory(
    card_id: str,
    patch: InventoryPatch,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> None:
    """更新數量 / 最愛 / 神秘包資格。只更新有帶值的欄位。"""
    sets = []
    params: dict = {"uid": user_id, "cid": card_id}
    if patch.quantity is not None:
        sets.append("quantity = :qty")
        params["qty"] = patch.quantity
    if patch.is_favorite is not None:
        sets.append("is_favorite = :fav")
        params["fav"] = patch.is_favorite
    if patch.pack_eligible is not None:
        sets.append("pack_eligible = :elig")
        params["elig"] = patch.pack_eligible
    if not sets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="沒有可更新的欄位"
        )

    try:
        res = await session.execute(
            text(
                f"""
                UPDATE user_inventory SET {', '.join(sets)}
                WHERE user_id = CAST(:uid AS uuid) AND card_id = :cid
                """
            ),
            params,
        )
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("patch inventory 失敗 user=%s card=%s", user_id, card_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="更新失敗",
        )
    if res.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="庫存項不存在"
        )
