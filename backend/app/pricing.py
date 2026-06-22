"""卡價語言版本選擇輔助。

卡拍拍日文版 (pkmjp) 與繁體中文版 (pkmtw) 價格差異甚大，分存 price_jp / price_tw。
依使用者選的語言回傳對應價；缺該語言價時退回 current_price。
"""
from __future__ import annotations


def normalize_lang(lang: str | None) -> str:
    return "jp" if (lang or "").lower() == "jp" else "tw"  # 預設繁中


def price_column(lang: str | None) -> str:
    return "price_jp" if normalize_lang(lang) == "jp" else "price_tw"


def price_expr(lang: str | None, alias: str = "c") -> str:
    """回傳 SQL 價格運算式（COALESCE 退回 current_price）。alias 為 cards 表別名。"""
    col = price_column(lang)
    return f"COALESCE({alias}.{col}, {alias}.current_price, 0)"
