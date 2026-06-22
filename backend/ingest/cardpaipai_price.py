"""卡拍拍 (kapaipai) 在地台幣價格抓取器。

來源 API（公開讀取，無需認證）：
    GET https://trade.kapaipai.tw/api/card/getCardPackList?game=pkmjp
    GET https://trade.kapaipai.tw/api/card/getCardPackDetailList?game=pkmjp&packId=<CODE>

每包一次請求即取得整包卡片的 packCardId / rare / lowestPrice / averagePrice。
配對規則：本地 cards.set_code == kapaipai packId（不分大小寫），
          本地 card_number 前段（'001/081'→'001'）== packCardId，
          稀有度相同者優先；本地為 N/A 時用卡拍拍 rare 回填。

用法：
    python -m ingest.cardpaipai_price                 # 更新 DB 既有 13 個展開
    python -m ingest.cardpaipai_price --packs M5,SV9  # 指定展開
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import urllib.request
from decimal import Decimal

import asyncpg


def norm_num(raw: str) -> str:
    """正規化卡號以便兩邊比對。

    處理不同包的格式：'SV11W-001'→'001'、'001S'→'001'、'001/086'→'001'、'1'→'001'。
    """
    s = str(raw).upper().strip()
    s = s.split("/")[0]              # 去掉 /總數
    if "-" in s:
        s = s.split("-")[-1]         # 去掉 packId 前綴
    m = re.match(r"(\d+)", s)        # 取前導數字
    return m.group(1).zfill(3) if m else s

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"
API = "https://trade.kapaipai.tw/api"
GAME = "pkmjp"                     # 預設（pack 索引用）
GAMES = {"jp": "pkmjp", "tw": "pkmtw"}  # 日文版 / 繁體中文版
DB_DSN = os.getenv("PG_DSN", "postgresql://ptcg:0907@127.0.0.1:55432/ptcg")


def api_get(path: str) -> dict:
    req = urllib.request.Request(f"{API}{path}", headers={"User-Agent": UA})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:  # noqa: BLE001
            time.sleep(1.0)
    raise RuntimeError(f"API 失敗: {path}")


def kapaipai_pack_index() -> dict[str, str]:
    """回傳 {大寫packId: 原始packId}，供本地 set_code 不分大小寫對應。"""
    d = api_get(f"/card/getCardPackList?game={GAME}")
    out: dict[str, str] = {}
    for p in d.get("data", {}).get("list", []):
        pid = str(p.get("packId", ""))
        if pid:
            out[pid.upper()] = pid
    return out


def fetch_pack_prices(pack_id: str, game: str = GAME) -> dict[str, list[dict]]:
    """取一包所有卡 → {packCardId: [{rare, avg, lowest}, ...]}。game 指定語言版本。"""
    d = api_get(f"/card/getCardPackDetailList?game={game}&packId={pack_id}")
    by_num: dict[str, list[dict]] = {}
    for c in d.get("data", {}).get("list", []):
        num = norm_num(c.get("packCardId", ""))
        if not num:
            continue
        rare = c.get("rare")
        rare_label = (rare[0] if isinstance(rare, list) and rare else
                      (rare if isinstance(rare, str) else "")) or ""
        avg = c.get("averagePrice")
        low = c.get("lowestPrice")
        by_num.setdefault(num, []).append({
            "rare": rare_label.strip(),
            "avg": avg,
            "low": low,
        })
    return by_num


def pick_price(
    cands: list[dict], our_rarity: str
) -> tuple[Decimal | None, str | None]:
    """從候選價挑出最符合者；回傳 (價格, 用於回填的稀有度)。

    - 本地稀有度有效 → 取 rare 相同者；找不到取最高均價者。
    - 本地 N/A → 取最高均價者，並回傳其 rare 供回填。
    """
    def price_of(c: dict) -> Decimal:
        v = c["avg"] if c["avg"] not in (None, 0) else c["low"]
        return Decimal(str(v)) if v not in (None,) else Decimal("0")

    if not cands:
        return None, None

    valid_rarity = our_rarity and our_rarity != "N/A"
    if valid_rarity:
        same = [c for c in cands if c["rare"].upper() == our_rarity.upper()]
        if same:
            best = max(same, key=price_of)
            return price_of(best), None
    # N/A 或找不到相同稀有度 → 取最高均價者
    best = max(cands, key=price_of)
    backfill = best["rare"] if not valid_rarity and best["rare"] else None
    return price_of(best), backfill


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", default=None,
                    help="只更新指定展開（逗號分隔）；預設更新 DB 既有全部")
    args = ap.parse_args()

    conn = await asyncpg.connect(DB_DSN)
    try:
        if args.packs:
            sets = [s.strip().upper() for s in args.packs.split(",") if s.strip()]
        else:
            rows = await conn.fetch(
                "SELECT DISTINCT set_code FROM cards WHERE source='tw_official' ORDER BY set_code"
            )
            sets = [r["set_code"] for r in rows]

        print(f"[1] 取得卡拍拍 pack 索引...")
        kp_index = kapaipai_pack_index()

        total_priced = total_backfill = 0
        for sc in sets:
            kp_pid = kp_index.get(sc.upper())
            if not kp_pid:
                print(f"  - {sc}: 卡拍拍查無對應 pack，略過")
                continue
            # 同時抓 日文版 與 繁體中文版 兩種價格
            prices_jp = fetch_pack_prices(kp_pid, GAMES["jp"])
            prices_tw = fetch_pack_prices(kp_pid, GAMES["tw"])
            our = await conn.fetch(
                "SELECT card_id, card_number, rarity FROM cards WHERE set_code=$1",
                sc,
            )
            priced = backfilled = 0
            for c in our:
                num = norm_num(c["card_number"])
                price_jp, bf_jp = pick_price(prices_jp.get(num, []), c["rarity"])
                price_tw, bf_tw = pick_price(prices_tw.get(num, []), c["rarity"])
                if (price_jp is None or price_jp <= 0) and (
                    price_tw is None or price_tw <= 0
                ):
                    continue
                # current_price 預設採繁中版，繁中沒有才用日文
                default_price = price_tw if (price_tw and price_tw > 0) else price_jp
                backfill = bf_tw or bf_jp
                if backfill:
                    await conn.execute(
                        "UPDATE cards SET price_jp=$1, price_tw=$2, current_price=$3, "
                        "rarity=$4, price_source='cardpaipai', updated_at=NOW() "
                        "WHERE card_id=$5",
                        price_jp, price_tw, default_price, backfill, c["card_id"],
                    )
                    backfilled += 1
                else:
                    await conn.execute(
                        "UPDATE cards SET price_jp=$1, price_tw=$2, current_price=$3, "
                        "price_source='cardpaipai', updated_at=NOW() WHERE card_id=$4",
                        price_jp, price_tw, default_price, c["card_id"],
                    )
                # price_history 記繁中版當日價（走勢圖預設繁中）
                await conn.execute(
                    "DELETE FROM price_history WHERE card_id=$1 AND recorded_date=CURRENT_DATE",
                    c["card_id"],
                )
                await conn.execute(
                    "INSERT INTO price_history (card_id, recorded_date, price, volume)"
                    " VALUES ($1, CURRENT_DATE, $2, 0)",
                    c["card_id"], default_price,
                )
                priced += 1
            total_priced += priced
            total_backfill += backfilled
            print(f"  - {sc} (kapaipai {kp_pid}): 定價 {priced} 張"
                  f"{f'、回填稀有度 {backfilled} 張' if backfilled else ''}")
            time.sleep(0.3)

        print(f"\n完成：定價 {total_priced} 張，回填稀有度 {total_backfill} 張。")
    finally:
        await conn.close()

    # 清除估價引擎的 Redis 價格快取，讓新價立即生效（best-effort）。
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://:0907@127.0.0.1:6380/0")
        )
        keys = [k async for k in r.scan_iter("price:*")]
        if keys:
            await r.delete(*keys)
        await r.aclose()
        print(f"已清除 {len(keys)} 筆價格快取。")
    except Exception as e:  # noqa: BLE001
        print(f"（價格快取未清除：{e}）")


if __name__ == "__main__":
    asyncio.run(main())
