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


def detect_card(data: bytes) -> Image.Image | None:
    """在整張畫面中偵測卡片矩形並透視校正，回傳裁切後的卡片 (PIL)，找不到回 None。

    流程：灰階 → 模糊 → Canny 邊緣 → 膨脹 → 找輪廓 → 取最大且近似四邊形者 →
    依四角透視校正成正面卡片影像。
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

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 40, 130)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    img_area = small.shape[0] * small.shape[1]
    quad = None
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if (
            len(approx) == 4
            and cv2.isContourConvex(approx)
            and cv2.contourArea(approx) > 0.10 * img_area
        ):
            quad = approx.reshape(4, 2).astype(np.float32)
            break
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


def embed_query(data: bytes) -> tuple[np.ndarray, bool]:
    """查詢用：先偵測卡片，偵測失敗則中央裁切。回傳 (embedding, 是否偵測到卡片)。"""
    card = detect_card(data)
    detected = card is not None
    if card is None:
        card = center_crop_card(Image.open(io.BytesIO(data)))
    return embed(card), detected


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
