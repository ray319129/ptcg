"""影像比對 API 的回應模型。"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class MatchCandidate(BaseModel):
    card_id: str
    set_code: str
    card_number: str
    rarity: str
    name_zh: str
    image_url: Optional[str] = None
    market_value: Decimal
    in_collection_count: int = 0
    similarity: float = Field(..., description="與卡圖庫的 cosine 相似度 0~1")


class MatchResponse(BaseModel):
    success: bool
    # 最佳匹配（相似度夠高時）。否則為 None，由前端用 candidates 讓使用者選。
    best: Optional[MatchCandidate] = None
    candidates: List[MatchCandidate] = Field(default_factory=list)
    detected: bool = Field(default=False, description="是否自動偵測到卡片邊框")
    message: str = ""
