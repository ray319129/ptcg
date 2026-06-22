"""掃描 / 解析模組的 Pydantic 資料模型 (Request / Response Schema)。

所有對外 API 的輸入輸出都經過這裡的型別約束，避免 OCR 端傳入髒資料
直接打到資料庫層，並讓 FastAPI 自動產生 OpenAPI 文件。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class MatchMethod(str, Enum):
    """記錄這張卡片最終是用哪一條路徑命中的，方便前端決定 UI 呈現與後續分析。"""

    EXACT_REGEX = "exact_regex"          # 正則一次命中，信心最高
    FUZZY_TRIGRAM = "fuzzy_trigram"      # pg_trgm 相似度命中
    FUZZY_LEVENSHTEIN = "fuzzy_lev"      # 編輯距離命中
    AMBIGUOUS = "ambiguous"              # 多個候選，需使用者二次確認
    NOT_FOUND = "not_found"              # 完全找不到


class ScanRequest(BaseModel):
    """前端「信心投票佇列」收斂後送來的單筆原始 OCR 文字。"""

    raw_text: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="OCR 原始字串，例如 ' SV8a   217/187  SAR '",
        examples=[" SV8a   217/187  SAR "],
    )
    # 前端把最後 5 幀投票的最高頻信心值帶上來，後端用來決定要不要直接走 fuzzy。
    client_confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="前端信心投票佇列勝出值的信心分數 (0~1)",
    )
    # 允許前端指定使用者，未登入情境可為 None（僅回傳百科資料，不查庫存）。
    user_id: Optional[str] = Field(default=None, description="使用者 UUID 字串")

    @field_validator("raw_text")
    @classmethod
    def _strip_text(cls, v: str) -> str:
        # 先把 OCR 常見的全形空白、換行壓平，避免污染後續 regex。
        cleaned = " ".join(v.replace("　", " ").split())
        if not cleaned:
            raise ValueError("raw_text 去除空白後為空字串")
        return cleaned


class CardCandidate(BaseModel):
    """模糊比對時的單一候選項，附帶相似度供前端「你是不是要找？」抽屜排序。"""

    card_id: str
    set_code: str
    card_number: str
    rarity: str
    name_zh: str
    similarity: float = Field(..., ge=0.0, le=1.0, description="與 OCR 字串的綜合相似度")


class MarketValue(BaseModel):
    """估價引擎輸出的市場價值區塊。"""

    estimated_price: Decimal = Field(..., description="主估值（依稀有度分層策略計算）")
    currency: str = Field(default="TWD")
    avg_7d: Optional[Decimal] = Field(default=None, description="7 日 VWMA")
    highest_deal: Optional[Decimal] = None
    lowest_ask: Optional[Decimal] = None
    liquidity_score: float = Field(..., ge=0.0, le=1.0)
    tier_strategy: str = Field(..., description="採用的估值層級策略名稱")
    is_stale: bool = Field(default=False, description="價格資料是否逾時（>24h 未更新）")


class CardProfile(BaseModel):
    """命中後回傳的完整卡片檔案。"""

    card_id: str
    set_code: str
    card_number: str
    rarity: str
    name_zh: str
    market_value: MarketValue
    in_collection_count: int = Field(default=0, description="該使用者已持有數量")


class ScanResponse(BaseModel):
    """/api/v1/parser/scan 的統一回傳格式。"""

    success: bool
    method: MatchMethod
    # 成功且唯一時填入 profile；ambiguous 時 profile 為 None、candidates 有多筆。
    profile: Optional[CardProfile] = None
    candidates: List[CardCandidate] = Field(default_factory=list)
    message: str = Field(default="")
    parsed_at: datetime = Field(default_factory=datetime.utcnow)
