"""神秘包出貨單 PDF 產生器。

使用 reportlab 內建 CID 字型 STSong-Light 渲染繁體中文，
不需外掛 TTF；輸出到 BytesIO 供 FastAPI StreamingResponse 直接回傳。
"""
from __future__ import annotations

import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas.packs import OptimizeResponse, PackDetail

# 註冊一次中文 CID 字型（reportlab 內建，支援 CJK）。
_CJK_FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT))

# 設計色（對齊 app 主題）
_GOLD = colors.HexColor("#FFCB05")
_DARK = colors.HexColor("#1E1E24")
_MINT = colors.HexColor("#1B7F3B")
_GREY = colors.HexColor("#6B6B73")

_TIER_LABEL = {
    "grand": "🏆 頭獎池 (SAR/UR)",
    "second": "🥈 二獎池 (SR/AR)",
    "base": "🥉 基底池 (RR/U/C)",
}


def _styles():
    ss = getSampleStyleSheet()
    base = ss["Normal"].clone("cjk")
    base.fontName = _CJK_FONT
    base.fontSize = 9
    title = ParagraphStyle(
        "cjkTitle", parent=base, fontSize=18, leading=22, spaceAfter=6
    )
    h2 = ParagraphStyle(
        "cjkH2", parent=base, fontSize=12, leading=16, textColor=_DARK,
        spaceBefore=8, spaceAfter=4,
    )
    small = ParagraphStyle("cjkSmall", parent=base, fontSize=8, textColor=_GREY)
    return base, title, h2, small


def _money(d: Decimal) -> str:
    return f"${Decimal(d):,.0f}"


def _summary_table(resp: OptimizeResponse, base_style) -> Table:
    rows = [
        ["總包數", str(resp.total_packs), "每包售價", _money(resp.pack_price)],
        [
            "目標毛利",
            f"{resp.target_margin:.0%}",
            "實現毛利",
            f"{resp.realized_margin:.1%}",
        ],
        [
            "成本預算",
            _money(resp.budget),
            "已配置成本",
            _money(resp.allocated_effective_value),
        ],
        [
            "每包期望值",
            _money(resp.expected_value_per_pack),
            "每包底價",
            _money(resp.floor_per_pack),
        ],
        [
            "剩餘未配置",
            f"{resp.leftover_count} 張",
            "剩餘價值",
            _money(resp.leftover_value),
        ],
    ]
    t = Table(rows, colWidths=[28 * mm, 40 * mm, 28 * mm, 40 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), _CJK_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), _GREY),
                ("TEXTCOLOR", (2, 0), (2, -1), _GREY),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F4F6")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E5E8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def _pack_table(pack: PackDetail) -> Table:
    """單一包的卡片明細表，依獎級分區。"""
    header = ["獎級", "卡號", "名稱", "稀有度", "市值"]
    data = [header]
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, -1), _CJK_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), _DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E5E8")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    row_idx = 1
    for tier_key in ("grand", "second", "base"):
        lines = getattr(pack.tiers, tier_key)
        if not lines:
            continue
        # 獎級分隔列
        data.append([_TIER_LABEL[tier_key], "", "", "", ""])
        style_cmds.append(
            ("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#FFF6D6"))
        )
        style_cmds.append(("SPAN", (0, row_idx), (-1, row_idx)))
        row_idx += 1
        for ln in lines:
            data.append(
                [
                    "",
                    ln.card_id,
                    ln.name_zh,
                    ln.rarity,
                    _money(ln.market_value),
                ]
            )
            row_idx += 1

    t = Table(data, colWidths=[34 * mm, 30 * mm, 56 * mm, 18 * mm, 22 * mm])
    t.setStyle(TableStyle(style_cmds))
    return t


def build_packing_list_pdf(resp: OptimizeResponse) -> bytes:
    """產生完整出貨單 PDF，回傳 bytes。"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="神秘包出貨單",
    )
    base, title, h2, small = _styles()
    story = []

    story.append(Paragraph("神秘包出貨單 / Packing List", title))
    if resp.plan_id:
        story.append(Paragraph(f"計畫編號：{resp.plan_id}", small))
    status = "可行 ✓" if resp.feasible else "不可行 ✗（請見訊息）"
    story.append(Paragraph(f"狀態：{status}", small))
    story.append(Paragraph(resp.message, small))
    story.append(Spacer(1, 6))
    story.append(_summary_table(resp, base))
    story.append(Spacer(1, 10))

    # 每包一節；包數很多時每 N 包換頁避免單頁過長。
    for i, pack in enumerate(resp.packs):
        story.append(
            Paragraph(
                f"第 {pack.pack_index + 1} 包　|　體感價值 {_money(pack.display_value)}",
                h2,
            )
        )
        story.append(_pack_table(pack))
        story.append(Spacer(1, 8))
        # 每 6 包換頁，保持版面整齊
        if (i + 1) % 6 == 0 and i + 1 < len(resp.packs):
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()
