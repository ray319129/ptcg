# 卡匣 PTCG — 交接文件（接手必讀）

> Pokemon 卡片資產管理 + 神秘包決策 App。後端 FastAPI + Postgres + Redis，前端 React PWA。
> 使用者：Ray（ray319129@gmail.com）。全程用**繁體中文**回覆。

## ⭐ 首要待辦（使用者最新需求）
（目前無待辦。下一步看使用者需求。）

## 🟢 服務啟動狀態（背景執行中，關機後用 `./start-dev.ps1` 重啟）
| 服務 | 位置 | 備註 |
|---|---|---|
| PostgreSQL | docker `ptcg-db` `127.0.0.1:55432` | user=ptcg pass=**0907** db=ptcg |
| Redis | docker `ptcg-redis` `127.0.0.1:6380` | pass=**0907** |
| 後端 uvicorn | `127.0.0.1:8000` | env: `DATABASE_URL=postgresql+asyncpg://ptcg:0907@127.0.0.1:55432/ptcg` `REDIS_URL=redis://:0907@127.0.0.1:6380/0` |
| 前端 | **正式 build + `vite preview` :4173**（非 dev！見下方雷區） | `cd webapp; npx vite build; npx vite preview --port 4173 --host 0.0.0.0` |
| Cloudflare tunnel | → localhost:4173 | `./tools/cloudflared.exe tunnel --url http://localhost:4173`，網址每次變 |
| 固定入口 | **https://ray319129.github.io/ptcg/** | 讀 `docs/url.txt` 跳轉當前 tunnel |

啟動後端指令範例：`cd backend && export DATABASE_URL=... REDIS_URL=... && nohup python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning > /tmp/uvicorn.log 2>&1 &`

## 📦 資料現況
- `cards` 1631 張（13 個 2025+ 擴充包，來源 tw_official + cardpaipai M5特卡）。1629 有卡圖、1609 有雙語價。
- **雙語價**：`price_jp`(日文版) / `price_tw`(繁中版)，差異大（如達克萊伊ex MUR 日33500/繁3300）。端點吃 `lang=tw|jp`，預設 tw。`app/pricing.py` 的 `price_expr(lang,alias)` 是核心。
- `users`、`user_inventory` 目前**全空**（使用者要自己註冊用）。**不要再亂清資料**。
- 缺圖：`M5_116/081`、`M5_118/081`（milongja 也沒有，不可掃）。

## ✅ 已完成功能
1. **影像比對掃描**（取代 OCR）：MobileNetV2 1280維 embedding，後端比對 1629 張卡圖索引（`backend/models/card_index.npz`）。OpenCV 自動偵測卡片矩形+透視校正。模擬命中率 Top1 92%。
2. **連續自動偵測**：卡片放上去**定時(~1.2s)自動辨識**，不需按拍攝、不需靜止（閃卡反光也行）。結果可選數量收藏 / 看其他候選 / 都不是重掃。掃描器不停。
3. **雙語卡價** + 掃描頁左上「繁中/日文」切換（存 localStorage，全 app 生效）。
4. **帳號系統**：註冊/登入（`/api/v1/auth/register|login`，pbkdf2雜湊），資料綁帳號保存。前端未登入顯示 `AuthScreen`。
5. **CSV 匯出**：庫存頁「⬇匯出CSV」→ `/api/v1/inventory/export.csv?user_id=&lang=`。
6. **神秘包**：`/api/v1/packs/optimize`（分層貪婪+流動性折價+**保底稀有度**guaranteed_rarity）+ PDF 出貨單。
7. **GitHub**：程式碼已推 https://github.com/ray319129/ptcg（main）。Pages 已啟用(/docs)。`start-dev.ps1` 每次啟動自動 push 新 tunnel 網址到 `docs/url.txt`。
8. **手動搜尋加入庫存**：`GET /api/v1/cards/search?q=&user_id=&lang=&limit=`（`backend/app/api/v1/cards.py`，**宣告在 `/{card_id:path}` 之前**，否則 search 會被當 card_id）；卡名/卡號/set_code ILIKE 比對、回傳該語言價+image_url+owned_qty。前端新頁 `webapp/src/screens/CardSearchScreen.tsx`（路由 `/search`），庫存頁右上「＋ 加入卡片」進入：搜尋框(350ms 防抖)→結果列表(縮圖+名+價+持有數)→點卡展開數量器→`加入庫存`呼叫既有 `addInventory`。已驗證 search/add/persist OK。

## 🗂️ 關鍵檔案
- 後端 API：`backend/app/api/v1/`（match.py=掃描比對, cards.py, portfolio.py=儀表板/庫存/CSV, packs.py, auth.py, parser.py=舊OCR已不用）
- 影像比對引擎：`backend/app/services/image_match.py`（embed/detect_card/match/build_index）
- 神秘包：`backend/app/services/optimizer.py`
- 價格語言：`backend/app/pricing.py`
- 抓取腳本：`backend/ingest/`（tw_official.py=官網卡+圖, cardpaipai_price.py=雙語價, cardpaipai_cards.py=補特卡, milongja_images.py=M5補圖, image_match --build=建索引）
- 前端：`webapp/src/scan/ScanScreen.tsx`（連續掃描）, `webapp/src/screens/`（Dashboard/Inventory/CardDetail/MysteryPack/Auth）, `webapp/src/store.ts`（userId/username/priceLang/login/logout）, `webapp/src/api/endpoints.ts`（所有 API）
- migrations：`backend/migrations/001~007`（007=users, 006=雙語價）

## ⚠️ 雷區（踩過的坑，務必注意）
1. **前端一定要用 build+preview，不能用 `npm run dev`**：dev 模式 Vite 會即時轉換 onnxruntime-web 導致 wasm 載入 500。`vite.config.ts` 已設 `optimizeDeps.exclude:['onnxruntime-web']` + ORT wasm 放在 `webapp/public/ort/`（`ort.env.wasm.wasmPaths='/ort/'`）。改前端後要**重新 build** 才生效。
2. **重建後 Service Worker 會服務舊 chunk**→空白頁。已設 skipWaiting/clientsClaim/cleanupOutdatedCaches，但測試時若空白：清 SW + 強制重整。MCP preview server 會「快照」舊 build，測試要 kill 舊 port 重開。
3. **tunnel 常掉**：用 `&`/nohup 啟動的會被清。掉了就重啟 cloudflared，網址會變（固定頁面會自動更新）。
4. **MCP Preview 工具**：`vite.config.ts` 已讓 server/preview 讀 `process.env.PORT`（autoPort 用）。`.claude/launch.json` 有 `webapp`(dev) 和 `webapp-prod`(preview, autoPort) 兩個設定。測掃描要用 webapp-prod，且要 kill 舊的 preview 進程才會服務新 build。瀏覽器測掃描可注入假相機：`navigator.mediaDevices.getUserMedia=async()=>canvas.captureStream()`，HashRouter 設 `location.hash='#/scan'` 不重載可保留覆寫。
5. **Bash 雷**：`UID` 是唯讀變數別當變數名用。終端是 cp950，印中文會 mojibake（資料本身是對的 UTF-8，別被嚇到）；要看中文寫檔再 Read。docker exec heredoc 有時無效，用 `-c` 個別指令。`/tmp` 跨呼叫會被清，存檔用專案路徑。
6. **Python 3.14 / Windows**：路徑用 Windows 格式給 onnxruntime。已裝：fastapi/sqlalchemy/asyncpg/redis/reportlab/pillow/numpy/onnx/onnxruntime/opencv-python-headless/python-multipart。
7. **git push 認證**：用 Windows 憑證管理員，已可 push。`git credential fill` 可取 token（曾用來呼叫 API 啟用 Pages）。

## 掃描可調參數（使用者可能要調靈敏度）
`webapp/src/scan/ScanScreen.tsx` 頂部：`MATCH_INTERVAL`(1200ms 觸發間隔)、`MIN_VARIANCE`(230 空畫面門檻)、`SAME_CARD_DIFF`(10 同卡判定)。後端 `app/api/v1/match.py` 的 `MIN_SIM`(0.70) 與前端 doMatch 的顯示門檻(0.5)。
