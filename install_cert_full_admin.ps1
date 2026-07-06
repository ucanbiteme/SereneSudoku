# Admin script to import certificate to both Root and TrustedPublisher
$cerPath = "c:\Users\timpe\Desktop\Microsoft Store - Unpaid IAP Version\serenesudoku_new.cer"

Write-Host "Importing certificate to Root store..."
certutil -addstore Root "$cerPath"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Certificate imported to Root store"
} else {
    Write-Host "✗ Failed to import to Root store"
}

Write-Host ""
Write-Host "Importing certificate to Trusted Publisher store..."
certutil -addstore TrustedPublisher "$cerPath"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Certificate imported to Trusted Publisher store"
} else {
    Write-Host "✗ Failed to import to Trusted Publisher store"
}

Write-Host ""
Write-Host "Certificate import complete. You can now install the MSIX."
Write-Host "Close this window and double-click SereneSudoku.msix again."
Write-Host ""
Write-Host "Press any key to exit..."
Read-Host
