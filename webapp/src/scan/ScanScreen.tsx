// 掃描頁（連續自動偵測版）：
// - 卡片放到畫面、靜止片刻 → 自動拍照上傳後端偵測+比對（不必手動按）。
// - 結果浮層讓你選「對 → 選數量入庫」或「不是 → 重新掃描 / 看其他候選」。
// - 掃描器開著就持續偵測，換一張卡會自動辨識下一張。
// - 左上角可切換「繁中版 / 日文版」卡價（持久記住，不必每次選）。
import { useCallback, useEffect, useRef, useState } from "react";
import {
  addInventory,
  matchCard,
  type MatchCandidate,
  type MatchResponse,
} from "../api/endpoints";
import { useApp } from "../store";
import { money, rarityColor } from "../utils/format";
import "./scan.css";

interface Props {
  userId?: string;
  onClose: () => void;
}

type Phase = "starting" | "scanning" | "matching" | "error";

const SIG_N = 16; // 影像簽章 16x16
const TICK_MS = 300; // 取樣間隔
const MATCH_INTERVAL = 1200; // 最快多久嘗試一次比對（毫秒）
const MIN_VARIANCE = 230; // 中央區域變異 < 此值 → 視為空畫面/桌面，不浪費比對
const SAME_CARD_DIFF = 10; // 與上次已比對卡的簽章差異 < 此值 → 視為同一張，跳過

export function ScanScreen({ userId, onClose }: Props) {
  const priceLang = useApp((s) => s.priceLang);
  const setPriceLang = useApp((s) => s.setPriceLang);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sigCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastTsRef = useRef(0);

  const matchedSigRef = useRef<Uint8Array | null>(null); // 上次已比對的卡簽章
  const lastAttemptRef = useRef(0); // 上次嘗試比對的時間
  const busyRef = useRef(false); // 正在比對 or 顯示結果中 → 暫停觸發

  const [phase, setPhase] = useState<Phase>("starting");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [result, setResult] = useState<MatchResponse | null>(null);
  const [selected, setSelected] = useState<MatchCandidate | null>(null);
  const [showCandidates, setShowCandidates] = useState(false);
  const [qty, setQty] = useState(1);
  const [savedCount, setSavedCount] = useState(0);

  // ---- 影像簽章（中央區域，灰階 16x16）----
  const signature = useCallback((): Uint8Array | null => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return null;
    let cv = sigCanvasRef.current;
    if (!cv) {
      cv = document.createElement("canvas");
      cv.width = SIG_N;
      cv.height = SIG_N;
      sigCanvasRef.current = cv;
    }
    const g = cv.getContext("2d", { willReadFrequently: true })!;
    // 取中央 70% 區域
    const vw = v.videoWidth;
    const vh = v.videoHeight;
    const cw = vw * 0.7;
    const ch = vh * 0.7;
    g.drawImage(v, (vw - cw) / 2, (vh - ch) / 2, cw, ch, 0, 0, SIG_N, SIG_N);
    const { data } = g.getImageData(0, 0, SIG_N, SIG_N);
    const sig = new Uint8Array(SIG_N * SIG_N);
    for (let i = 0; i < sig.length; i++) {
      sig[i] = (data[i * 4] + data[i * 4 + 1] + data[i * 4 + 2]) / 3;
    }
    return sig;
  }, []);

  const sigDiff = (a: Uint8Array, b: Uint8Array): number => {
    let s = 0;
    for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]);
    return s / a.length;
  };

  // 中央區域的變異度（卡片有圖案 → 高；空桌面 → 低）
  const variance = (sig: Uint8Array): number => {
    let mean = 0;
    for (const v of sig) mean += v;
    mean /= sig.length;
    let va = 0;
    for (const v of sig) va += (v - mean) * (v - mean);
    return va / sig.length;
  };

  // ---- 拍照（整張畫面縮放）→ JPEG ----
  const capture = useCallback((): Promise<Blob | null> => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return Promise.resolve(null);
    const vw = v.videoWidth;
    const vh = v.videoHeight;
    const scale = Math.min(1, 1100 / Math.max(vw, vh));
    const cv = document.createElement("canvas");
    cv.width = Math.round(vw * scale);
    cv.height = Math.round(vh * scale);
    cv.getContext("2d")!.drawImage(v, 0, 0, cv.width, cv.height);
    return new Promise((res) => cv.toBlob((b) => res(b), "image/jpeg", 0.85));
  }, []);

  const triggerReward = useCallback((rarity: string) => {
    const high = ["SAR", "UR", "SR", "MUR", "MA", "SSR", "HR"].includes(
      rarity.toUpperCase(),
    );
    if ("vibrate" in navigator) navigator.vibrate(high ? [40, 30, 120] : 20);
  }, []);

  // ---- 比對 ----
  const doMatch = useCallback(
    async (sig: Uint8Array) => {
      if (!userId) return;
      busyRef.current = true;
      setPhase("matching");
      const blob = await capture();
      if (!blob) {
        busyRef.current = false;
        setPhase("scanning");
        return;
      }
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        const resp = await matchCard(blob, userId, priceLang, ac.signal);
        // success：高信心 → 直接跳結果。
        // needs_pick：同圖多版且讀不出卡號 → 跳結果並自動展開版本清單讓使用者選。
        // 其餘（信心不足/沒偵測到卡）→ 不記簽章，下個間隔再試（閃卡反光每幀不同）。
        if (resp.success && resp.best) {
          const pick = resp.best;
          matchedSigRef.current = sig;
          setResult(resp);
          setSelected(pick);
          setQty(1);
          setShowCandidates(false);
          triggerReward(pick.rarity);
          setPhase("scanning"); // 畫面不停，但 busyRef 仍鎖住（結果顯示中）
        } else if (resp.needs_pick && resp.best) {
          matchedSigRef.current = sig;
          setResult(resp);
          setSelected(resp.best); // 預選最佳猜測，使用者可改
          setQty(1);
          setShowCandidates(true); // 自動展開版本清單
          setPhase("scanning");
        } else {
          busyRef.current = false;
          setPhase("scanning");
        }
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          busyRef.current = false;
          setPhase("scanning");
        }
      }
    },
    [userId, capture, priceLang, triggerReward],
  );

  // ---- 連續取樣迴圈（定時偵測，不要求畫面靜止，閃卡反光也能觸發）----
  const tick = useCallback(() => {
    rafRef.current = requestAnimationFrame(tick);
    const now = performance.now();
    if (now - lastTsRef.current < TICK_MS) return;
    lastTsRef.current = now;
    if (busyRef.current) return; // 比對中或結果顯示中 → 不觸發
    if (now - lastAttemptRef.current < MATCH_INTERVAL) return; // 節流

    const sig = signature();
    if (!sig) return;
    if (variance(sig) < MIN_VARIANCE) return; // 空畫面/桌面，不浪費比對
    // 與上次已比對的卡太像（同一張還在框內）→ 跳過，避免重複
    const matched = matchedSigRef.current;
    if (matched && sigDiff(matched, sig) < SAME_CARD_DIFF) return;

    lastAttemptRef.current = now;
    void doMatch(sig);
  }, [signature, doMatch]);

  // ---- 相機 ----
  const start = useCallback(async () => {
    setPhase("starting");
    setErrorMsg(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      });
      streamRef.current = stream;
      const v = videoRef.current!;
      v.srcObject = stream;
      v.setAttribute("playsinline", "true");
      await v.play();
      setPhase("scanning");
      rafRef.current = requestAnimationFrame(tick);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : "無法存取相機");
      setPhase("error");
    }
  }, [tick]);

  const stop = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    abortRef.current?.abort();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    void start();
    return () => stop();
  }, [start, stop]);

  // ---- 結果操作 ----
  const dismiss = useCallback((allowResameCard: boolean) => {
    setResult(null);
    setSelected(null);
    setShowCandidates(false);
    // allowResameCard=true（都不是/重新掃描）：清掉已比對簽章，讓同一張卡也能重觸發
    if (allowResameCard) matchedSigRef.current = null;
    lastAttemptRef.current = performance.now(); // 加個冷卻，避免立刻重跳同一張
    busyRef.current = false;
  }, []);

  const accept = useCallback(async () => {
    const card = selected;
    if (card && userId) {
      try {
        await addInventory(userId, card.card_id, qty);
        setSavedCount((c) => c + qty);
      } catch {
        /* 入庫失敗不阻斷 */
      }
    }
    // 收藏後保留 matchedSig（同卡還在畫面不重觸發），移除卡片後自動掃下一張
    dismiss(false);
  }, [selected, userId, qty, dismiss]);

  const isHighTier =
    !!selected &&
    ["SAR", "UR", "SR", "MUR", "MA", "SSR", "HR"].includes(
      selected.rarity.toUpperCase(),
    );

  return (
    <div className="scan-root">
      <video ref={videoRef} className="scan-video" muted playsInline />
      <div className={`scan-viewfinder ${isHighTier ? "gold" : ""}`} />

      {/* 頂部列：語言切換 + 已收藏 + 關閉 */}
      <div className="scan-topbar">
        <div className="lang-toggle">
          <button
            className={priceLang === "tw" ? "on" : ""}
            onClick={() => setPriceLang("tw")}
          >
            繁中
          </button>
          <button
            className={priceLang === "jp" ? "on" : ""}
            onClick={() => setPriceLang("jp")}
          >
            日文
          </button>
        </div>
        <span className="badge mono">已收藏 {savedCount}</span>
        <button className="icon-btn" onClick={onClose} aria-label="關閉">
          ✕
        </button>
      </div>

      {phase === "error" && (
        <div className="scan-error surface">
          {errorMsg}
          <button className="btn-gold" style={{ marginTop: 12 }} onClick={start}>
            重試
          </button>
        </div>
      )}

      {/* 狀態提示（無結果時）*/}
      {!result && phase !== "error" && (
        <div className="scan-hint">
          {phase === "matching" ? "辨識中…" : "將卡片放到框內，會自動辨識"}
        </div>
      )}

      {/* 結果浮層 */}
      {result && selected && (
        <div className={`result-tile surface ${isHighTier ? "gold-border" : ""}`}>
          <div className="rt-thumb">
            {selected.image_url && (
              <img src={selected.image_url} alt={selected.name_zh} />
            )}
          </div>
          <div className="rt-left">
            <span className="mono rt-code">
              {selected.set_code} {selected.card_number} {selected.rarity}
            </span>
            <span className="rt-name">{selected.name_zh}</span>
            <span className="rt-price">
              {money(selected.market_value)}
              <small className="rt-lang">
                {priceLang === "tw" ? " 繁中" : " 日文"}
              </small>
            </span>
            <div className="rt-actions">
              <button
                className="rt-link"
                onClick={() => setShowCandidates((s) => !s)}
              >
                看其他候選
              </button>
              <button className="rt-link warn" onClick={() => dismiss(true)}>
                都不是 / 重掃
              </button>
            </div>
          </div>
          <div className="rt-right">
            <span className="rt-owned">已持有 ×{selected.in_collection_count}</span>
            <div className="qty-stepper">
              <button onClick={() => setQty((q) => Math.max(1, q - 1))}>−</button>
              <span className="mono">{qty}</span>
              <button onClick={() => setQty((q) => q + 1)}>+</button>
            </div>
            <button className="btn-gold rt-cta" onClick={accept}>
              收藏 {qty} 張 →
            </button>
          </div>
        </div>
      )}

      {/* 候選清單 */}
      {result && showCandidates && (
        <div className="suggest-drawer">
          <div className="suggest-title">
            {result.needs_pick
              ? "🔀 這張圖有多個版本，請選擇正確的卡號/系列"
              : "其他可能（相似度排序）"}
          </div>
          <div className="suggest-list">
            {result.candidates.map((c) => (
              <button
                key={c.card_id}
                className={`suggest-item surface ${
                  selected?.card_id === c.card_id ? "sel" : ""
                }`}
                onClick={() => {
                  setSelected(c);
                  setShowCandidates(false);
                }}
              >
                {c.image_url && (
                  <img className="sg-img" src={c.image_url} alt={c.name_zh} />
                )}
                <span className="mono">
                  {c.set_code} {c.card_number}
                </span>
                <span className="name">{c.name_zh}</span>
                <span className="sg-meta">
                  <span style={{ color: rarityColor(c.rarity) }}>{c.rarity}</span>{" "}
                  · {money(c.market_value)} · {Math.round(c.similarity * 100)}%
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
