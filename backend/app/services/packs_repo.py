"""神秘包的資料存取層：載入可用庫存、持久化/讀取已產生的計畫。"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pricing import price_expr
from app.schemas.packs import OptimizeResponse
from app.services.optimizer import InventoryCard, expand_inventory


async def load_eligible_inventory(
    session: AsyncSession,
    user_id: str,
    exclude_favorites: bool = True,
    lang: str | None = "tw",
) -> list[InventoryCard]:
    """讀取該使用者「可進神秘包」的庫存，攤平成單卡清單。

    篩選條件：
      - pack_eligible = TRUE（對應 UI 的「納入神秘包資格」開關）
      - 可選排除 is_favorite
      - market_value 依語言取 price_jp / price_tw
    """
    pe = price_expr(lang, "c")
    sql = text(
        f"""
        SELECT ui.card_id,
               c.name_zh,
               c.rarity,
               c.card_type,
               {pe}                           AS market_value,
               COALESCE(c.liquidity_score, 1) AS liquidity_score,
               SUM(ui.quantity)               AS quantity
        FROM user_inventory ui
        JOIN cards c ON c.card_id = ui.card_id
        WHERE ui.user_id = CAST(:uid AS uuid)
          AND COALESCE(ui.pack_eligible, TRUE) = TRUE
          AND (:keep_fav OR COALESCE(ui.is_favorite, FALSE) = FALSE)
        GROUP BY ui.card_id, c.name_zh, c.rarity, c.card_type, c.price_jp, c.price_tw,
                 c.current_price, c.liquidity_score
        HAVING SUM(ui.quantity) > 0
        """
    )
    rows = await session.execute(
        sql, {"uid": user_id, "keep_fav": not exclude_favorites}
    )
    dict_rows = [
        {
            "card_id": r["card_id"],
            "name_zh": r["name_zh"],
            "rarity": r["rarity"],
            "market_value": Decimal(str(r["market_value"])),
            "liquidity_score": float(r["liquidity_score"]),
            "quantity": int(r["quantity"]),
            "card_type": r["card_type"],
        }
        for r in rows.mappings()
    ]
    return expand_inventory(dict_rows)


async def save_plan(
    session: AsyncSession,
    user_id: str,
    total_packs: int,
    pack_price: Decimal,
    target_margin: float,
    floor_ratio: float,
    response: OptimizeResponse,
) -> str:
    """把計畫結果存入 pack_plans，回傳 plan_id。"""
    sql = text(
        """
        INSERT INTO pack_plans
            (user_id, total_packs, pack_price, target_margin,
             floor_ratio, feasible, result)
        VALUES
            (CAST(:uid AS uuid), :n, :price, :margin,
             :floor, :feasible, CAST(:result AS jsonb))
        RETURNING plan_id
        """
    )
    # 用 Pydantic 的 JSON 序列化確保 Decimal/日期等型別正確落地。
    result_json = response.model_dump_json()
    row = await session.execute(
        sql,
        {
            "uid": user_id,
            "n": total_packs,
            "price": pack_price,
            "margin": target_margin,
            "floor": floor_ratio,
            "feasible": response.feasible,
            "result": result_json,
        },
    )
    await session.commit()
    return str(row.scalar_one())


async def load_plan(
    session: AsyncSession, plan_id: str, user_id: Optional[str] = None
) -> Optional[OptimizeResponse]:
    """依 plan_id 讀回計畫；指定 user_id 時做擁有者驗證。"""
    clauses = "plan_id = CAST(:pid AS uuid)"
    params: dict = {"pid": plan_id}
    if user_id is not None:
        clauses += " AND user_id = CAST(:uid AS uuid)"
        params["uid"] = user_id
    sql = text(f"SELECT result FROM pack_plans WHERE {clauses}")
    row = (await session.execute(sql, params)).first()
    if row is None:
        return None
    data = row[0]
    # asyncpg 可能回傳 dict（jsonb）或 str，兩種都處理。
    if isinstance(data, str):
        data = json.loads(data)
    return OptimizeResponse.model_validate(data)
