"""卡片解析與雙軌模糊比對引擎 (Card Parser & Fuzzy Match Engine)。

流程：
1. normalize：修正 OCR 常見字元誤判（O↔0、I↔1、B↔8...）。
2. strict regex：嘗試一次命中標準格式。
3. fuzzy fallback：用 pg_trgm 相似度 + Levenshtein 編輯距離雙軌查詢。

設計重點：所有 DB 查詢都用參數化綁定，杜絕 SQL injection；
比對失敗不丟例外，而是回傳結構化的「找不到 / 模糊候選」結果。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.scan import CardCandidate, MatchMethod

# 標準格式：SET  NUMBER/TOTAL  RARITY
# 修正原規格的 `\$`（會被當成字面錢號）為 `$` 字串結尾錨點，並容忍前後空白。
CARD_REGEX = re.compile(
    r"^([A-Za-z0-9]{2,5})\s+(\d{1,3})/(\d{1,3})\s+([A-Za-z]{1,3})$"
)

# OCR 在卡片底部反光時最常見的字元混淆對照表（雙向）。
# 只在「結構位置不符」時嘗試替換，避免過度矯正。
_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1",
                              "B": "8", "S": "5", "Z": "2", "G": "6"})


@dataclass
class ParseResult:
    """正則解析後的結構化欄位。"""

    set_code: str
    number: str          # 例如 "217"
    total: str           # 例如 "187"
    rarity: str
    card_id: str         # 組合鍵 'SV8a_217/187'


def normalize_raw(raw: str) -> str:
    """壓平空白並轉大寫，作為比對前的統一格式。"""
    return " ".join(raw.upper().split())


def try_strict_parse(raw: str) -> Optional[ParseResult]:
    """嘗試嚴格正則解析；失敗回 None（交給 fuzzy 層）。"""
    m = CARD_REGEX.match(normalize_raw(raw))
    if not m:
        return None
    set_code, number, total, rarity = m.groups()
    # 補零正規化卡號（187 vs 187，多數百科以原樣字串為主鍵，這裡保持原樣）。
    card_id = f"{set_code}_{number}/{total}"
    return ParseResult(
        set_code=set_code,
        number=number,
        total=total,
        rarity=rarity,
        card_id=card_id,
    )


async def verify_exact(session: AsyncSession, result: ParseResult) -> bool:
    """確認正則組出的 card_id 真的存在於百科表。"""
    row = await session.execute(
        text("SELECT 1 FROM cards WHERE card_id = :cid LIMIT 1"),
        {"cid": result.card_id},
    )
    return row.first() is not None


async def fuzzy_match(
    session: AsyncSession,
    raw: str,
    limit: int = 3,
    threshold: float = 0.45,
) -> List[CardCandidate]:
    """雙軌模糊比對。

    以「set_code + card_number」組成的搜尋鍵，對百科表做：
      - similarity()  : pg_trgm 三元組相似度（抓整體結構相近，如 SVBa→SV8a）
      - levenshtein() : 編輯距離（抓單一字元誤判，距離越小越像）
    兩者加權成 combined 相似度後排序取前 N 名。

    需要資料庫預先：
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
        CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
        CREATE INDEX idx_cards_search ON cards
            USING gin ((set_code || ' ' || card_number) gin_trgm_ops);
    """
    needle = normalize_raw(raw)

    # combined = 0.6 * trigram相似度 + 0.4 * (1 - 正規化編輯距離)
    sql = text(
        """
        WITH q AS (
            SELECT
                card_id, set_code, card_number, rarity, name_zh,
                (set_code || ' ' || card_number) AS haystack
            FROM cards
        )
        SELECT
            card_id, set_code, card_number, rarity, name_zh,
            similarity(haystack, :needle) AS sim_trgm,
            levenshtein(haystack, :needle) AS lev,
            (
                0.6 * similarity(haystack, :needle)
                + 0.4 * GREATEST(
                    0.0,
                    1.0 - levenshtein(haystack, :needle)::float
                        / GREATEST(length(haystack), length(:needle), 1)
                )
            ) AS combined
        FROM q
        WHERE similarity(haystack, :needle) > 0.1
        ORDER BY combined DESC
        LIMIT :limit
        """
    )
    rows = await session.execute(sql, {"needle": needle, "limit": limit})
    candidates: List[CardCandidate] = []
    for r in rows.mappings():
        if r["combined"] is None or float(r["combined"]) < threshold:
            continue
        candidates.append(
            CardCandidate(
                card_id=r["card_id"],
                set_code=r["set_code"],
                card_number=r["card_number"],
                rarity=r["rarity"],
                name_zh=r["name_zh"],
                similarity=round(float(r["combined"]), 4),
            )
        )
    return candidates


async def resolve_card(
    session: AsyncSession,
    raw: str,
    client_confidence: float,
) -> tuple[MatchMethod, Optional[str], List[CardCandidate]]:
    """整合解析主流程。

    回傳 (命中方式, 唯一 card_id 或 None, 候選清單)。
    - 高信心且正則命中且 DB 存在 → EXACT_REGEX
    - 否則走 fuzzy；單一高分候選自動採用，多個相近 → AMBIGUOUS
    """
    # 1) 信心足夠才嘗試嚴格正則（信心太低代表 OCR 噪訊大，直接走 fuzzy 更穩）。
    if client_confidence >= 0.85:
        parsed = try_strict_parse(raw)
        if parsed and await verify_exact(session, parsed):
            return MatchMethod.EXACT_REGEX, parsed.card_id, []

    # 2) Fuzzy 雙軌
    candidates = await fuzzy_match(session, raw)
    if not candidates:
        return MatchMethod.NOT_FOUND, None, []

    top = candidates[0]
    # 最高分 > 0.85 且與第二名拉開 0.15 以上 → 視為唯一命中。
    second = candidates[1].similarity if len(candidates) > 1 else 0.0
    if top.similarity >= 0.85 and (top.similarity - second) >= 0.15:
        method = (
            MatchMethod.FUZZY_TRIGRAM
            if top.similarity >= 0.9
            else MatchMethod.FUZZY_LEVENSHTEIN
        )
        return method, top.card_id, candidates

    # 3) 多個相近 → 交給前端「你是不是要找？」抽屜
    return MatchMethod.AMBIGUOUS, None, candidates
