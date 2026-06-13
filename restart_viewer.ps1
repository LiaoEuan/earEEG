# 只重启 viewer（模拟设备和 lsl_proxy 保持运行）
# 用法：.\restart_viewer.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "重启 viewer..." -ForegroundColor Yellow

# 杀掉旧 viewer
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "upper_machine.eeg_viewer.main"
} | Stop-Process -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 1

# 启动新 viewer
Start-Process -FilePath "python" -ArgumentList "-m", "upper_machine.eeg_viewer.main", "--host", "127.0.0.1", "--port", "8765", "--proxy-url", "http://127.0.0.1:8787" -WorkingDirectory $root -WindowStyle Normal

Write-Host "viewer 已重启。刷新浏览器: http://127.0.0.1:8765" -ForegroundColor Green
