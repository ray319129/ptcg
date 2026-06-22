"""補抓卡片牌種（card_type）。

自官方詳情頁 https://asia.pokemon-card.com/tw/card-search/detail/{external_id}/
判定 Pokemon / Supporter / Item / Stadium / Tool / Energy，寫回 cards.card_type。
可重複執行：只抓 card_type 仍為 NULL 的卡（resumable）。

用法：python -m ingest.card_types
"""
from __future__ import annotations

import asyncio
import os
import time
import urllib.request

from sqlalchemy import text

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://ptcg:0907@127.0.0.1:55432/ptcg"
)
os.environ.setdefault("REDIS_URL", "redis://:0907@127.0.0.1:6380/0")

from app.db import AsyncSessionLocal  # noqa: E402

UA = "Mozilla/5.0 (compatible; ptcg-ingest/1.0)"
DETAIL = "https://asia.pokemon-card.com/tw/card-search/detail/{}/"
DELAY = 0.25  # 禮貌限速


def parse_type(html: str) -> str | None:
    # 寶可夢一定有進化階段標記；訓練家/能量沒有。先判 Pokemon 最可靠。
    if 'class="evolveMarker"' in html:
        return "Pokemon"
    # 訓練家子類標籤只出現在該卡本體（已驗證不會誤現於其他牌種頁）
    if "支援者卡" in html:
        return "Supporter"
    if "物品卡" in html:
        return "Item"
    if "競技場卡" in html:
        return "Stadium"
    if "寶可夢道具" in html:
        return "Tool"
    if "基本能量" in html or "特殊能量" in html:
        return "Energy"
    return None


def fetch(external_id: str) -> str | None:
    url = DETAIL.format(external_id)
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            time.sleep(1.0)
    return None


async def main() -> None:
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT card_id, external_id FROM cards "
                    "WHERE external_id IS NOT NULL AND external_id <> '' "
                    "AND card_type IS NULL ORDER BY card_id"
                )
            )
        ).all()
        total = len(rows)
        print(f"待補抓 {total} 張…", flush=True)
        done = 0
        for cid, ext in rows:
            html = fetch(str(ext))
            ctype = parse_type(html) if html else None
            if ctype:
                await s.execute(
                    text("UPDATE cards SET card_type = :t WHERE card_id = :c"),
                    {"t": ctype, "c": cid},
                )
                await s.commit()
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{total}  (last {cid} -> {ctype})", flush=True)
            time.sleep(DELAY)
        # 統計
        stats = (
            await s.execute(
                text("SELECT card_type, COUNT(*) FROM cards GROUP BY card_type ORDER BY 2 DESC")
            )
        ).all()
        print("完成。牌種分布：", flush=True)
        for t, n in stats:
            print(f"  {t}: {n}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
