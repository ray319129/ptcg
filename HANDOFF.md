# 卡匣 PTCG — 交接文件（接手必讀）

> Pokemon 卡片資產管理 + 神秘包決策 App。後端 FastAPI + Postgres + Redis，前端 React PWA。
> 使用者：Ray（ray319129@gmail.com）。全程用**繁體中文**回覆。
> 程式碼：https://github.com/ray319129/ptcg （main）。

## ⭐ 首要待辦
目前無指定待辦。使用者開放討論「下一步優化」，候選見最後一節「改善 backlog」。

## 🟢 服務啟動 / 固定網址（重要）
| 服務 | 位置 | 備註 |
|---|---|---|
| PostgreSQL | docker `ptcg-db` `127.0.0.1:55432` | user=ptcg pass=**0907** db=ptcg |
| Redis | docker `ptcg-redis` `127.0.0.1:6380` | pass=**0907** |
| 後端 uvicorn | `127.0.0.1:8000` | 見下方啟動指令（**要帶 PYTHONPATH**） |
| 前端 | 正式 build + `vite preview` **:4173**（非 dev！見雷區1） | `cd webapp; npx vite build; npx vite preview --port 4173 --host 0.0.0.0` |
| **固定公開網址** | **`https://ray.tail0a17b9.ts.net`** | **Tailscale Funnel → :4173，永久不變**（取代舊的 Cloudflare 臨時通道） |
| 手機固定入口 | **`https://ray319129.github.io/ptcg/`** | 讀 `docs/url.txt`（已永久指向上面 funnel，不用再改） |

- **一鍵啟動 + 看門狗**：`./start-dev.ps1`（已改寫）。會確保 Docker/後端/前端/Funnel 都在線，並每 15 秒自動重啟掛掉的服務。有單例 mutex。**在一般終端機跑這個最可靠**（互動環境下 Python 能正確載入套件）。
- **開機自動執行**：已註冊排程工作 `PTCG-AutoStart`（登入時跑 start-dev.ps1，單例）。⚠️ 見雷區8——排程環境的 PYTHONPATH 問題，**重開機後請驗證網站還在**。
- **Tailscale Funnel**：`& "C:\Program Files\Tailscale\tailscale.exe" funnel --bg 4173`。Funnel 設定跨重開機保留（Tailscale 服務開機自啟並還原）。機器名 `ray`，tailnet `tail0a17b9.ts.net`。
- **手動啟動後端（PowerShell，務必帶 PYTHONPATH）**：
  ```powershell
  $env:DATABASE_URL="postgresql+asyncpg://ptcg:0907@127.0.0.1:55432/ptcg"
  $env:REDIS_URL="redis://:0907@127.0.0.1:6380/0"
  $env:PYTHONPATH="C:\Users\Ray\AppData\Roaming\Python\Python314\site-packages"
  Start-Process -FilePath "C:\Python314\python.exe" -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000","--log-level","warning" -WorkingDirectory "...\backend" -RedirectStandardOutput "...\backend\uvicorn.out.log" -RedirectStandardError "...\backend\uvicorn.err.log" -WindowStyle Hidden
  ```

## 📦 資料現況
- `cards` 1631 張（M1L/M1S/M2/M2A/M3/M4/M5/MJ 繁中系列 + SV9/SV9A/SV10/SV11B/SV11W）。
- **雙語價** `price_jp`/`price_tw`，端點吃 `lang=tw|jp`（預設 tw）；核心 `app/pricing.py` 的 `price_expr(lang,alias)`。
- **`card_type` 欄位（本 session 新增，migration 008）**：Pokemon 1346 / Supporter 146 / Item 71 / Stadium 31 / Tool 20 / Energy 17。由 `python -m ingest.card_types` 從官方詳情頁回填（判 `evolveMarker`→Pokemon、`支援者卡`→Supporter…）。**資料在 DB volume，不進 git**；新環境要重跑。
- **同圖不同版很普遍**：M2A 大量重收 SV 系列的圖（互比 1629 張，~97% 有同圖雙胞胎、卡號/稀有度/價不同）。AR/SAR 全圖多為獨佔圖。
- 測試帳號 `browsertest`（user_id `b616f823-7dee-4e5d-819e-31e4013d2aaa`）有手動 seed 的測試庫存（ex/Supporter/普卡）。**勿亂清真實使用者資料**。
- 缺圖：`M5_116/081`、`M5_118/081`。

## ✅ 已完成功能（本 session 大更新）
1. **影像辨識掃描**：**SIFT 局部特徵 + CLAHE + FLANN 投票 + RANSAC 幾何驗證**（`backend/app/services/sift_match.py`，索引 `models/sift_index.npz` 326MB **不進 git**，建：`python -m app.services.sift_match --build`）。真實照片 Top-1 由舊 MobileNet 的 13%→**100%**、空畫面 0 假陽性。評測：`backend/eval_match.py` + `backend/_samples/`（照片 gitignore、manifest.csv 有標卡號）。`detect_card`（在 `image_match.py`）負責定位+透視校正；舊 MobileNet embedding 程式保留但已不用。
   - **同圖不同版**：`identify()` 回 `(candidates, detected, status)`，status=`confident`/`pick`/`none`。內點數打平→`pick`（版本群），先試讀左下角卡號 ROI 自動定版（弱，多半退回選擇器），不行就 `needs_pick=True` 讓前端跳「版本選擇器」。門檻在檔頂：`MIN_INLIERS`(12)、`GROUP_RATIO`(0.62)、`ROI_*`。
2. **連續自動偵測**：放上去定時自動辨識。`ScanScreen.tsx`：`resp.success`→直接跳結果；`resp.needs_pick`→跳結果並自動展開候選清單選版本。
3. **庫存頁強化**：每卡縮圖、清單↔圖卡切換、排序(價值/名/量/稀有度/系列)、分組(系列/稀有度)、多選批次(最愛/神秘包資格/刪除)、一鍵清空。端點 `/inventory/bulk`、`/inventory/clear`；`InventoryItem` 加 `image_url`。
4. **手動搜尋加入庫存**：`GET /api/v1/cards/search`（**宣告在 `/{card_id:path}` 之前**）；前端 `CardSearchScreen.tsx`（路由 `/search`，庫存頁「＋加入卡片」進入）。
5. **價格波動全砍**：移除儀表板 24h漲跌/趨勢線/暴漲清單 + 卡片詳情走勢圖與 7d均/高/低矩陣；只留目前市值/總資產。後端 summary、cards detail、schema 都精簡了；卡片詳情 chunk 由 1MB→2.5KB（拿掉 echarts import）。
6. **神秘包策略升級**（對齊賣家賣法，`optimizer.py`）：
   - 既有 `guaranteed_rarity` 保底稀有度。
   - **類別保底** `guaranteed_categories`：`ex` / `mega`(超級進化) / `full_art_supporter`(全圖人物=SR以上的 Supporter)。類別由 `card_categories()` 從名稱/牌種/稀有度推導。
   - **招牌頭獎** `chase_card_ids` 或 `auto_chase_count`（自動取最高價 N 張，一包一張優先灑）。
   - **回本率** `payback_ratio`(期望值/售價) 顯示。
   - 前端 `MysteryPackScreen.tsx` 加類別 chips + 招牌張數 + 回本率指標。
7. **雙語卡價** + 掃描頁「繁中/日文」切換（localStorage 全 app）。**帳號系統**（register/login pbkdf2）。**CSV 匯出**。**神秘包 PDF 出貨單**。

## 🗂️ 關鍵檔案
- 後端 API：`backend/app/api/v1/`（match.py=SIFT掃描, cards.py=詳情+search, portfolio.py=儀表板/庫存/CSV/bulk/clear, packs.py, auth.py）
- 辨識引擎：`backend/app/services/sift_match.py`（識別+版本群+ROI定版）、`image_match.py`（detect_card 仍用）
- 神秘包：`backend/app/services/optimizer.py`、`packs_repo.py`、`schemas/packs.py`
- 牌種回填：`backend/ingest/card_types.py`
- 前端：`webapp/src/scan/ScanScreen.tsx`、`webapp/src/screens/`（Dashboard/Inventory/CardSearch/CardDetail/MysteryPack/Auth）、`webapp/src/api/endpoints.ts`
- migrations：`backend/migrations/001~008`（007=users, 006=雙語價, **008=card_type**）
- 部署：`start-dev.ps1`（看門狗）、`docs/url.txt`(固定 funnel 網址)、`docs/index.html`(跳轉頁)

## ⚠️ 雷區
1. **前端用 build+preview，不可 `npm run dev`**（dev 模式 ORT wasm 載入 500）。改前端要重新 build。
2. **重建後 SW 服務舊 chunk → 空白頁**：清 SW + 強制重整。MCP preview 會快照舊 build，要 kill 舊 port 重開。
3. **後端用 `&`/nohup 背景啟動會被清掉**（本 session 死好幾次）。用 PowerShell `Start-Process`（見上方指令）或 `start-dev.ps1` 看門狗。
4. **Bash 雷**：`UID` 唯讀別當變數；終端 cp950 印中文 mojibake（資料是對的 UTF-8）；`/tmp` 跨呼叫會清，存專案路徑。`gh` CLI 在 Bash 不在 PATH（用 PowerShell 或 curl+token）。
5. **Python 3.14 / Windows**：套件裝在**使用者 site-packages** `C:\Users\Ray\AppData\Roaming\Python\Python314\site-packages`。已裝：fastapi/sqlalchemy/asyncpg/redis/reportlab/pillow/numpy/onnx/onnxruntime/opencv-python-headless/python-multipart。
6. **PowerShell 5.1**：寫 .ps1 要存 **UTF-8 with BOM**（否則中文亂碼導致解析錯）；native 指令別 `2>&1`（會誤判失敗）；複合指令常回 exit 255（多為非終止錯誤，動作其實有做，用單一簡單指令查狀態）。
7. **Docker Desktop inference-manager bug**：本 session Docker 自停且重啟卡在 `dockerInference` socket 壞掉。引擎起不來就「完全結束 Docker Desktop → 重開」或重開機（資料在 volume 不會掉）。
8. **⭐排程自動啟動的 PYTHONPATH 問題（未完全驗證）**：排程工作啟動的 Python **不載入使用者 site-packages** → `No module named uvicorn`。已 (a) 在 `start-dev.ps1` 設 `$env:PYTHONPATH`、(b) 設了「永久 USER 環境變數 PYTHONPATH」（`[Environment]::SetEnvironmentVariable(...,"User")`，**下次登入/重開機才生效**）。**手動跑 start-dev.ps1 的看門狗正常**；開機自動那條未經重開機驗證。若重開機後後端沒起來：手動跑一次 `start-dev.ps1` 即可。根治方案：改用專案內 **venv**（見 backlog）。
9. **GitHub Pages 部署偶爾 timeout 變紅**：本 session 出現過，但 `docs/url.txt` 內容其實已發布成功（github.io 跳轉正常）。因固定網址後 `url.txt` 永不再改，這個紅 X 無害可忽略。使用者尚未決定要不要 re-run/關閉 Pages。

## 掃描可調參數
- 後端 `sift_match.py` 頂部：`MIN_INLIERS`(12 採信下限)、`GROUP_RATIO`(0.62 同圖群)、`RATIO`/`SHORTLIST`/`ROI_*`。
- 前端 `ScanScreen.tsx`：`MATCH_INTERVAL`(1200)、`MIN_VARIANCE`(230)、`SAME_CARD_DIFF`(10)。

## 🔧 改善 backlog（已和使用者討論、未做）
- **A. 環境韌性根治**：把後端依賴裝進專案 venv，排程自動啟動就不依賴使用者 site-packages（最徹底）。
- **B. 掃描**：多幀共識（連續幾幀同卡才採信→可降門檻、更快鎖定）；上傳前 Laplacian 糊度過濾；真正的數字 OCR 讀卡號做同圖定版（目前 ROI 比對弱，多半要手選）。
- **C. 神秘包**：機率抽獎級距（保底SR+機會抽SAR）；手動指定招牌卡 picker；建議售價反推。
- **D. 清理**：移除已不用的 MobileNet embedding + `card_index.npz` + 可能的 onnxruntime 依賴；`webapp/src/api/client.ts` 是舊 OCR 死碼可刪。
