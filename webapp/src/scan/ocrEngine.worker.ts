/// <reference lib="webworker" />
// WebGPU OCR 引擎（Web Worker）。
//
// 設計重點：
//  - 只做「單行文字辨識 (recognition)」，不做文字偵測 —— 因為前端已把 ROI
//    裁成卡片底部 15% 的單行字串區，省去最複雜且易出錯的 DB 偵測後處理。
//  - 模型用 ONNX Runtime Web 的 WebGPU execution provider；失敗自動退回 wasm。
//  - 推論在 worker 執行緒，主執行緒永遠不被阻塞（等同 Flutter isolate）。
//
// 模型檔放置（自備 PP-OCRv4 rec 的 onnx 與字典）：
//   /public/models/rec.onnx
//   /public/models/ppocr_keys_v1.txt   (每行一字元；index 0 為 CTC blank)

import * as ort from "onnxruntime-web/webgpu";

// ORT 的 wasm 二進位改從同源 /ort/ 載入（dev 模式不會自動服務 node_modules 內的 wasm，
// 預設路徑會抓到 SPA 的 index.html 導致 "expected magic word" 錯誤）。
ort.env.wasm.wasmPaths = "/ort/";
// 單執行緒：免依賴 SharedArrayBuffer / 跨來源隔離（透過 tunnel 較穩）。WebGPU 由 GPU 運算，
// wasm 僅作膠水/後備，單執行緒影響有限。
ort.env.wasm.numThreads = 1;

// ---- worker 訊息協定 -------------------------------------------------------
interface InitMsg {
  type: "init";
  modelUrl: string;
  dictUrl: string;
}
interface FrameMsg {
  type: "frame";
  seq: number; // 幀序號，供主執行緒對齊背壓
  bitmap: ImageBitmap; // 已裁切的 ROI
}
type InMsg = InitMsg | FrameMsg;

interface ReadyMsg {
  type: "ready";
  backend: "webgpu" | "wasm";
}
interface ResultMsg {
  type: "result";
  seq: number;
  text: string;
  confidence: number;
  ms: number;
}
interface ErrorMsg {
  type: "error";
  message: string;
}

const ctx = self as unknown as DedicatedWorkerGlobalScope;

// ---- 模型輸入規格 (PP-OCRv4 mobile rec) ------------------------------------
const REC_H = 48;
const REC_W = 320;

let session: ort.InferenceSession | null = null;
let charset: string[] = [];
let backend: "webgpu" | "wasm" = "wasm";

// 在 worker 內用 OffscreenCanvas 做前處理，避免把像素搬回主執行緒。
const canvas = new OffscreenCanvas(REC_W, REC_H);
const cctx = canvas.getContext("2d", { willReadFrequently: true })!;

async function init(modelUrl: string, dictUrl: string): Promise<void> {
  // 字典：每行一字元，index 0 預留給 CTC blank。
  const dictText = await (await fetch(dictUrl)).text();
  charset = ["<blank>", ...dictText.split(/\r?\n/).filter((c) => c.length > 0)];
  charset.push(" "); // PP-OCR 慣例：字典尾端補一個空白字元

  // 後端固定用 wasm（單執行緒 asyncify）。手機端 WebGPU 在重模型上常造成 GPU 行程
  // 崩潰（「網頁發生錯誤」），wasm 雖較慢但跨裝置最穩定；ROI 只是一條文字，速度足夠。
  session = await ort.InferenceSession.create(modelUrl, {
    executionProviders: ["wasm"],
    graphOptimizationLevel: "all",
  });
  backend = "wasm";
  ctx.postMessage({ type: "ready", backend } satisfies ReadyMsg);
}

/** ROI bitmap → 正規化的 Float32 張量 [1,3,48,320]，等比縮放 + 右側補邊。 */
function preprocess(bitmap: ImageBitmap): ort.Tensor {
  const scale = REC_H / bitmap.height;
  const drawW = Math.min(REC_W, Math.round(bitmap.width * scale));

  cctx.fillStyle = "#000";
  cctx.fillRect(0, 0, REC_W, REC_H);
  cctx.drawImage(bitmap, 0, 0, drawW, REC_H);
  bitmap.close();

  const { data } = cctx.getImageData(0, 0, REC_W, REC_H);
  const out = new Float32Array(3 * REC_H * REC_W);
  const plane = REC_H * REC_W;
  // NCHW；PP-OCR 正規化：(x/255 - 0.5) / 0.5
  for (let i = 0; i < plane; i++) {
    const r = data[i * 4] / 255;
    const g = data[i * 4 + 1] / 255;
    const b = data[i * 4 + 2] / 255;
    out[i] = (r - 0.5) / 0.5;
    out[plane + i] = (g - 0.5) / 0.5;
    out[2 * plane + i] = (b - 0.5) / 0.5;
  }
  return new ort.Tensor("float32", out, [1, 3, REC_H, REC_W]);
}

/** CTC 貪婪解碼：逐時間步取 argmax → 去重複 → 去 blank。回傳字串與平均信心。 */
function ctcDecode(logits: Float32Array, dims: readonly number[]): {
  text: string;
  confidence: number;
} {
  // dims = [1, T, C]
  const T = dims[1];
  const C = dims[2];
  let prev = -1;
  let chars = "";
  let confSum = 0;
  let confCount = 0;

  for (let t = 0; t < T; t++) {
    const base = t * C;
    // 找這個時間步的最大類別（注意：模型輸出可能已是 softmax 機率或 logits）
    let best = 0;
    let bestVal = logits[base];
    for (let c = 1; c < C; c++) {
      const v = logits[base + c];
      if (v > bestVal) {
        bestVal = v;
        best = c;
      }
    }
    // CTC：跳過 blank(0) 與「與上一步相同」的重複輸出
    if (best !== 0 && best !== prev) {
      chars += charset[best] ?? "";
      confSum += bestVal;
      confCount++;
    }
    prev = best;
  }
  // 若模型輸出是 logits 而非機率，bestVal 可能 >1；用 sigmoid 夾到 0~1 當近似信心。
  const raw = confCount > 0 ? confSum / confCount : 0;
  const confidence = raw > 1 || raw < 0 ? 1 / (1 + Math.exp(-raw)) : raw;
  return { text: chars, confidence };
}

async function infer(seq: number, bitmap: ImageBitmap): Promise<void> {
  if (!session) {
    ctx.postMessage({ type: "error", message: "session 尚未初始化" } satisfies ErrorMsg);
    bitmap.close();
    return;
  }
  const t0 = performance.now();
  const input = preprocess(bitmap);
  const feeds: Record<string, ort.Tensor> = {
    [session.inputNames[0]]: input,
  };
  const output = await session.run(feeds);
  const out = output[session.outputNames[0]];
  const { text, confidence } = ctcDecode(
    out.data as Float32Array,
    out.dims,
  );
  ctx.postMessage({
    type: "result",
    seq,
    text: text.toUpperCase(),
    confidence,
    ms: performance.now() - t0,
  } satisfies ResultMsg);
}

// 全域兜底：任何未捕捉的錯誤/拒絕都回報，不讓 worker 默默掛掉。
ctx.addEventListener("error", (e) => {
  ctx.postMessage({ type: "error", message: `worker error: ${e.message}` } satisfies ErrorMsg);
});
ctx.addEventListener("unhandledrejection", (e) => {
  const r = (e as PromiseRejectionEvent).reason;
  ctx.postMessage({
    type: "error",
    message: `unhandled: ${r instanceof Error ? r.message : String(r)}`,
  } satisfies ErrorMsg);
});

ctx.onmessage = async (e: MessageEvent<InMsg>) => {
  const msg = e.data;
  try {
    if (msg.type === "init") {
      await init(msg.modelUrl, msg.dictUrl);
    } else if (msg.type === "frame") {
      await infer(msg.seq, msg.bitmap);
    }
  } catch (err) {
    // 推論單幀失敗：關閉該幀 bitmap、回報，但不影響後續幀。
    if (msg.type === "frame") {
      try {
        msg.bitmap.close();
      } catch {
        /* 已關閉 */
      }
    }
    ctx.postMessage({
      type: "error",
      message: err instanceof Error ? err.message : String(err),
    } satisfies ErrorMsg);
  }
};
