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
    # 最佳匹配（信心足夠時）。否則為 None，由前端用 candidates 讓使用者選。
    best: Optional[MatchCandidate] = None
    candidates: List[MatchCandidate] = Field(default_factory=list)
    detected: bool = Field(default=False, description="是否自動偵測到卡片邊框")
    # 同圖不同版：偵測到多個版本(同圖、卡號/稀有度不同)需使用者挑選時為 True，
    # candidates 即為這些版本（依信心排序）。自動讀卡號定版成功時則回 success=True。
    needs_pick: bool = Field(default=False, description="是否需要使用者選擇版本")
    message: str = ""
