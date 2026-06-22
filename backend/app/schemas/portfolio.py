"""儀表板與庫存 API 的回應模型。"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class SpikeItem(BaseModel):
    card_id: str
    name_zh: str
    rarity: str
    price: Decimal
    change_pct: float = Field(..., description="今日相對昨日的價格變動百分比")


class RarityRatio(BaseModel):
    rarity: str
    count: int
    pct: float


class PortfolioSummary(BaseModel):
    net_worth: Decimal = Field(..., description="總資產淨值")
    change_24h_pct: float = Field(..., description="24h 淨值變動 %")
    sparkline: List[Decimal] = Field(
        default_factory=list, description="近 7 日每日淨值（趨勢線）"
    )
    total_cards: int
    rarity_distribution: List[RarityRatio]
    avg_liquidity: float
    dead_stock_count: int = Field(..., description="低流動性滯銷卡張數")
    recent_spikes: List[SpikeItem]


class InventoryItem(BaseModel):
    card_id: str
    set_code: str
    card_number: str
    name_zh: str
    rarity: str
    quantity: int
    market_value: Decimal
    liquidity_score: float
    is_favorite: bool
    pack_eligible: bool


class InventoryPage(BaseModel):
    items: List[InventoryItem]
    total: int
    limit: int
    offset: int


class InventoryAdd(BaseModel):
    """掃描自動入庫的請求。"""

    user_id: str
    card_id: str
    quantity: int = Field(default=1, ge=1, le=999)


class InventoryAddResult(BaseModel):
    card_id: str
    new_quantity: int
    name_zh: str
    rarity: str
    market_value: Decimal


class InventoryPatch(BaseModel):
    """更新單一庫存項（卡片詳情頁的數量器 / 開關）。"""

    quantity: Optional[int] = Field(default=None, ge=0)
    is_favorite: Optional[bool] = None
    pack_eligible: Optional[bool] = None


class PricePoint(BaseModel):
    recorded_date: str
    price: Decimal
    volume: int


class CardDetail(BaseModel):
    card_id: str
    set_code: str
    card_number: str
    rarity: str
    name_zh: str
    current_price: Decimal
    liquidity_score: float
    avg_7d: Optional[Decimal] = None
    highest_deal: Optional[Decimal] = None
    lowest_ask: Optional[Decimal] = None
    owned_qty: int
    is_favorite: bool
    pack_eligible: bool
    price_history: List[PricePoint]
