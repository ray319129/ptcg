"""台灣官方寶可夢卡牌網站爬蟲（Scrydex 未收錄的展開，例如 M5）。

來源：https://asia.pokemon-card.com/tw/card-search/
擷取：中文卡名、卡號(如 001/081)、稀有度(用官網 rarity 篩選反查)、卡圖。

用法：
    python -m ingest.tw_official --expansion M5

設計：
- 只用標準函式庫做 HTTP（帶瀏覽器 UA，否則官網回 403）。
- 卡圖下載到 webapp/public/img/cards/<EXP>/ 走同源，避開前端 COEP 限制。
- 稀有度：官網詳情頁不公開，改用列表的 rarity[] 篩選反查每張卡。
"""
from __future__ import annotations

import argparse
import asyncio
import html as _html
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import asyncpg

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"
BASE = "https://asia.pokemon-card.com/tw/card-search/list/"
IMG_URL = "https://asia.pokemon-card.com/tw/card-img/tw{id:08d}.png"

# 官網 rarity[] 代碼 → 稀有度標籤（取自搜尋表單）
RARITY_MAP = {
    1: "C", 2: "U", 3: "R", 4: "RR", 5: "RRR", 6: "PR", 7: "TR", 8: "SR",
    9: "HR", 10: "UR", 12: "K", 13: "A", 14: "AR", 15: "SAR", 16: "S",
    17: "SSR", 18: "ACE", 19: "BWR", 20: "MUR", 21: "MA",
}

DB_DSN = os.getenv(
    "PG_DSN", "postgresql://ptcg:0907@127.0.0.1:55432/ptcg"
)

# webapp/public/img/cards/<EXP> 的實體路徑
IMG_DIR = Path(__file__).resolve().parents[2] / "webapp" / "public" / "img" / "cards"


def http_get(url: str, *, binary: bool = False, retries: int = 3) -> bytes | str:
    """帶 UA 的 GET，UTF-8 解碼；失敗重試。"""
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
                return data if binary else data.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0)
    raise RuntimeError(f"GET 失敗 {url}: {last}")


def detail_ids(html: str) -> list[int]:
    return [int(x) for x in re.findall(r"/tw/card-search/detail/(\d+)", html)]


def collect_all_ids(expansion: str, max_pages: int = 40) -> list[int]:
    """分頁取得該展開所有卡片 detail id（去重、保序）。"""
    seen: list[int] = []
    seen_set: set[int] = set()
    for page in range(1, max_pages + 1):
        url = f"{BASE}?expansionCodes={expansion}&pageNo={page}"
        ids = detail_ids(http_get(url))  # type: ignore[arg-type]
        fresh = [i for i in ids if i not in seen_set]
        if not ids or not fresh:
            break  # 空頁或整頁都看過 → 到底了
        for i in fresh:
            seen.append(i)
            seen_set.add(i)
        time.sleep(0.25)
    return seen


def build_rarity_map(expansion: str, max_pages: int = 20) -> dict[int, str]:
    """用 rarity[] 篩選反查 id→稀有度。"""
    out: dict[int, str] = {}
    for code, label in RARITY_MAP.items():
        for page in range(1, max_pages + 1):
            url = f"{BASE}?expansionCodes={expansion}&rarity%5B%5D={code}&pageNo={page}"
            ids = detail_ids(http_get(url))  # type: ignore[arg-type]
            if not ids:
                break
            new = False
            for i in ids:
                if i not in out:
                    out[i] = label
                    new = True
            if not new:
                break  # 這頁全是看過的 → 此稀有度到底
            time.sleep(0.2)
    return out


_NUM_RE = re.compile(r"\b(\d{1,3})/(\d{1,3})\b")


def parse_detail(html: str) -> tuple[str, str, str] | None:
    """回傳 (中文名, 卡號 '001/081', 總數 '081')；解析失敗回 None。"""
    mt = re.search(r"<title>(.*?)</title>", html, re.S)
    name = ""
    if mt:
        # 解碼 HTML 實體（如 &lt;阿響的&gt; → <阿響的>）
        name = _html.unescape(re.sub(r"\s+", " ", mt.group(1)).split("|")[0].strip())
    mn = _NUM_RE.search(html)
    if not name or not mn:
        return None
    number = f"{mn.group(1)}/{mn.group(2)}"
    return name, number, mn.group(2)


def download_image(card_db_id: int, expansion: str, number: str) -> str | None:
    """下載卡圖到 public/img/cards/<EXP>/<safe>.png，回傳同源 URL。"""
    safe = number.replace("/", "-")
    out_dir = IMG_DIR / expansion
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{safe}.png"
    rel = f"/img/cards/{expansion}/{safe}.png"
    if dest.exists() and dest.stat().st_size > 0:
        return rel
    try:
        data = http_get(IMG_URL.format(id=card_db_id), binary=True)
        dest.write_bytes(data)  # type: ignore[arg-type]
        return rel
    except Exception as e:  # noqa: BLE001
        print(f"  ! 卡圖下載失敗 {card_db_id}: {e}", file=sys.stderr)
        return None


async def upsert(pool: asyncpg.Pool, rows: list[dict]) -> int:
    sql = """
    INSERT INTO cards
        (card_id, set_code, card_number, rarity, name_zh, current_price,
         liquidity_score, is_meta, source, image_url, external_id, release_date)
    VALUES ($1,$2,$3,$4,$5,0,1.0,FALSE,'tw_official',$6,$7,$8)
    ON CONFLICT (card_id) DO UPDATE SET
        name_zh   = EXCLUDED.name_zh,
        rarity    = EXCLUDED.rarity,
        image_url = EXCLUDED.image_url,
        source    = EXCLUDED.source,
        external_id = EXCLUDED.external_id,
        release_date = EXCLUDED.release_date,
        updated_at = NOW()
    """
    n = 0
    async with pool.acquire() as conn:
        for r in rows:
            await conn.execute(
                sql, r["card_id"], r["set_code"], r["card_number"], r["rarity"],
                r["name_zh"], r["image_url"], r["external_id"], r["release_date"],
            )
            n += 1
    return n


async def ingest_expansion(
    pool: asyncpg.Pool, exp: str, rel_date=None
) -> dict:
    """抓取單一展開並寫入 DB，回傳摘要 dict。可被批次重用。"""
    exp = exp.upper()
    print(f"\n=== {exp} ===")
    print("[1] 取得全部卡片 id...")
    ids = collect_all_ids(exp)
    print(f"    共 {len(ids)} 張")
    if not ids:
        return {"expansion": exp, "cards": 0, "rarities": {}}

    print("[2] 反查稀有度...")
    rmap = build_rarity_map(exp)
    print(f"    已標稀有度 {len(rmap)} 張")

    print("[3] 逐張取詳情 + 下載卡圖...")
    rows: list[dict] = []
    for idx, cid in enumerate(ids, 1):
        det = parse_detail(http_get(f"https://asia.pokemon-card.com/tw/card-search/detail/{cid}/"))  # type: ignore[arg-type]
        if not det:
            print(f"  ! 略過 {cid}（詳情解析失敗）", file=sys.stderr)
            continue
        name, number, _total = det
        img = download_image(cid, exp, number)
        rows.append({
            "card_id": f"{exp}_{number}",
            "set_code": exp,
            "card_number": number,
            "rarity": rmap.get(cid, "N/A"),
            "name_zh": name,
            "image_url": img,
            "external_id": str(cid),
            "release_date": rel_date,
        })
        if idx % 20 == 0:
            print(f"    {idx}/{len(ids)}")
        time.sleep(0.2)

    n = await upsert(pool, rows)
    from collections import Counter
    dist = dict(Counter(r["rarity"] for r in rows))
    print(f"[4] {exp} 完成：upsert {n} 張，稀有度 {dist}")
    return {"expansion": exp, "cards": n, "rarities": dist}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expansion", required=True,
                    help="官網展開代碼（可逗號分隔多個，如 M5,M4,SV9）")
    ap.add_argument("--release-date", default=None, help="上市日 YYYY-MM-DD（可選）")
    args = ap.parse_args()
    import datetime
    rel = (datetime.date.fromisoformat(args.release_date)
           if args.release_date else None)
    codes = [c.strip().upper() for c in args.expansion.split(",") if c.strip()]

    pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=4)
    try:
        summary = [await ingest_expansion(pool, c, rel) for c in codes]
    finally:
        await pool.close()
    total = sum(s["cards"] for s in summary)
    print(f"\n總計：{len(codes)} 個展開、{total} 張卡片入庫。")


if __name__ == "__main__":
    asyncio.run(main())
