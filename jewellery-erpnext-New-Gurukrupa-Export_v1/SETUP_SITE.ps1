# Frappe Site Setup Script for Windows
# Run this script in your Frappe bench directory

Write-Host "=== Frappe Site Setup Script ===" -ForegroundColor Green
Write-Host ""

# Step 1: Check if we're in a bench directory
if (-not (Test-Path "sites")) {
    Write-Host "ERROR: This doesn't appear to be a Frappe bench directory!" -ForegroundColor Red
    Write-Host "Please navigate to your bench directory first (e.g., C:\Users\ASUS\frappe-bench)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Then run:" -ForegroundColor Yellow
    Write-Host "  .\SETUP_SITE.ps1" -ForegroundColor Cyan
    exit 1
}

Write-Host "Step 1: Checking existing sites..." -ForegroundColor Cyan
$sites = Get-ChildItem -Path "sites" -Directory | Where-Object { $_.Name -ne "common" -and $_.Name -ne "assets" }
if ($sites) {
    Write-Host "Found sites:" -ForegroundColor Green
    foreach ($site in $sites) {
        Write-Host "  - $($site.Name)" -ForegroundColor White
    }
} else {
    Write-Host "No sites found. You need to create one." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Step 2: Checking if jewellery_erpnext app is installed..." -ForegroundColor Cyan
$appsPath = "apps\jewellery_erpnext"
if (Test-Path $appsPath) {
    Write-Host "App found at: $appsPath" -ForegroundColor Green
} else {
    Write-Host "App not found. You need to install it." -ForegroundColor Yellow
    Write-Host "Run: bench get-app jewellery_erpnext [path-to-app]" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "=== Manual Steps Required ===" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. If site doesn't exist, create it:" -ForegroundColor White
Write-Host "   bench new-site site1.local" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Install the app on your site:" -ForegroundColor White
Write-Host "   bench --site site1.local install-app jewellery_erpnext" -ForegroundColor Cyan
Write-Host ""
Write-Host "3. Run migrations:" -ForegroundColor White
Write-Host "   bench --site site1.local migrate" -ForegroundColor Cyan
Write-Host ""
Write-Host "4. Build assets:" -ForegroundColor White
Write-Host "   bench --site site1.local build" -ForegroundColor Cyan
Write-Host ""
Write-Host "5. Start the server:" -ForegroundColor White
Write-Host "   bench start" -ForegroundColor Cyan
Write-Host ""
Write-Host "6. Access at: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host ""

