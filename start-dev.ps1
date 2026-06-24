# 一鍵啟動 + 看門狗（固定網址版，Tailscale Funnel）。
# 用法：在專案根目錄執行  ./start-dev.ps1   （視窗保持開啟＝持續自動監控／重啟）
#
#   PostgreSQL : 127.0.0.1:55432 (docker)  user=ptcg pass=0907 db=ptcg
#   Redis      : 127.0.0.1:6380  (docker)  pass=0907
#   後端 API   : http://127.0.0.1:8000
#   前端 PWA   : http://127.0.0.1:4173 （正式 build + preview）
#   固定網址   : https://ray.tail0a17b9.ts.net   ← 永不改變（Tailscale Funnel → :4173）
#   手機入口   : https://ray319129.github.io/ptcg/ （docs/url.txt 永久指向上面網址）

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot

# 單例：避免多個看門狗實例互打（重複啟動時直接結束新的）。
$mutex = New-Object System.Threading.Mutex($false, "Global\PTCG-AutoStart-Watchdog")
if (-not $mutex.WaitOne(0)) {
  Write-Host "已有一個 start-dev 看門狗在執行，結束本實例。" -ForegroundColor DarkYellow
  return
}
$ts = "C:\Program Files\Tailscale\tailscale.exe"
$FUNNEL_URL = "https://ray.tail0a17b9.ts.net"
$env:DATABASE_URL = "postgresql+asyncpg://ptcg:0907@127.0.0.1:55432/ptcg"
$env:REDIS_URL = "redis://:0907@127.0.0.1:6380/0"
# uvicorn 等套件裝在使用者 site-packages；排程工作的精簡環境不一定會載入，
# 明確加進 PYTHONPATH，確保看門狗重啟後端時一定找得到。
$env:PYTHONPATH = "C:\Users\Ray\AppData\Roaming\Python\Python314\site-packages"

function Test-Port([int]$port) {
  try {
    $c = New-Object Net.Sockets.TcpClient
    $c.Connect("127.0.0.1", $port); $c.Close(); return $true
  } catch { return $false }
}

function Test-DbHealthy {
  return ((docker inspect --format '{{.State.Health.Status}}' ptcg-db 2>$null) -eq 'healthy')
}

function Ensure-Docker {
  docker info *> $null
  if ($LASTEXITCODE -ne 0) {
    $dd = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) {
      Write-Host "  Docker 引擎未啟動 → 啟動 Docker Desktop…" -ForegroundColor Yellow
      Start-Process $dd
      for ($i = 0; $i -lt 30; $i++) { Start-Sleep 4; docker info *> $null; if ($LASTEXITCODE -eq 0) { break } }
    }
  }
  if (-not (Test-DbHealthy)) {
    docker compose -f "$root/docker-compose.yml" up -d *> $null
  }
}

function Ensure-Backend {
  if (Test-Port 8000) { return }
  Write-Host "  (重)啟動後端 :8000" -ForegroundColor Yellow
  Start-Process -FilePath "C:\Python314\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning" `
    -WorkingDirectory "$root/backend" `
    -RedirectStandardOutput "$root/backend/uvicorn.out.log" `
    -RedirectStandardError "$root/backend/uvicorn.err.log" -WindowStyle Hidden
}

function Ensure-Preview {
  if (Test-Port 4173) { return }
  Write-Host "  (重)啟動前端預覽 :4173" -ForegroundColor Yellow
  Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npx vite preview --port 4173 --host 0.0.0.0 > preview.out.log 2>&1" `
    -WorkingDirectory "$root/webapp" -WindowStyle Hidden
}

function Ensure-Funnel {
  $st = (& $ts funnel status 2>&1 | Out-String)
  if ($st -notmatch "4173") {
    Write-Host "  (重)啟動 Tailscale Funnel → :4173" -ForegroundColor Yellow
    & $ts funnel --bg 4173 *> $null
  }
}

Write-Host "[1/4] Docker (Postgres + Redis)…" -ForegroundColor Cyan
Ensure-Docker
for ($i = 0; $i -lt 24; $i++) { if (Test-DbHealthy) { Write-Host "  DB healthy"; break }; Start-Sleep 5 }

Write-Host "[2/4] 建置前端正式檔…" -ForegroundColor Cyan
Push-Location "$root/webapp"; npm run build; Pop-Location

Write-Host "[3/4] 啟動服務（後端 / 預覽 / Funnel）…" -ForegroundColor Cyan
Ensure-Backend; Ensure-Preview; Ensure-Funnel

Write-Host ""
Write-Host "✅ 已啟動。固定網址：$FUNNEL_URL" -ForegroundColor Green
Write-Host "   手機固定入口：https://ray319129.github.io/ptcg/" -ForegroundColor Green
Write-Host "   電腦：前端 http://127.0.0.1:4173 ｜ 後端 http://127.0.0.1:8000/docs"
Write-Host "   看門狗運行中：每 15 秒檢查，任何服務掛掉自動重啟。" -ForegroundColor DarkGray
Write-Host "   （關閉此視窗只會停止『自動監控』，背景服務仍在；要全停請關各服務或登出。）" -ForegroundColor DarkGray

while ($true) {
  Start-Sleep -Seconds 15
  Ensure-Docker
  Ensure-Backend
  Ensure-Preview
  Ensure-Funnel
}
