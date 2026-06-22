// 相機掃描 Hook —— 對應 Flutter 的 CardScanner。
// 串接：getUserMedia → 幀節流 → 背壓鎖 → ROI 裁切 → OCR worker → 投票佇列。

import { useCallback, useEffect, useRef, useState } from "react";
import { VotingQueue, type VoteResult } from "./votingQueue";

export type ScannerStatus = "idle" | "starting" | "scanning" | "error";

interface WorkerResult {
  type: "result";
  seq: number;
  text: string;
  confidence: number;
  ms: number;
}
interface WorkerReady {
  type: "ready";
  backend: "webgpu" | "wasm";
}
interface WorkerError {
  type: "error";
  message: string;
}
type WorkerMsg = WorkerResult | WorkerReady | WorkerError;

export interface ScannerOptions {
  // 收斂出高信心結果時呼叫（前端直接採信）
  onHighConfidence: (vote: VoteResult) => void;
  // 收斂但信心不足時呼叫（交後端雙軌 fuzzy）
  onLowConfidence: (vote: VoteResult) => void;
  throttleMs?: number; // OCR 取樣間隔，預設 80ms (~12fps)
  roiRatio?: number; // ROI 取卡片底部比例，預設 0.15
}

export interface ScannerHandle {
  videoRef: React.RefObject<HTMLVideoElement>;
  status: ScannerStatus;
  backend: "webgpu" | "wasm" | null;
  lastMs: number; // 最近一次推論耗時，供 HUD 顯示效能
  lastText: string; // 最近一次辨識到的文字（即時回饋）
  errorMsg: string | null;
  start: () => Promise<void>;
  stop: () => void;
  /** 收齊一張卡後呼叫，清空投票視窗準備下一張。 */
  acceptAndReset: () => void;
}

export function useCardScanner(opts: ScannerOptions): ScannerHandle {
  const { onHighConfidence, onLowConfidence } = opts;
  const throttleMs = opts.throttleMs ?? 80;
  const roiRatio = opts.roiRatio ?? 0.15;

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workerRef = useRef<Worker | null>(null);
  const queueRef = useRef(new VotingQueue());
  const roiCanvasRef = useRef<HTMLCanvasElement | null>(null); // ROI 裁切用，重複使用

  const busyRef = useRef(false); // 背壓鎖：上一幀未處理完就丟棄新幀
  const lastTsRef = useRef(0);
  const seqRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const lockedRef = useRef(false); // 已收齊一張、等待 reset 期間暫停送幀
  const readyRef = useRef(false); // 模型是否初始化完成
  const frameErrRef = useRef(0); // 連續單幀錯誤計數

  const [status, setStatus] = useState<ScannerStatus>("idle");
  const [backend, setBackend] = useState<"webgpu" | "wasm" | null>(null);
  const [lastMs, setLastMs] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastText, setLastText] = useState(""); // 最近一次辨識文字（給使用者回饋）

  // 回呼以 ref 保存，避免 hook 依賴變動造成迴圈重建。
  const cbRef = useRef({ onHighConfidence, onLowConfidence });
  cbRef.current = { onHighConfidence, onLowConfidence };

  // ---- 初始化 worker ----
  useEffect(() => {
    const w = new Worker(
      new URL("./ocrEngine.worker.ts", import.meta.url),
      { type: "module" },
    );
    workerRef.current = w;
    w.onmessage = (e: MessageEvent<WorkerMsg>) => {
      const msg = e.data;
      if (msg.type === "ready") {
        readyRef.current = true;
        setBackend(msg.backend);
        return;
      }
      if (msg.type === "error") {
        busyRef.current = false; // 一律解除背壓，避免死鎖
        if (!readyRef.current) {
          // 初始化階段失敗 → 致命，顯示錯誤
          setErrorMsg(msg.message);
          setStatus("error");
        } else {
          // 已就緒後的單幀錯誤 → 不中斷掃描，連續多次才提示
          frameErrRef.current += 1;
          if (frameErrRef.current >= 15) {
            setErrorMsg("辨識持續失敗，請重新整理頁面");
            setStatus("error");
          }
        }
        return;
      }
      // result
      busyRef.current = false; // 解除背壓，允許下一幀
      frameErrRef.current = 0;
      setLastMs(Math.round(msg.ms));
      if (msg.text) setLastText(msg.text);
      if (lockedRef.current) return;

      const normalized = msg.text.replace(/\s+/g, " ").trim();
      queueRef.current.push({ text: normalized, confidence: msg.confidence });
      const vote = queueRef.current.vote();
      if (!vote) return;

      lockedRef.current = true; // 暫停送幀直到上層決定
      if (queueRef.current.isHighConfidence(vote)) {
        cbRef.current.onHighConfidence(vote);
      } else {
        cbRef.current.onLowConfidence(vote);
      }
    };
    w.postMessage({
      type: "init",
      modelUrl: "/models/rec.onnx",
      dictUrl: "/models/ppocr_keys_v1.txt",
    });
    return () => {
      w.terminate();
      workerRef.current = null;
    };
  }, []);

  // ---- 取幀迴圈 ----
  const tick = useCallback(() => {
    rafRef.current = requestAnimationFrame(tick);
    const video = videoRef.current;
    const worker = workerRef.current;
    if (!video || !worker || video.readyState < 2) return;
    if (busyRef.current || lockedRef.current) return;

    const now = performance.now();
    if (now - lastTsRef.current < throttleMs) return;
    lastTsRef.current = now;
    busyRef.current = true;

    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh) {
      busyRef.current = false;
      return;
    }
    // ROI：影像底部 roiRatio 高度（卡號/稀有度所在）。畫到固定寬度的小 canvas，
    // 控制記憶體並相容 iOS Safari（避免 createImageBitmap 的影片裁切多載相容性問題）。
    const sy = Math.round(vh * (1 - roiRatio));
    const sh = vh - sy;
    const outW = Math.min(640, vw);
    const outH = Math.max(1, Math.round((sh / vw) * outW));

    let cv = roiCanvasRef.current;
    if (!cv) {
      cv = document.createElement("canvas");
      roiCanvasRef.current = cv;
    }
    cv.width = outW;
    cv.height = outH;
    const c2d = cv.getContext("2d");
    if (!c2d) {
      busyRef.current = false;
      return;
    }
    const seq = ++seqRef.current;
    try {
      c2d.drawImage(video, 0, sy, vw, sh, 0, 0, outW, outH);
    } catch {
      busyRef.current = false; // 影片尚未可繪製
      return;
    }
    createImageBitmap(cv)
      .then((bitmap) => {
        const w = workerRef.current;
        if (!w) {
          bitmap.close();
          busyRef.current = false;
          return;
        }
        w.postMessage({ type: "frame", seq, bitmap }, [bitmap]);
      })
      .catch(() => {
        busyRef.current = false; // 解鎖，避免永久卡死
      });
  }, [throttleMs, roiRatio]);

  const start = useCallback(async () => {
    setStatus("starting");
    setErrorMsg(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" }, // 後鏡頭
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current!;
      video.srcObject = stream;
      video.setAttribute("playsinline", "true"); // iOS 必要，避免全螢幕接管
      await video.play();
      lockedRef.current = false;
      setStatus("scanning");
      rafRef.current = requestAnimationFrame(tick);
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : "無法存取相機，請確認權限",
      );
      setStatus("error");
    }
  }, [tick]);

  const stop = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    busyRef.current = false;
    lockedRef.current = false;
    queueRef.current.reset();
    setStatus("idle");
  }, []);

  const acceptAndReset = useCallback(() => {
    queueRef.current.reset();
    lockedRef.current = false; // 恢復送幀，掃下一張
  }, []);

  // 卸載時確保釋放相機（行動裝置不釋放會耗電 / 占用鏡頭）。
  useEffect(() => () => stop(), [stop]);

  return {
    videoRef,
    status,
    backend,
    lastMs,
    lastText,
    errorMsg,
    start,
    stop,
    acceptAndReset,
  };
}
