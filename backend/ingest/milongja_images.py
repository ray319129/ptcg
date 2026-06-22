"""從 milongja (waca.tw) 卡舖抓 M5 特卡圖片，補我們缺的卡圖。

來源：https://milongja.waca.tw/category/202913 （M5 深淵之瞳，分頁）
商品用 CSS background-image，名稱含「M5 XXX/081」卡號。
只下載 DB 中 image_url 為空的 M5 卡；不使用此站價格。

用法：python -m ingest.milongja_images
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import urllib.request
from pathlib import Path

import asyncpg

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"
CAT_URL = "https://milongja.waca.tw/category/202913"
DB_DSN = os.getenv("PG_DSN", "postgresql://ptcg:0907@127.0.0.1:55432/ptcg")
IMG_DIR = Path(__file__).resolve().parents[2] / "webapp" / "public" / "img" / "cards" / "M5"

_NUM_RE = re.compile(r"M5\s*(\d{2,3})/0\d{2}")
_IMG_RE = re.compile(
    r"background-image:\s*url\((https://img\.cloudimg\.in/[^)]+\.(?:jpg|jpeg|png|webp))\)"
)


def http_get(url: str, binary: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                data = r.read()
                return data if binary else data.decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            time.sleep(1.0)
    raise RuntimeError(f"GET 失敗 {url}")


def parse_page(html: str) -> dict[str, str]:
    """回傳 {三位卡號: 圖URL}，每張圖配最近的卡號。"""
    nums = [(m.start(), m.group(1).zfill(3)) for m in _NUM_RE.finditer(html)]
    imgs = [(m.start(), m.group(1)) for m in _IMG_RE.finditer(html)]
    out: dict[str, str] = {}
    for ipos, url in imgs:
        if not nums:
            break
        num = min(nums, key=lambda n: abs(n[0] - ipos))
        if abs(num[0] - ipos) < 3000:
            out.setdefault(num[1], url)
    return out


async def main() -> None:
    conn = await asyncpg.connect(DB_DSN)
    try:
        rows = await conn.fetch(
            "SELECT card_id, card_number FROM cards "
            "WHERE set_code='M5' AND image_url IS NULL"
        )
        missing = {r["card_number"].split("/")[0].zfill(3): r["card_id"] for r in rows}
        print(f"缺卡圖 {len(missing)} 張：{sorted(missing)}")
        if not missing:
            return

        # 蒐集各頁的 卡號→圖
        num2url: dict[str, str] = {}
        for page in range(1, 8):
            html = http_get(f"{CAT_URL}?page={page}")
            page_map = parse_page(html)
            if not page_map:
                break
            for k, v in page_map.items():
                num2url.setdefault(k, v)
            print(f"  page{page}: {len(page_map)} 張圖（累計 {len(num2url)}）")
            time.sleep(0.4)

        IMG_DIR.mkdir(parents=True, exist_ok=True)
        done = 0
        for num, card_id in sorted(missing.items()):
            url = num2url.get(num)
            if not url:
                print(f"  ! {card_id} 在 milongja 找不到對應圖")
                continue
            total = card_id.split("_")[1].split("/")[1]
            dest = IMG_DIR / f"{num}-{total}.png"
            try:
                from PIL import Image
                import io
                data = http_get(url, binary=True)
                Image.open(io.BytesIO(data)).convert("RGB").save(dest, "PNG")
                rel = f"/img/cards/M5/{num}-{total}.png"
                await conn.execute(
                    "UPDATE cards SET image_url=$1, updated_at=NOW() WHERE card_id=$2",
                    rel, card_id,
                )
                done += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ! {card_id} 下載失敗: {e}")
            time.sleep(0.3)
        print(f"\n完成：補入 {done} 張 M5 卡圖。")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
