# 卡匣 — Pokemon 卡片資產管理與神秘包決策系統

TCG 卡片的**資產管理 + 商業決策**平台：掃描建檔、即時市值、把滯銷庫存最佳化打包成鎖定毛利的神秘包。

## 架構

```
ptcg/
├── backend/          FastAPI + PostgreSQL + Redis（API、估價、神秘包演算法、PDF）
├── webapp/           React + Vite PWA（網頁先行，WebGPU 即時掃描）
└── frontend/         Flutter 設計 token（原生 App 預留，AppTheme）
```

- **後端 API 三端共用**：webapp 與未來原生 App 打同一組 API。
- **網頁先行**：除高效串流掃描外，所有功能網頁皆可達；掃描以 WebGPU 跑 ONNX 辨識模型。

## 後端 backend/

| 模組 | 檔案 |
|------|------|
| 掃描解析（正則 + pg_trgm/Levenshtein 雙軌模糊比對） | `app/services/parser.py`, `app/api/v1/parser.py` |
| 分層估價（VWMA / 中位數 / 散卡底價 + 流動性折價） | `app/services/valuation.py` |
| 神秘包最佳化（MCKP 近似：分層貪婪 + 流動性折價） | `app/services/optimizer.py` |
| 神秘包 API + PDF 出貨單 | `app/api/v1/packs.py`, `app/services/pdf.py` |
| 儀表板 / 庫存 / 卡片詳情 | `app/api/v1/portfolio.py`, `app/api/v1/cards.py` |

### 端點

```
POST   /api/v1/parser/scan                       OCR 字串 → 卡片檔案 + 市值
POST   /api/v1/packs/optimize                    產生神秘包策略（持久化計畫）
GET    /api/v1/packs/{plan_id}/packing-list.pdf  下載出貨單 PDF
GET    /api/v1/portfolio/summary                 儀表板彙總
GET    /api/v1/inventory                          庫存清單
PATCH  /api/v1/inventory/{card_id}                更新數量/最愛/神秘包資格
GET    /api/v1/cards/{card_id}                    卡片詳情 + 歷史價格
GET    /health
```

### 啟動

```bash
cd backend
python -m pip install -r requirements.txt
psql "$DATABASE_URL" -f migrations/001_schema.sql      # 含 pg_trgm/fuzzystrmatch/pgcrypto 擴充
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/ptcg
export REDIS_URL=redis://localhost:6379/0
uvicorn app.main:app --reload                          # http://localhost:8000/docs
```

## 網頁 webapp/

| 畫面 | 檔案 |
|------|------|
| 儀表板（淨值 Hero、Sparkline、統計四宮格、今日波動） | `src/screens/DashboardScreen.tsx` |
| 庫存清單（搜尋/最愛篩選） | `src/screens/InventoryScreen.tsx` |
| 卡片詳情（估值矩陣、ECharts 趨勢、數量器、資格開關） | `src/screens/CardDetailScreen.tsx` |
| 神秘包決策（參數、健康環、三層獎池、匯出 PDF） | `src/screens/MysteryPackScreen.tsx` |
| 即時掃描（WebGPU OCR、HUD、模糊候選抽屜） | `src/scan/ScanScreen.tsx` |

掃描管線：`getUserMedia → 幀節流 → 背壓鎖 → ROI 裁底部15% → OCR Worker(ONNX/WebGPU) → 信心投票`。

### 啟動

```bash
cd webapp
npm install
# 放入 OCR 模型：見 public/models/README.md
npm run dev        # http://localhost:5173（已設 /api proxy 到 :8000）
npm run build      # 產出 PWA（含 Service Worker 離線快取）
```

## 已驗證

- 後端：全模組 `py_compile` 通過；optimizer → serialize → PDF 端到端產出有效 `%PDF-`；8 端點 OpenAPI 註冊。
- 前端：`tsc` 型別 0 錯；`vite build` 成功；路由 lazy 切分，首屏 ~61KB gzip。

## 待辦

- OCR 模型檔（PP-OCRv4 rec onnx + 字典）— 見 `webapp/public/models/README.md`。
- 登入 / 多租戶（目前用 demo user）。
- 實機驗證 WebGPU 掃描 fps 與耗電（Android / iOS 18+）。
- Flutter 原生 App（共用 `frontend/lib/theme/app_theme.dart`）。
