"""卡圖影像比對引擎（ManaBox 式視覺辨識，取代讀小字 OCR）。

- 用 MobileNetV2 分類前的 1280 維 GlobalAveragePool 特徵當 embedding。
- 對 cards 的本地卡圖預先建索引（embeddings.npz）。
- 查詢時把拍到的卡 embed → 與索引做 cosine 相似度 → 取最相近的卡。

索引建置：python -m app.services.image_match --build
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

CARD_ASPECT = 2.5 / 3.5  # 寬/高

_ROOT = Path(__file__).resolve().parents[2]            # backend/
_PROJ = _ROOT.parent                                   # 專案根
MODEL_PATH = _ROOT / "models" / "mobilenetv2.onnx"
EMB_MODEL_PATH = _ROOT / "models" / "mobilenetv2_emb.onnx"
INDEX_PATH = _ROOT / "models" / "card_index.npz"
IMG_ROOT = _PROJ / "webapp" / "public" / "img" / "cards"

EMBED_TENSOR = "464"  # MobileNetV2-12 的 GlobalAveragePool 輸出 (1280 維)
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)

_session: ort.InferenceSession | None = None
_index_vecs: np.ndarray | None = None      # (N, 1280) 已 L2 normalize
_index_ids: list[str] = []


def _ensure_emb_model() -> None:
    """把 GlobalAveragePool 中間層加為輸出，產生可取 embedding 的模型。"""
    if EMB_MODEL_PATH.exists():
        return
    import onnx

    m = onnx.load(str(MODEL_PATH))
    if not any(o.name == EMBED_TENSOR for o in m.graph.output):
        vi = onnx.helper.ValueInfoProto()
        vi.name = EMBED_TENSOR
        m.graph.output.append(vi)
    onnx.save(m, str(EMB_MODEL_PATH))


def _get_session() -> ort.InferenceSession:
    global _session
    if _session is None:
        _ensure_emb_model()
        _session = ort.InferenceSession(
            str(EMB_MODEL_PATH), providers=["CPUExecutionProvider"]
        )
    return _session


def preprocess(img: Image.Image) -> np.ndarray:
    """RGB → [1,3,224,224] ImageNet 正規化。"""
    img = img.convert("RGB").resize((224, 224), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0      # HWC
    arr = arr.transpose(2, 0, 1)                          # CHW
    arr = (arr - _MEAN) / _STD
    return arr[None, ...]


def embed(img: Image.Image) -> np.ndarray:
    """回傳 L2 normalize 後的 1280 維 embedding。"""
    s = _get_session()
    out = s.run([EMBED_TENSOR], {s.get_inputs()[0].name: preprocess(img)})[0]
    v = out.reshape(-1).astype(np.float32)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def embed_bytes(data: bytes) -> np.ndarray:
    return embed(Image.open(io.BytesIO(data)))


# ------------------ 卡片自動偵測（ManaBox 式定位）------------------

def _order_corners(pts: np.ndarray) -> np.ndarray:
    """把 4 點排成 [左上, 右上, 右下, 左下]。"""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]          # 左上：x+y 最小
    rect[2] = pts[np.argmax(s)]          # 右下：x+y 最大
    d = np.diff(pts, axis=1).reshape(-1)
    rect[1] = pts[np.argmin(d)]          # 右上：x-y 最小（y-x 最大）
    rect[3] = pts[np.argmax(d)]          # 左下
    return rect


# 卡片定位參數
_MIN_AREA_FRAC = 0.05    # 卡片矩形至少占畫面 5%（容許卡片不滿版、不置中）
_MAX_AREA_FRAC = 0.985   # 上限：排除整個畫面外框
_MIN_FILL = 0.72         # 輪廓面積 / 其外接矩形面積，須近似實心矩形（卡片是實心方塊）
_RATIO_LO = 0.55         # 短/長邊比下限（標準卡 ≈ 0.714，留誤差含透視傾斜）
_RATIO_HI = 0.88         # 上限


def _candidate_masks(small: np.ndarray) -> list[np.ndarray]:
    """產生多種前景遮罩來源，提升在低對比（白卡白底）與高反光（holo/金卡）下的命中率。"""
    masks: list[np.ndarray] = []
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    k3 = np.ones((3, 3), np.uint8)
    k5 = np.ones((5, 5), np.uint8)

    # 1) Canny 邊緣（膨脹後封閉輪廓）
    edges = cv2.Canny(blur, 30, 120)
    masks.append(cv2.dilate(edges, k3, iterations=2))

    # 2) Otsu 二值化（卡與背景亮度差）；兩個方向都試，不假設卡較亮或較暗
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    masks.append(th)
    masks.append(cv2.bitwise_not(th))

    # 3) 飽和度（holo / 金卡在中性色背景上特別鮮豔，能補強白底白盒情境）
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    _, sth = cv2.threshold(hsv[:, :, 1], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    masks.append(cv2.dilate(sth, k5, iterations=2))
    return masks


def _find_card_quad(small: np.ndarray) -> np.ndarray | None:
    """在縮圖中找最像卡片的矩形，回傳 4 角座標 (4,2)；找不到回 None。

    對每個遮罩取最大的幾個外輪廓，用 minAreaRect 取得旋轉外接矩形，
    以「面積占比 / 長寬比 / 填充率」三項濾除盒子邊框、桌面雜訊、L 形陰影，
    取分數（面積×填充率）最高者。比起「恰好四點凸多邊形」更耐反光與低對比。
    """
    img_area = small.shape[0] * small.shape[1]
    best_score = 0.0
    best_box: np.ndarray | None = None
    for mask in _candidate_masks(small):
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(c)
            if area < _MIN_AREA_FRAC * img_area or area > _MAX_AREA_FRAC * img_area:
                continue
            rect = cv2.minAreaRect(c)
            (rw, rh) = rect[1]
            if rw < 1 or rh < 1:
                continue
            long_, short_ = max(rw, rh), min(rw, rh)
            if not (_RATIO_LO <= short_ / long_ <= _RATIO_HI):
                continue
            fill = area / (rw * rh)
            if fill < _MIN_FILL:
                continue
            score = area * fill
            if score > best_score:
                best_score = score
                best_box = cv2.boxPoints(rect)
    return best_box


def detect_card(data: bytes) -> Image.Image | None:
    """在整張畫面中偵測卡片矩形並透視校正，回傳裁切後的卡片 (PIL)，找不到回 None。

    卡片可在畫面任意位置、不必置中或滿版；偵測不到視為「畫面中沒有卡片」。
    """
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h0, w0 = img.shape[:2]
    scale = 1000.0 / max(h0, w0)
    small = cv2.resize(img, (int(w0 * scale), int(h0 * scale))) if scale < 1 else img
    if scale >= 1:
        scale = 1.0

    quad = _find_card_quad(small)
    if quad is None:
        return None

    rect = _order_corners(quad / scale)  # 還原到原圖座標
    tl, tr, br, bl = rect
    wq = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    hq = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if wq < 20 or hq < 20:
        return None
    dst = np.array(
        [[0, 0], [wq - 1, 0], [wq - 1, hq - 1], [0, hq - 1]], dtype=np.float32
    )
    warped = cv2.warpPerspective(img, cv2.getPerspectiveTransform(rect, dst), (wq, hq))
    if wq > hq:  # 偵測到橫放的卡 → 轉成直向
        warped = cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)
    return Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))


def center_crop_card(img: Image.Image) -> Image.Image:
    """偵測失敗時的後備：取中央卡片比例區域。"""
    img = img.convert("RGB")
    w, h = img.size
    ch = int(h * 0.92)
    cw = int(ch * CARD_ASPECT)
    if cw > w:
        cw = int(w * 0.95)
        ch = int(cw / CARD_ASPECT)
    x = (w - cw) // 2
    y = (h - ch) // 2
    return img.crop((x, y, x + cw, y + ch))


def embed_query(data: bytes) -> tuple[np.ndarray | None, bool]:
    """查詢用：先偵測畫面中的卡片。

    偵測不到就回 (None, False)，由上層拒絕辨識——「確認畫面中有卡片才比對」，
    避免空畫面/桌面被硬塞到最近鄰而誤判。偵測到才裁切+校正後 embed。
    """
    card = detect_card(data)
    if card is None:
        return None, False
    return embed(card), True


def load_index() -> tuple[np.ndarray, list[str]]:
    """載入（並快取）卡圖索引。"""
    global _index_vecs, _index_ids
    if _index_vecs is None:
        if not INDEX_PATH.exists():
            raise FileNotFoundError(
                f"卡圖索引不存在：{INDEX_PATH}，請先執行 --build"
            )
        data = np.load(INDEX_PATH, allow_pickle=True)
        _index_vecs = data["vecs"].astype(np.float32)
        _index_ids = list(data["ids"])
    return _index_vecs, _index_ids


def match(query: np.ndarray, top_k: int = 5) -> list[tuple[str, float]]:
    """回傳 [(card_id, 相似度 0~1), ...]，相似度由高到低。"""
    vecs, ids = load_index()
    sims = vecs @ query                  # cosine（皆已 normalize）
    idx = np.argsort(-sims)[:top_k]
    return [(ids[i], float(sims[i])) for i in idx]


def _iter_card_images():
    """走訪所有本地卡圖，yield (card_id, path)。

    路徑：webapp/public/img/cards/<SET>/<num-safe>.png
    card_id 還原為 <SET>_<num>（num-safe 的 '-' 還原為 '/'）。
    """
    for set_dir in sorted(IMG_ROOT.iterdir()):
        if not set_dir.is_dir():
            continue
        for png in sorted(set_dir.glob("*.png")):
            num = png.stem.replace("-", "/")             # 001-081 → 001/081
            yield f"{set_dir.name}_{num}", png


def build_index() -> int:
    """對所有卡圖建立 embedding 索引並存檔。"""
    ids: list[str] = []
    vecs: list[np.ndarray] = []
    items = list(_iter_card_images())
    print(f"建立索引：{len(items)} 張卡圖...")
    for i, (cid, path) in enumerate(items, 1):
        try:
            with Image.open(path) as im:
                vecs.append(embed(im))
                ids.append(cid)
        except Exception as e:  # noqa: BLE001
            print(f"  ! 略過 {path.name}: {e}")
        if i % 200 == 0:
            print(f"  {i}/{len(items)}")
    mat = np.vstack(vecs).astype(np.float32)
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez(INDEX_PATH, vecs=mat, ids=np.array(ids, dtype=object))
    print(f"完成：{mat.shape[0]} 張，維度 {mat.shape[1]}，存於 {INDEX_PATH.name}")
    return mat.shape[0]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    args = ap.parse_args()
    if args.build:
        build_index()
    else:
        print("用 --build 建立索引")
