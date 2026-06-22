"""神秘包最佳化引擎 (Mystery Pack Optimizer)。

商業目標：把滯銷庫存打包成「對消費者有吸引力、對商家鎖死目標毛利」的神秘包。

數學建模：多選有界背包 (Multi-Choice Bounded Knapsack) 的近似解。
精確 MCKP 為 NP-hard，在數千張卡 × 數百包的規模下，採用
「分層 + 流動性折價 + 輪流分配 (round-robin) + 底價補padding」的貪婪策略，
可在 O(n log n) 內得到穩定且可解釋的分配，並嚴格驗證毛利下限。

關鍵約束：
    成本預算 budget = total_packs * pack_price * (1 - target_margin)
    Σ(已分配卡片的折價後價值) <= budget        → 鎖住商家毛利
    每包價值 >= floor_per_pack                  → 保障消費者體感（避免雷包）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, List, Optional


class PrizeTier(str, Enum):
    GRAND = "grand"   # 頭獎：價值前 5% (SAR/UR)
    SECOND = "second"  # 二獎：SR/AR
    BASE = "base"     # 基底池：RR/U/C，負責補滿底價


# 稀有度價值排序（數字越大越稀有/值錢），用於「保底稀有度」比較與分級。
RARITY_RANK = {
    "C": 1, "U": 2, "R": 3, "RR": 4,
    "RRR": 5, "AR": 5, "ACE": 6, "SR": 6,
    "BWR": 7, "SAR": 7, "UR": 8, "HR": 8,
    "SSR": 9, "MUR": 9, "MA": 9,
}


def rarity_rank(rarity: str) -> int:
    return RARITY_RANK.get(rarity.upper(), 0)


# 神秘包「類別保底」支援的類別（對應市場主打賣法）。
CATEGORIES = ("ex", "mega", "full_art_supporter")
CATEGORY_LABELS = {
    "ex": "寶可夢 ex",
    "mega": "超級進化",
    "full_art_supporter": "全圖人物",
}
# 全圖人物 = SR 以上稀有度的 Supporter（訓練家）卡
_FULL_ART_MIN_RANK = 6


def card_categories(card: "InventoryCard") -> set[str]:
    """依名稱/牌種/稀有度推導卡片所屬的市場類別（可多屬）。"""
    cats: set[str] = set()
    name = (card.name_zh or "").strip()
    is_ex = name.lower().endswith("ex")
    if is_ex:
        cats.add("ex")
        if name.startswith("超級"):       # 超級XXXex = 超級進化 (Mega)
            cats.add("mega")
    if (card.card_type or "") == "Supporter" and rarity_rank(card.rarity) >= _FULL_ART_MIN_RANK:
        cats.add("full_art_supporter")
    return cats


# 稀有度 → 獎級（用於 tier 分類與 PDF/UI 呈現）
_RARITY_TIER = {
    "SAR": PrizeTier.GRAND, "UR": PrizeTier.GRAND, "HR": PrizeTier.GRAND,
    "SSR": PrizeTier.GRAND, "MUR": PrizeTier.GRAND, "MA": PrizeTier.GRAND,
    "BWR": PrizeTier.GRAND,
    "SR": PrizeTier.SECOND, "AR": PrizeTier.SECOND, "RRR": PrizeTier.SECOND,
    "ACE": PrizeTier.SECOND,
    "RR": PrizeTier.BASE, "R": PrizeTier.BASE,
    "U": PrizeTier.BASE, "C": PrizeTier.BASE,
}


@dataclass
class InventoryCard:
    """演算法輸入的單張庫存卡（已攤平 quantity，即每個物件代表 1 張實體卡）。"""

    card_id: str
    name_zh: str
    rarity: str
    market_value: Decimal          # 市場估值
    liquidity_score: float = 1.0   # 0~1，越低代表越難變現
    card_type: Optional[str] = None  # Pokemon / Supporter / Item / ...（類別保底用）

    @property
    def effective_value(self) -> Decimal:
        """流動性折價後的「演算法貢獻價值」。

        滯銷（低流動性）的卡在演算法裡價值打折，鼓勵它們被消耗掉，
        但對消費者展示時仍用 market_value（體感價值）。
        """
        factor = Decimal(str(max(0.05, min(1.0, self.liquidity_score))))
        return (self.market_value * factor).quantize(Decimal("0.01"))


@dataclass
class PackPlan:
    """單一神秘包的分配結果。"""

    pack_index: int
    cards: List[InventoryCard] = field(default_factory=list)

    @property
    def display_value(self) -> Decimal:
        return sum((c.market_value for c in self.cards), Decimal("0.00"))

    @property
    def effective_value(self) -> Decimal:
        return sum((c.effective_value for c in self.cards), Decimal("0.00"))

    def tier_breakdown(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {t.value: [] for t in PrizeTier}
        for c in self.cards:
            tier = _RARITY_TIER.get(c.rarity.upper(), PrizeTier.BASE)
            out[tier.value].append(c.card_id)
        return out


@dataclass
class OptimizeResult:
    """演算法總輸出。"""

    feasible: bool
    message: str
    packs: List[PackPlan] = field(default_factory=list)
    leftover: List[InventoryCard] = field(default_factory=list)
    # 商業指標
    budget: Decimal = Decimal("0.00")
    allocated_effective_value: Decimal = Decimal("0.00")
    expected_value_per_pack: Decimal = Decimal("0.00")
    realized_margin: float = 0.0
    floor_per_pack: Decimal = Decimal("0.00")
    payback_ratio: float = 0.0     # 期望體感價值 / 售價（回本率，賣點透明化）


def _q(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _classify(cards: List[InventoryCard]) -> Dict[PrizeTier, List[InventoryCard]]:
    """依稀有度 + 價值把卡分成三池，並各自由高到低排序。"""
    pools: Dict[PrizeTier, List[InventoryCard]] = {t: [] for t in PrizeTier}
    for c in cards:
        pools[_RARITY_TIER.get(c.rarity.upper(), PrizeTier.BASE)].append(c)
    for t in pools:
        pools[t].sort(key=lambda c: c.market_value, reverse=True)
    return pools


def optimize_mystery_packs(
    inventory: List[InventoryCard],
    total_packs: int,
    pack_price: Decimal,
    target_margin: float,
    *,
    floor_ratio: float = 0.5,
    guaranteed_rarity: Optional[str] = None,
    guaranteed_categories: Optional[List[str]] = None,
    chase_card_ids: Optional[List[str]] = None,
    auto_chase_count: int = 0,
) -> OptimizeResult:
    """主函式：把 inventory 分配進 total_packs 個神秘包。

    參數
    ----
    inventory        : 已攤平的庫存卡清單（每物件 = 1 張實體卡）。
    total_packs      : 要做幾包 (N)。
    pack_price       : 每包售價 (P)。
    target_margin    : 目標毛利率 (M)，例如 0.30。
    floor_ratio      : 每包最低「體感價值 / 售價」比，預設 0.5（半價保底，防雷包）。
    guaranteed_rarity: 每包保底至少一張 >= 此稀有度的卡（對應市場「保底SAR/SR」賣法）。
                       例如 'RR'、'AR'、'SR'、'SAR'。None 表示不設保底稀有度。
    guaranteed_categories: 每包各保底至少一張該類別（'ex'/'mega'/'full_art_supporter'）。
                       對應市場「必出 ex / 超級進化 / 全圖人物」賣法。
    chase_card_ids   : 招牌頭獎卡的 card_id 清單。優先把這些灑進不同包（一包一張），
                       確保招牌卡實際進包、不被當 leftover。

    回傳 OptimizeResult，內含每包卡片、商業指標與可行性判斷。
    """
    # ---- 0. 參數防呆 -------------------------------------------------------
    if total_packs <= 0:
        return OptimizeResult(False, "total_packs 必須 > 0")
    if pack_price <= 0:
        return OptimizeResult(False, "pack_price 必須 > 0")
    if not (0.0 <= target_margin < 1.0):
        return OptimizeResult(False, "target_margin 必須落在 [0, 1)")
    if not inventory:
        return OptimizeResult(False, "庫存為空，無法產生神秘包")

    pack_price = Decimal(str(pack_price))
    revenue = pack_price * total_packs
    budget = _q(revenue * Decimal(str(1.0 - target_margin)))
    floor_per_pack = _q(pack_price * Decimal(str(floor_ratio)))

    packs = [PackPlan(pack_index=i) for i in range(total_packs)]
    allocated_eff = Decimal("0.00")

    def can_afford(card: InventoryCard) -> bool:
        return allocated_eff + card.effective_value <= budget

    remaining = list(inventory)
    used: set[int] = set()

    def _take(card: InventoryCard, pack: PackPlan) -> None:
        nonlocal allocated_eff
        pack.cards.append(card)
        allocated_eff += card.effective_value
        used.add(id(card))

    # ---- 0.3 招牌頭獎卡：優先把指定卡灑進不同包（一包一張）-----------------
    # 未指定 chase 但要求自動招牌時，取市值最高的 N 個 card_id 當招牌。
    if not chase_card_ids and auto_chase_count > 0:
        by_value = sorted(
            {c.card_id: c.market_value for c in remaining}.items(),
            key=lambda kv: kv[1], reverse=True,
        )
        chase_card_ids = [cid for cid, _ in by_value[:auto_chase_count]]
    if chase_card_ids:
        chase_set = set(chase_card_ids)
        chase_cards = sorted(
            (c for c in remaining if c.card_id in chase_set and id(c) not in used),
            key=lambda c: c.market_value, reverse=True,
        )
        ci = 0
        for p in packs:
            if ci >= len(chase_cards):
                break
            c = chase_cards[ci]
            ci += 1
            if can_afford(c):
                _take(c, p)
        remaining = [c for c in remaining if id(c) not in used]

    # ---- 0.5 各種「每包保底」：稀有度 + 類別（已滿足的包自動跳過，避免重複耗用）----
    def guarantee_each_pack(predicate, label: str) -> Optional[str]:
        """確保每個包至少有一張符合 predicate 的卡；回傳錯誤訊息或 None(成功)。"""
        nonlocal remaining
        need = [p for p in packs if not any(predicate(c) for c in p.cards)]
        qualifying = sorted(
            (c for c in remaining if id(c) not in used and predicate(c)),
            key=lambda c: c.market_value,
        )
        if len(qualifying) < len(need):
            return (
                f"{label}保底卡不足：尚需 {len(need)} 張、僅有 {len(qualifying)} 張。"
                f"請放寬保底、減少包數或補貨。"
            )
        qi = 0
        for p in need:
            placed = False
            while qi < len(qualifying):
                c = qualifying[qi]
                qi += 1
                if id(c) in used:
                    continue
                if can_afford(c):
                    _take(c, p)
                    placed = True
                    break
            if not placed:
                return f"預算不足以為每包保底「{label}」：請提高售價或降低毛利/保底。"
        remaining = [c for c in remaining if id(c) not in used]
        return None

    if guaranteed_rarity:
        min_rank = rarity_rank(guaranteed_rarity)
        err = guarantee_each_pack(
            lambda c: rarity_rank(c.rarity) >= min_rank,
            f">= {guaranteed_rarity.upper()}",
        )
        if err:
            return OptimizeResult(False, err)

    for cat in (guaranteed_categories or []):
        if cat not in CATEGORIES:
            continue
        err = guarantee_each_pack(
            lambda c, _cat=cat: _cat in card_categories(c),
            CATEGORY_LABELS.get(cat, cat),
        )
        if err:
            return OptimizeResult(False, err)

    # ---- 1. 分池（剩餘卡）-------------------------------------------------
    pools = _classify(remaining)

    # ---- 2. 頭獎輪流分配 (round-robin) ------------------------------------
    # 把最值錢的頭獎卡平均「灑」到不同包，製造稀缺感與公平感；
    # 受預算限制，灑不完的留作 leftover。
    grand_leftover: List[InventoryCard] = []
    gi = 0
    for card in pools[PrizeTier.GRAND]:
        if not can_afford(card):
            grand_leftover.append(card)
            continue
        # 找目前 effective_value 最低的包放，平衡各包價值。
        target = min(packs, key=lambda p: p.effective_value)
        target.cards.append(card)
        allocated_eff += card.effective_value
        gi += 1

    # ---- 3. 二獎分配：優先補「還沒有頭獎」或價值偏低的包 -------------------
    second_leftover: List[InventoryCard] = []
    for card in pools[PrizeTier.SECOND]:
        if not can_afford(card):
            second_leftover.append(card)
            continue
        target = min(packs, key=lambda p: p.effective_value)
        target.cards.append(card)
        allocated_eff += card.effective_value

    # ---- 4. 基底池：把每包補到 floor_per_pack 以上 ------------------------
    base_cards = list(pools[PrizeTier.BASE])
    base_idx = 0

    def next_base() -> Optional[InventoryCard]:
        nonlocal base_idx
        while base_idx < len(base_cards):
            c = base_cards[base_idx]
            base_idx += 1
            return c
        return None

    # 4a. 先確保每包達底價（體感價值用 market_value 衡量）。
    unfilled_floor: List[int] = []
    for p in packs:
        while p.display_value < floor_per_pack:
            c = next_base()
            if c is None:
                break
            if not can_afford(c):
                # 預算不夠塞更多卡，記下此包未達底價。
                base_idx -= 1  # 退回此卡，留給 leftover
                break
            p.cards.append(c)
            allocated_eff += c.effective_value
        if p.display_value < floor_per_pack:
            unfilled_floor.append(p.pack_index)

    # 4b. 預算仍有餘額，把剩餘基底卡平均灑出去消耗滯銷庫存。
    leftover_base: List[InventoryCard] = []
    c = next_base()
    while c is not None:
        if can_afford(c):
            target = min(packs, key=lambda p: p.effective_value)
            target.cards.append(c)
            allocated_eff += c.effective_value
        else:
            leftover_base.append(c)
        c = next_base()

    # ---- 5. 指標與可行性 --------------------------------------------------
    total_display = sum((p.display_value for p in packs), Decimal("0.00"))
    ev_per_pack = _q(total_display / total_packs) if total_packs else Decimal("0.00")
    payback_ratio = float(ev_per_pack / pack_price) if pack_price > 0 else 0.0
    realized_cost = allocated_eff
    realized_margin = (
        float((revenue - realized_cost) / revenue) if revenue > 0 else 0.0
    )

    leftover = grand_leftover + second_leftover + leftover_base

    feasible = len(unfilled_floor) == 0
    if feasible:
        msg = (
            f"成功產生 {total_packs} 包；每包期望體感價值 ${ev_per_pack}，"
            f"實現毛利率 {realized_margin:.1%}"
        )
    else:
        msg = (
            f"預算不足以讓 {len(unfilled_floor)} 個包達到底價 ${floor_per_pack}："
            f"請降低 floor_ratio、提高 pack_price、或補充庫存。"
            f"未達標包索引：{unfilled_floor[:10]}"
        )

    return OptimizeResult(
        feasible=feasible,
        message=msg,
        packs=packs,
        leftover=leftover,
        budget=budget,
        allocated_effective_value=_q(allocated_eff),
        expected_value_per_pack=ev_per_pack,
        realized_margin=round(realized_margin, 4),
        floor_per_pack=floor_per_pack,
        payback_ratio=round(payback_ratio, 4),
    )


def expand_inventory(rows: List[dict]) -> List[InventoryCard]:
    """工具：把 user_inventory join cards 的聚合列（含 quantity）攤平成單卡清單。

    rows 每筆需含：card_id, name_zh, rarity, market_value, liquidity_score, quantity
    """
    out: List[InventoryCard] = []
    for r in rows:
        qty = int(r.get("quantity", 1))
        for _ in range(max(0, qty)):
            out.append(
                InventoryCard(
                    card_id=r["card_id"],
                    name_zh=r["name_zh"],
                    rarity=r["rarity"],
                    market_value=Decimal(str(r["market_value"])),
                    liquidity_score=float(r.get("liquidity_score", 1.0)),
                    card_type=r.get("card_type"),
                )
            )
    return out
