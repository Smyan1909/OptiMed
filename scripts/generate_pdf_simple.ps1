# Simple PDF Generation for OptiMed Documentation
Write-Host "=== OptiMed Documentation PDF Generator ===" -ForegroundColor Cyan
Write-Host ""

# Check for Chrome
$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chromePath)) {
    $chromePath = "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
}

if (-not (Test-Path $chromePath)) {
    Write-Host "ERROR: Google Chrome not found!" -ForegroundColor Red
    exit 1
}

Write-Host "Chrome found" -ForegroundColor Green

# Create PDF directory
New-Item -ItemType Directory -Path "pdf" -Force | Out-Null

# Start MkDocs server
Write-Host "Starting MkDocs server..." -ForegroundColor Cyan
$job = Start-Job { Set-Location $using:PWD; mkdocs serve --no-livereload }
Start-Sleep 5

# Generate PDF
Write-Host "Generating PDF..." -ForegroundColor Cyan
$output = Join-Path $PWD "pdf\optimed-documentation-complete.pdf"
& $chromePath --headless --disable-gpu --print-to-pdf="$output" "http://localhost:8000/"

# Stop server
Stop-Job $job
Remove-Job $job

if (Test-Path $output) {
    Write-Host "SUCCESS! PDF created: $output" -ForegroundColor Green
    Start-Process $output
} else {
    Write-Host "Failed. Use manual method: mkdocs serve then Ctrl+P" -ForegroundColor Red
}

Read-Host "Press Enter"
