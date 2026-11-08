# Nandhini Stationery - PowerShell Server & Dashboard Launcher
Set-Location -Path $PSScriptRoot

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "          NANDHINI STATIONERY - LAUNCHING SERVER...                  " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) {
    $py = (Get-Command py -ErrorAction SilentlyContinue).Source
}
if (-not $py -and (Test-Path "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe")) {
    $py = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe"
}

if (-not $py) {
    Write-Host "[ERROR] Python was not found on your system." -ForegroundColor Red
    pause
    exit 1
}

& $py "$PSScriptRoot\run_server.py"
