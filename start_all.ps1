# earEEG one-click startup
# Usage: .\start_all.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== earEEG Startup ===" -ForegroundColor Cyan

Write-Host "[1/3] Starting simulated device..." -ForegroundColor Yellow
$sim = Start-Process -FilePath "python" -ArgumentList "-m", "ear_eeg_sound_lab.src.simulated_device", "--auto-start", "--eeg-profile", "focused", "--mic-mode", "chirp" -WorkingDirectory $root -PassThru -WindowStyle Normal
Write-Host "  PID: $($sim.Id)" -ForegroundColor Gray

Start-Sleep -Seconds 2

Write-Host "[2/3] Starting lsl_proxy..." -ForegroundColor Yellow
$proxy = Start-Process -FilePath "python" -ArgumentList "-m", "upper_machine.lsl_proxy.main", "--host", "127.0.0.1", "--port", "8889", "--lsl", "--start", "--stats" -WorkingDirectory $root -PassThru -WindowStyle Normal
Write-Host "  PID: $($proxy.Id)" -ForegroundColor Gray

Start-Sleep -Seconds 2

Write-Host "[3/3] Starting viewer..." -ForegroundColor Yellow
$viewer = Start-Process -FilePath "python" -ArgumentList "-m", "upper_machine.eeg_viewer.main", "--host", "127.0.0.1", "--port", "8765", "--proxy-url", "http://127.0.0.1:8787" -WorkingDirectory $root -PassThru -WindowStyle Normal
Write-Host "  PID: $($viewer.Id)" -ForegroundColor Gray

Start-Sleep -Seconds 1

Write-Host ""
Write-Host "=== All started ===" -ForegroundColor Green
Write-Host "Browser: http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to stop all processes..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

Write-Host ""
Write-Host "Stopping..." -ForegroundColor Red
Stop-Process -Id $sim.Id -ErrorAction SilentlyContinue
Stop-Process -Id $proxy.Id -ErrorAction SilentlyContinue
Stop-Process -Id $viewer.Id -ErrorAction SilentlyContinue
Write-Host "Done." -ForegroundColor Green
