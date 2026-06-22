import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// PWA 設定：離線可用、把 OCR 模型(onnx) 與 wasm 預快取，避免每次重抓。
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/*.png"],
      workbox: {
        // 只「預」快取 app 殼層（js/css/html）。大型資源（wasm/模型/卡圖）改用
        // runtime 快取——首次用到才下載並快取，避免安裝時硬塞 800MB+。
        globPatterns: ["**/*.{js,css,html,svg}"],
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        // 新版立即接管並清除舊版快取，避免重建後參照到已不存在的舊 chunk。
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        // 導覽一律回退到最新 index（避免拿到舊 index 參照舊 chunk hash）。
        navigateFallback: "/index.html",
        runtimeCaching: [
          {
            // OCR wasm：首次下載後永久快取（檔名含版本，內容不變）
            urlPattern: ({ url }) => url.pathname.startsWith("/ort/"),
            handler: "CacheFirst",
            options: {
              cacheName: "ort-wasm",
              expiration: { maxEntries: 8 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // OCR 模型 + 字典
            urlPattern: ({ url }) => url.pathname.startsWith("/models/"),
            handler: "CacheFirst",
            options: {
              cacheName: "ocr-models",
              expiration: { maxEntries: 4 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // 卡圖：用到才快取
            urlPattern: ({ url }) => url.pathname.startsWith("/img/"),
            handler: "StaleWhileRevalidate",
            options: {
              cacheName: "card-images",
              expiration: { maxEntries: 3000 },
            },
          },
        ],
      },
      manifest: {
        name: "卡匣 — Pokemon 卡片資產管理",
        short_name: "卡匣",
        theme_color: "#121214",
        background_color: "#121214",
        display: "standalone",
        orientation: "portrait",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
    }),
  ],
  // 註：OCR 用單執行緒 asyncify wasm + WebGPU，兩者皆不需 SharedArrayBuffer / 跨來源隔離，
  // 故不再設 COOP/COEP（也免去跨來源圖片的 CORP 限制）。
  // dev server（HMR，但 dev 模式下 Vite 會即時轉換 ORT 的動態 import 而無法載入 OCR wasm，
  // 故實際使用請走 `npm run build && npm run preview`）。
  server: {
    port: process.env.PORT ? Number(process.env.PORT) : 5173,
    host: true,
    allowedHosts: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  // 正式預覽：服務 dist/ 靜態檔（不轉換 .mjs，ORT 從 /ort/ 正常載入），並代理 /api。
  preview: {
    port: process.env.PORT ? Number(process.env.PORT) : 4173,
    host: true,
    allowedHosts: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  worker: { format: "es" },
  optimizeDeps: { exclude: ["onnxruntime-web"] },
});
