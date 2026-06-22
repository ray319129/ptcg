"""把卡拍拍有、但官網尚未上架的卡片補進 cards 表（例如 M5 的特卡 082+）。

來源：getCardPackDetailList?game=pkmjp&packId=<CODE>
只新增「我們 DB 還沒有」的卡；已存在者不動（官網資料優先，含卡圖）。
這些補進來的卡 source='cardpaipai'、暫無卡圖，待官網上架後重跑 tw_official 補圖。

用法：
    python -m ingest.cardpaipai_cards --packs M5
    python -m ingest.cardpaipai_cards            # 預設 DB 既有全部展開
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from collections import Counter
from decimal import Decimal

import asyncpg

from ingest.cardpaipai_price import (
    api_get,
    kapaipai_pack_index,
    norm_num,
    GAME,
)

DB_DSN = os.getenv("PG_DSN", "postgresql://ptcg:0907@127.0.0.1:55432/ptcg")


def fetch_pack_cards(pack_id: str) -> list[dict]:
    d = api_get(f"/card/getCardPackDetailList?game={GAME}&packId={pack_id}")
    return d.get("data", {}).get("list", [])


async def base_total(conn: asyncpg.Connection, set_code: str) -> str:
    """取該展開官網卡號的「總數」眾數（如 M5 → '081'）。"""
    rows = await conn.fetch(
        "SELECT card_number FROM cards WHERE set_code=$1 AND source='tw_official'",
        set_code,
    )
    totals = [r["card_number"].split("/")[1] for r in rows
              if "/" in r["card_number"]]
    return Counter(totals).most_common(1)[0][0] if totals else "000"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", default=None)
    args = ap.parse_args()

    conn = await asyncpg.connect(DB_DSN)
    try:
        if args.packs:
            sets = [s.strip().upper() for s in args.packs.split(",") if s.strip()]
        else:
            rows = await conn.fetch(
                "SELECT DISTINCT set_code FROM cards WHERE source='tw_official'"
            )
            sets = [r["set_code"] for r in rows]

        kp_index = kapaipai_pack_index()
        total_added = 0
        for sc in sets:
            kp_pid = kp_index.get(sc.upper())
            if not kp_pid:
                continue
            total = await base_total(conn, sc)
            existing = {
                norm_num(r["card_number"])
                for r in await conn.fetch(
                    "SELECT card_number FROM cards WHERE set_code=$1", sc
                )
            }
            added = 0
            for c in fetch_pack_cards(kp_pid):
                num = norm_num(c.get("packCardId", ""))
                # 只收乾淨數字編號、且尚未存在者
                if not num.isdigit() or num in existing:
                    continue
                rare = c.get("rare")
                rarity = (rare[0] if isinstance(rare, list) and rare else
                          (rare if isinstance(rare, str) else "N/A")) or "N/A"
                name = (c.get("cardName") or "").strip() or "(未命名)"
                price = c.get("averagePrice") or c.get("lowestPrice") or 0
                card_number = f"{num}/{total}"
                card_id = f"{sc}_{card_number}"
                await conn.execute(
                    """
                    INSERT INTO cards
                        (card_id, set_code, card_number, rarity, name_zh,
                         current_price, liquidity_score, is_meta, source,
                         price_source, external_id)
                    VALUES ($1,$2,$3,$4,$5,$6,1.0,FALSE,'cardpaipai','cardpaipai',$7)
                    ON CONFLICT (card_id) DO NOTHING
                    """,
                    card_id, sc, card_number, rarity, name,
                    Decimal(str(price)), str(c.get("id", "")),
                )
                existing.add(num)
                added += 1
            if added:
                print(f"  - {sc}: 補入 {added} 張卡拍拍專屬卡")
            total_added += added
            time.sleep(0.3)
        print(f"\n完成：共補入 {total_added} 張。")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
