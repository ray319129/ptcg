"""真實照片辨識評測（SIFT 幾何辨識引擎）。

讀 _samples/manifest.csv（filename,card_id），對每張實拍照片跑辨識，
report top-1 / top-5 準確率、內點數、信心門檻判定、每張耗時，以及空畫面假陽性率。
card_id 填 NONE 代表「畫面中沒有卡」。

用法：PYTHONIOENCODING=utf-8 python eval_match.py
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

from app.services import sift_match as sm

SAMPLES = Path(__file__).resolve().parent / "_samples"
MANIFEST = SAMPLES / "manifest.csv"


def main() -> int:
    if not MANIFEST.exists():
        print(f"找不到 {MANIFEST}")
        return 1
    rows = [
        r
        for r in csv.DictReader(MANIFEST.read_text(encoding="utf-8").splitlines())
        if r.get("filename", "").strip()
    ]
    card_rows = [r for r in rows if r["card_id"].strip().upper() != "NONE"]
    none_rows = [r for r in rows if r["card_id"].strip().upper() == "NONE"]
    if not card_rows and not none_rows:
        print("manifest.csv 還沒有資料。")
        return 0

    top1 = top5 = shown_ok = 0
    print(f"{'檔名':16} {'偵測':4} {'top1':16} {'內點':5} {'rank':5} {'信心':5} {'秒':5} 判定")
    print("-" * 86)
    for r in card_rows:
        fn, gold = r["filename"].strip(), r["card_id"].strip()
        p = SAMPLES / fn
        if not p.exists():
            print(f"{fn:16} 檔案不存在")
            continue
        t0 = time.time()
        cand, detected, mstatus = sm.identify(p.read_bytes())
        confident = mstatus == "confident"
        dt = time.time() - t0
        if not detected:
            print(f"{fn:16} {'F':4} {'(未偵測到)':16} {'-':5} {'-':5} {'-':5} {dt:4.1f} 漏抓")
            continue
        if not cand:
            print(f"{fn:16} {'T':4} {'(無配對)':16} {'-':5} {'-':5} {'-':5} {dt:4.1f} 無解")
            continue
        ids = [c for c, _ in cand]
        inl = cand[0][1]
        rank = ids.index(gold) + 1 if gold in ids else 0
        top1 += rank == 1
        top5 += rank >= 1
        shown_ok += confident and ids[0] == gold
        verdict = "✓對" if ids[0] == gold else f"✗錯({ids[0]})"
        print(f"{fn:16} {'T':4} {ids[0]:16} {inl:5} {rank or '—':>5} "
              f"{'是' if confident else '否':5} {dt:4.1f} {verdict}")

    n = len(card_rows)
    print("-" * 86)
    if n:
        print(f"Top-1 準確率: {top1}/{n} = {top1/n:.0%}")
        print(f"Top-5 準確率: {top5}/{n} = {top5/n:.0%}")
        print(f"通過信心門檻且正確: {shown_ok}/{n} = {shown_ok/n:.0%}")

    if none_rows:
        fp = 0
        for r in none_rows:
            p = SAMPLES / r["filename"].strip()
            if not p.exists():
                continue
            cand, detected, mstatus = sm.identify(p.read_bytes())
            if mstatus in ("confident", "pick"):
                fp += 1
                print(f"空畫面 {r['filename']} 誤觸發({mstatus}) {cand[0] if cand else ''}")
        print(f"空畫面誤判(假陽性): {fp}/{len(none_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
