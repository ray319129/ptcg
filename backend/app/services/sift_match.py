"""卡片辨識引擎：SIFT 局部特徵 + CLAHE 對比正規化 + FLANN 投票 + RANSAC 幾何驗證。

取代原本「MobileNet 全域 embedding + cosine」的做法——後者對 holo/AR 強反光幾乎失效
（實測 top-1 僅 ~13%）。局部特徵只比對沒被炫光蓋住的區域，並要求幾何一致（單應性內點），
對反光/光線/角度遠為穩健（實測同組 top-1 ~83%，且正確卡內點數常為次高者的數倍）。

流程
----
建索引（一次性）：每張官方卡圖 → 灰階+CLAHE → SIFT 特徵 → 全部串成一個 FLANN 索引，
                  並記錄每個描述子屬於哪張卡、其關鍵點座標。存 models/sift_index.npz。
查詢：偵測畫面中的卡 → 裁切校正 → SIFT → 對全域索引做 knn 比對（ratio test）→
      每張卡累積「投票」(配對數) → 取票數前幾名做 RANSAC 單應性 → 內點數最高者即結果。
信心門檻：最佳內點數需達 MIN_INLIERS 且明顯高於次佳（MARGIN 倍），否則視為「不確定」不回報，
          由連續掃描的下一幀（反光不同）再試。

建索引：python -m app.services.sift_match --build
"""
from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.services.image_match import IMG_ROOT, _iter_card_images, detect_card

INDEX_PATH = Path(__file__).resolve().parents[2] / "models" / "sift_index.npz"

REF_SIZE = (320, 448)          # 參照卡標準化尺寸（卡比例 2.5:3.5）
N_FEATURES = 400               # 每張卡最多取的 SIFT 特徵數（控制索引大小與速度）
RATIO = 0.75                   # Lowe ratio test
SHORTLIST = 25                 # 投票後進入專屬比對 + RANSAC 的候選數
RANSAC_THRESH = 5.0
MIN_INLIERS = 12               # 採信門檻：最佳內點數下限
GROUP_RATIO = 0.62             # 內點數 ≥ 最佳 * 此值的候選視為「同圖不同版」群（≈ margin 1.6）
TOP_K = 5

# 自動讀卡號定版：卡片左下角「集名/卡號」ROI（相對校正後卡片的比例）
NUM_ROI = (0.02, 0.90, 0.58, 0.995)   # (x0,y0,x1,y1) 比例
ROI_MIN_MATCHES = 6            # ROI 比對最少 good matches 才採信自動定版
ROI_MARGIN = 1.5              # ROI 最佳須 ≥ 次佳 * 此值

_sift: cv2.SIFT | None = None
_clahe: cv2.CLAHE | None = None
_bf: cv2.BFMatcher | None = None

# 執行期索引（載入後快取）
_flann: cv2.FlannBasedMatcher | None = None
_desc: np.ndarray | None = None        # (M,128) 全部描述子（依卡連續排列）
_all_kp: np.ndarray | None = None      # (M,2) 每個描述子的參照關鍵點座標
_desc_card: np.ndarray | None = None   # (M,) 每個描述子屬於哪張卡（index 到 _card_ids）
_card_span: list[tuple[int, int]] = [] # 每張卡在 _desc 的 [start,end) 區間（連續）
_card_ids: list[str] = []


def _engines() -> tuple[cv2.SIFT, cv2.CLAHE]:
    global _sift, _clahe, _bf
    if _sift is None:
        _sift = cv2.SIFT_create(nfeatures=N_FEATURES)
        _clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        _bf = cv2.BFMatcher(cv2.NORM_L2)
    return _sift, _clahe


def _features(bgr: np.ndarray):
    """灰階 → CLAHE → SIFT。回傳 (keypoints, descriptors)。"""
    sift, clahe = _engines()
    gray = clahe.apply(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    return sift.detectAndCompute(gray, None)


# ------------------------- 建索引 -------------------------

def build_index() -> int:
    sift, _ = _engines()
    all_desc: list[np.ndarray] = []
    all_kp: list[np.ndarray] = []
    desc_card: list[np.ndarray] = []
    card_ids: list[str] = []
    items = list(_iter_card_images())
    print(f"建立 SIFT 索引：{len(items)} 張卡圖…")
    for ci, (cid, path) in enumerate(items):
        img = cv2.imread(str(path))
        if img is None:
            continue
        kp, des = _features(cv2.resize(img, REF_SIZE))
        if des is None or len(kp) < 8:
            continue
        card_ids.append(cid)
        all_desc.append(des.astype(np.float32))
        all_kp.append(np.float32([k.pt for k in kp]))
        desc_card.append(np.full(len(kp), len(card_ids) - 1, dtype=np.int32))
        if (ci + 1) % 200 == 0:
            print(f"  {ci + 1}/{len(items)}")

    desc_mat = np.vstack(all_desc).astype(np.float32)
    kp_mat = np.vstack(all_kp).astype(np.float32)
    card_vec = np.concatenate(desc_card).astype(np.int32)
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        INDEX_PATH,
        desc=desc_mat,
        kp=kp_mat,
        desc_card=card_vec,
        card_ids=np.array(card_ids, dtype=object),
    )
    print(f"完成：{len(card_ids)} 張卡、{desc_mat.shape[0]} 個描述子，存於 {INDEX_PATH.name}")
    return len(card_ids)


# ------------------------- 載入 / 查詢 -------------------------

def _load() -> None:
    global _flann, _desc, _all_kp, _desc_card, _card_span, _card_ids
    if _flann is not None:
        return
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            f"SIFT 索引不存在：{INDEX_PATH}，請先執行 "
            f"python -m app.services.sift_match --build"
        )
    _engines()
    data = np.load(INDEX_PATH, allow_pickle=True)
    _desc = data["desc"].astype(np.float32)
    _all_kp = data["kp"].astype(np.float32)
    _desc_card = data["desc_card"].astype(np.int32)
    _card_ids = list(data["card_ids"])
    # 每張卡的描述子在 _desc 中是連續排列；記錄區間以便取單卡描述子重新比對
    nc = len(_card_ids)
    starts = np.searchsorted(_desc_card, np.arange(nc), side="left")
    ends = np.searchsorted(_desc_card, np.arange(nc), side="right")
    _card_span = list(zip(starts.tolist(), ends.tolist()))
    # FLANN KD-Tree（SIFT 為浮點描述子，用 L2）做快速「投票」粗篩
    flann = cv2.FlannBasedMatcher(
        {"algorithm": 1, "trees": 4}, {"checks": 32}
    )
    flann.add([_desc])
    flann.train()
    _flann = flann


def _verify(qkp, qdes, q_pts, c: int) -> int:
    """對單一候選卡做專屬 SIFT 比對 + RANSAC，回傳內點數（信心用）。"""
    s, e = _card_span[c]
    if e - s < 8 or _bf is None:
        return 0
    cdes = _desc[s:e]
    matches = _bf.knnMatch(qdes, cdes, k=2)
    good = [m[0] for m in matches if len(m) == 2 and m[0].distance < RATIO * m[1].distance]
    if len(good) < 8:
        return len(good)
    src = q_pts[[m.queryIdx for m in good]].reshape(-1, 1, 2)
    dst = _all_kp[[s + m.trainIdx for m in good]].reshape(-1, 1, 2)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_THRESH)
    return int(mask.sum()) if mask is not None else 0


# 卡片左下角「集名/卡號」ROI 比對，用於同圖不同版自動定版 -----------------
_card_path: dict[str, "Path"] | None = None


def _paths() -> dict[str, Path]:
    global _card_path
    if _card_path is None:
        from app.services.image_match import _iter_card_images

        _card_path = {cid: p for cid, p in _iter_card_images()}
    return _card_path


def _roi_feats(bgr: np.ndarray):
    """取卡片左下角『集名/卡號』ROI 放大後的 SIFT 特徵（小字需放大才有足夠關鍵點）。"""
    h, w = bgr.shape[:2]
    x0, y0, x1, y1 = NUM_ROI
    roi = bgr[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if roi.size == 0:
        return None, None
    roi = cv2.resize(roi, (roi.shape[1] * 3, roi.shape[0] * 3))
    return _features(roi)


def _disambiguate(qbgr: np.ndarray, group_ids: list[str]) -> str | None:
    """同圖不同版：比對左下角卡號 ROI，嘗試自動定出正確版本；不確定回 None（交給使用者選）。"""
    if _bf is None:
        return None
    qkp, qdes = _roi_feats(qbgr)
    if qdes is None or len(qkp) < 6:
        return None
    qdes = qdes.astype(np.float32)
    scores: list[tuple[str, int]] = []
    for cid in group_ids:
        p = _paths().get(cid)
        if p is None:
            continue
        img = cv2.imread(str(p))
        if img is None:
            continue
        rkp, rdes = _roi_feats(cv2.resize(img, REF_SIZE))
        if rdes is None or len(rkp) < 6:
            scores.append((cid, 0))
            continue
        m = _bf.knnMatch(qdes, rdes.astype(np.float32), k=2)
        good = sum(
            1 for x in m if len(x) == 2 and x[0].distance < RATIO * x[1].distance
        )
        scores.append((cid, good))
    scores.sort(key=lambda x: x[1], reverse=True)
    if not scores:
        return None
    best_cid, best = scores[0]
    second = scores[1][1] if len(scores) > 1 else 0
    if best >= ROI_MIN_MATCHES and best >= max(1, second) * ROI_MARGIN:
        return best_cid
    return None


def identify(data: bytes) -> tuple[list[tuple[str, int]], bool, str]:
    """辨識畫面中的卡片。

    回傳 (candidates, detected, status)：
      candidates: [(card_id, inliers), ...] 依內點數高到低。
      detected:   是否在畫面中偵測到卡片矩形。
      status:     'confident' = candidates[0] 即答案；
                  'pick'      = 同圖多版需使用者選（candidates 即版本群）；
                  'none'      = 未達信心（空畫面 / 反光 / 不確定）。
    """
    card = detect_card(data)
    if card is None:
        return [], False, "none"
    _load()
    assert _flann is not None and _all_kp is not None and _desc_card is not None

    qbgr = cv2.resize(
        cv2.cvtColor(np.array(card.convert("RGB")), cv2.COLOR_RGB2BGR), REF_SIZE
    )
    qkp, qdes = _features(qbgr)
    if qdes is None or len(qkp) < 8:
        return [], True, "none"

    qdes = qdes.astype(np.float32)
    q_pts = np.float32([k.pt for k in qkp])

    # 1) 全域 knn 比對 + ratio test → 每張卡累積票數（配對數）做快速粗篩
    matches = _flann.knnMatch(qdes, k=2)
    votes: dict[int, int] = {}
    for m in matches:
        if len(m) < 2 or m[0].distance >= RATIO * m[1].distance:
            continue
        c = int(_desc_card[m[0].trainIdx])
        votes[c] = votes.get(c, 0) + 1
    if not votes:
        return [], True, "none"

    # 2) 票數前 SHORTLIST 名 → 對單卡做專屬比對 + RANSAC，取真實內點數
    shortlist = sorted(votes, key=lambda c: votes[c], reverse=True)[:SHORTLIST]
    scored = [(_card_ids[c], _verify(qkp, qdes, q_pts, c)) for c in shortlist]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:TOP_K]
    best = top[0][1] if top else 0
    if best < MIN_INLIERS:
        return top, True, "none"

    # 3) 同圖不同版判定：內點數與最佳接近(打平)的高分候選視為同圖版本群
    group = [(cid, inl) for cid, inl in top if inl >= GROUP_RATIO * best and inl >= MIN_INLIERS]
    if len(group) <= 1:
        return top, True, "confident"

    # 4) 同圖多版 → 先嘗試自動讀左下角卡號定版；定不出來才交給使用者選
    resolved = _disambiguate(qbgr, [cid for cid, _ in group])
    if resolved is not None:
        reordered = sorted(top, key=lambda x: (x[0] != resolved, -x[1]))
        return reordered, True, "confident"
    return group, True, "pick"


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    args = ap.parse_args()
    if args.build:
        build_index()
    else:
        print("用 --build 建立索引")
