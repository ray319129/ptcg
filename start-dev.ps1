# 一鍵啟動本機開發環境（Windows PowerShell）。
# 用法： 在專案根目錄執行  ./start-dev.ps1
#
# 連線設定（避開主機既有的 PostgreSQL 17/18 與 Redis，故用非預設埠）：
#   PostgreSQL : 127.0.0.1:55432  (docker)  user=ptcg pass=0907 db=ptcg
#   Redis      : 127.0.0.1:6380   (docker)  pass=0907
#   後端 API   : http://127.0.0.1:8000   (/docs 有 Swagger)
#   前端 PWA   : http://127.0.0.1:5173

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "[1/4] 啟動 Docker 基礎設施 (Postgres + Redis)..." -ForegroundColor Cyan
docker compose -f "$root/docker-compose.yml" up -d

Write-Host "[2/4] 等待資料庫健康檢查..." -ForegroundColor Cyan
for ($i = 0; $i -lt 24; $i++) {
  $s = (docker inspect --format '{{.State.Health.Status}}' ptcg-db 2>$null)
  if ($s -eq "healthy") { Write-Host "  DB healthy"; break }
  Start-Sleep -Seconds 5
}

# 後端連線環境變數
$env:DATABASE_URL = "postgresql+asyncpg://ptcg:0907@127.0.0.1:55432/ptcg"
$env:REDIS_URL = "redis://:0907@127.0.0.1:6380/0"

Write-Host "[3/4] 啟動後端 FastAPI (:8000)..." -ForegroundColor Cyan
Start-Process -WindowStyle Minimized powershell -ArgumentList @(
  "-NoExit", "-Command",
  "`$env:DATABASE_URL='$($env:DATABASE_URL)'; `$env:REDIS_URL='$($env:REDIS_URL)'; " +
  "cd '$root/backend'; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
)

# 前端：OCR 的 wasm 在 dev 模式無法載入（Vite 會轉換 ORT 動態 import），
# 故用「build + 靜態 preview」服務正式檔。改程式碼後需重跑本腳本（或 npm run build）。
Write-Host "[4/5] 建置並啟動前端正式預覽 (:4173)..." -ForegroundColor Cyan
Push-Location "$root/webapp"; npm run build; Pop-Location
Start-Process -WindowStyle Minimized powershell -ArgumentList @(
  "-NoExit", "-Command", "cd '$root/webapp'; npx vite preview --port 4173 --host 0.0.0.0"
)

Write-Host "[5/5] 啟動 Cloudflare Tunnel 並發布固定網址..." -ForegroundColor Cyan
# quick tunnel 每次網址會變；啟動後抓出網址 → 寫入 docs/url.txt → push 到 GitHub，
# 讓固定頁面 https://ray319129.github.io/ptcg/ 永遠跳轉到當前網址。
$cfLog = Join-Path $env:TEMP "ptcg_cf.log"
if (Test-Path $cfLog) { Remove-Item $cfLog -Force }
Start-Process -WindowStyle Minimized powershell -ArgumentList @(
  "-NoExit", "-Command",
  "& '$root/tools/cloudflared.exe' tunnel --url http://localhost:4173 --no-autoupdate *> '$cfLog'"
)

# 等待並擷取網址
$tunnelUrl = $null
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  if (Test-Path $cfLog) {
    $m = Select-String -Path $cfLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($m) { $tunnelUrl = $m.Matches[0].Value; break }
  }
}

if ($tunnelUrl) {
  Set-Content -Path "$root/docs/url.txt" -Value $tunnelUrl -Encoding utf8 -NoNewline
  Write-Host "   目前網址: $tunnelUrl" -ForegroundColor Yellow
  # 推到 GitHub（更新固定頁面）。失敗不中斷。
  Push-Location $root
  try {
    git add docs/url.txt 2>$null
    git commit -m "update tunnel url" 2>$null
    git push 2>$null
    Write-Host "   已更新固定頁面 https://ray319129.github.io/ptcg/" -ForegroundColor Green
  } catch { Write-Host "   （push 失敗，請確認 git 已設定認證）" -ForegroundColor DarkYellow }
  Pop-Location
} else {
  Write-Host "   （未取得 tunnel 網址，請看最小化的 cloudflared 視窗）" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "✅ 已啟動：" -ForegroundColor Green
Write-Host "   電腦   前端 http://127.0.0.1:4173 ｜ 後端 http://127.0.0.1:8000/docs"
Write-Host "   手機   固定入口 https://ray319129.github.io/ptcg/ （永遠跳轉到當前網址）"
