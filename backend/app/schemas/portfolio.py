"""儀表板與庫存 API 的回應模型。"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class RarityRatio(BaseModel):
    rarity: str
    count: int
    pct: float


class PortfolioSummary(BaseModel):
    net_worth: Decimal = Field(..., description="總資產淨值")
    total_cards: int
    rarity_distribution: List[RarityRatio]
    avg_liquidity: float
    dead_stock_count: int = Field(..., description="低流動性滯銷卡張數")


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
    image_url: Optional[str] = None


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


class InventoryBulk(BaseModel):
    """批次編輯多張庫存卡（庫存頁多選操作）。

    delete=True 時刪除選取項；否則套用有帶值的開關欄位。
    """

    user_id: str
    card_ids: List[str] = Field(..., min_length=1)
    is_favorite: Optional[bool] = None
    pack_eligible: Optional[bool] = None
    delete: bool = False


class InventoryBulkResult(BaseModel):
    affected: int


class InventoryClear(BaseModel):
    """一鍵清空整個收藏。"""

    user_id: str


class CardSearchItem(BaseModel):
    """卡片百科搜尋結果（手動加入庫存用）。"""

    card_id: str
    set_code: str
    card_number: str
    rarity: str
    name_zh: str
    image_url: Optional[str] = None
    market_value: Decimal
    owned_qty: int = Field(default=0, description="使用者目前持有數")


class CardDetail(BaseModel):
    card_id: str
    set_code: str
    card_number: str
    rarity: str
    name_zh: str
    current_price: Decimal
    liquidity_score: float
    owned_qty: int
    is_favorite: bool
    pack_eligible: bool
