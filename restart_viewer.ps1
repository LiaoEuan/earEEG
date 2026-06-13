# Restart viewer only (simulated device and lsl_proxy keep running)
# Usage: .\restart_viewer.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Restarting viewer..." -ForegroundColor Yellow

Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "upper_machine.eeg_viewer.main"
} | Stop-Process -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 1

Start-Process -FilePath "python" -ArgumentList "-m", "upper_machine.eeg_viewer.main", "--host", "127.0.0.1", "--port", "8765", "--proxy-url", "http://127.0.0.1:8787" -WorkingDirectory $root -WindowStyle Normal

Write-Host "Viewer restarted. Refresh browser: http://127.0.0.1:8765" -ForegroundColor Green
