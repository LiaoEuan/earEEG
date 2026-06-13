# earEEG 一键启动脚本
# 启动：模拟设备 + lsl_proxy + viewer
# 用法：.\start_all.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== earEEG 一键启动 ===" -ForegroundColor Cyan

# 启动模拟设备
Write-Host "[1/3] 启动模拟设备..." -ForegroundColor Yellow
$sim = Start-Process -FilePath "python" -ArgumentList "-m", "ear_eeg_sound_lab.src.simulated_device", "--auto-start", "--eeg-profile", "focused", "--mic-mode", "chirp" -WorkingDirectory $root -PassThru -WindowStyle Normal
Write-Host "  PID: $($sim.Id)" -ForegroundColor Gray

Start-Sleep -Seconds 2

# 启动 lsl_proxy
Write-Host "[2/3] 启动 lsl_proxy..." -ForegroundColor Yellow
$proxy = Start-Process -FilePath "python" -ArgumentList "-m", "upper_machine.lsl_proxy.main", "--host", "127.0.0.1", "--port", "8889", "--lsl", "--start", "--stats" -WorkingDirectory $root -PassThru -WindowStyle Normal
Write-Host "  PID: $($proxy.Id)" -ForegroundColor Gray

Start-Sleep -Seconds 2

# 启动 viewer
Write-Host "[3/3] 启动 viewer..." -ForegroundColor Yellow
$viewer = Start-Process -FilePath "python" -ArgumentList "-m", "upper_machine.eeg_viewer.main", "--host", "127.0.0.1", "--port", "8765", "--proxy-url", "http://127.0.0.1:8787" -WorkingDirectory $root -PassThru -WindowStyle Normal
Write-Host "  PID: $($viewer.Id)" -ForegroundColor Gray

Start-Sleep -Seconds 1

Write-Host "`n=== 全部启动完成 ===" -ForegroundColor Green
Write-Host "浏览器打开: http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host "`n按任意键停止所有进程..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

Write-Host "`n停止中..." -ForegroundColor Red
Stop-Process -Id $sim.Id -ErrorAction SilentlyContinue
Stop-Process -Id $proxy.Id -ErrorAction SilentlyContinue
Stop-Process -Id $viewer.Id -ErrorAction SilentlyContinue
Write-Host "已停止。" -ForegroundColor Green
