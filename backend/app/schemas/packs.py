"""神秘包最佳化 API 的請求 / 回應模型，以及 OptimizeResult → 回應的序列化。"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.services.optimizer import (
    OptimizeResult,
    PrizeTier,
    _RARITY_TIER,
)


class OptimizeRequest(BaseModel):
    """產生神秘包策略的輸入參數（對應 UI Screen 4 的三個欄位）。"""

    user_id: str = Field(..., description="商家使用者 UUID")
    total_packs: int = Field(..., gt=0, le=100_000, description="要做幾包 (N)")
    pack_price: Decimal = Field(..., gt=0, description="每包售價 (P)")
    target_margin: float = Field(
        ..., ge=0.0, lt=1.0, description="目標毛利率 (M)，例如 0.30"
    )
    floor_ratio: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="每包最低體感價值/售價比，防雷包",
    )
    guaranteed_rarity: Optional[str] = Field(
        default=None,
        description="每包保底至少一張 >= 此稀有度（如 RR/AR/SR/SAR）；對應市場保底賣法",
    )
    guaranteed_categories: Optional[List[str]] = Field(
        default=None,
        description="每包各保底一張該類別：ex / mega(超級進化) / full_art_supporter(全圖人物)",
    )
    chase_card_ids: Optional[List[str]] = Field(
        default=None,
        description="招牌頭獎卡 card_id 清單，優先灑進不同包",
    )
    auto_chase_count: int = Field(
        default=0, ge=0, le=1000,
        description="未指定 chase 時，自動取市值最高的 N 張當招牌頭獎卡",
    )
    exclude_favorites: bool = Field(
        default=True, description="是否排除使用者標記為最愛的卡"
    )
    lang: Optional[str] = Field(
        default="tw", description="卡價語言版本：tw(繁中) / jp(日文)"
    )


class CardLine(BaseModel):
    """PDF / UI 用的單張卡明細。"""

    card_id: str
    name_zh: str
    rarity: str
    market_value: Decimal


class TierBreakdown(BaseModel):
    grand: List[CardLine] = Field(default_factory=list)
    second: List[CardLine] = Field(default_factory=list)
    base: List[CardLine] = Field(default_factory=list)


class PackDetail(BaseModel):
    pack_index: int
    display_value: Decimal
    effective_value: Decimal
    tiers: TierBreakdown


class OptimizeResponse(BaseModel):
    plan_id: Optional[str] = Field(
        default=None, description="已持久化的計畫 ID，可用於下載 PDF"
    )
    feasible: bool
    message: str
    # 商業指標
    budget: Decimal
    allocated_effective_value: Decimal
    expected_value_per_pack: Decimal
    realized_margin: float
    payback_ratio: float = 0.0
    floor_per_pack: Decimal
    total_packs: int
    pack_price: Decimal
    target_margin: float
    # 明細
    packs: List[PackDetail]
    leftover_count: int
    leftover_value: Decimal


def _card_line(card) -> CardLine:
    return CardLine(
        card_id=card.card_id,
        name_zh=card.name_zh,
        rarity=card.rarity,
        market_value=card.market_value,
    )


def serialize_result(
    result: OptimizeResult,
    *,
    total_packs: int,
    pack_price: Decimal,
    target_margin: float,
    plan_id: Optional[str] = None,
) -> OptimizeResponse:
    """把純演算法的 OptimizeResult 轉成附完整卡片明細的 API 回應。"""
    pack_details: List[PackDetail] = []
    for p in result.packs:
        tiers = TierBreakdown()
        for card in p.cards:
            tier = _RARITY_TIER.get(card.rarity.upper(), PrizeTier.BASE)
            line = _card_line(card)
            if tier == PrizeTier.GRAND:
                tiers.grand.append(line)
            elif tier == PrizeTier.SECOND:
                tiers.second.append(line)
            else:
                tiers.base.append(line)
        pack_details.append(
            PackDetail(
                pack_index=p.pack_index,
                display_value=p.display_value,
                effective_value=p.effective_value,
                tiers=tiers,
            )
        )

    leftover_value = sum(
        (c.market_value for c in result.leftover), Decimal("0.00")
    )
    return OptimizeResponse(
        plan_id=plan_id,
        feasible=result.feasible,
        message=result.message,
        budget=result.budget,
        allocated_effective_value=result.allocated_effective_value,
        expected_value_per_pack=result.expected_value_per_pack,
        realized_margin=result.realized_margin,
        payback_ratio=result.payback_ratio,
        floor_per_pack=result.floor_per_pack,
        total_packs=total_packs,
        pack_price=pack_price,
        target_margin=target_margin,
        packs=pack_details,
        leftover_count=len(result.leftover),
        leftover_value=leftover_value,
    )
