# Admin script to import certificate and install MSIX
$cerPath = "c:\Users\timpe\Desktop\Microsoft Store - Unpaid IAP Version\serenesudoku_new.cer"
$msixPath = "c:\Users\timpe\Desktop\Microsoft Store - Unpaid IAP Version\SereneSudoku.msix"

Write-Host "Importing certificate to Trusted Publisher store..."
certutil -addstore TrustedPublisher "$cerPath"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Certificate imported successfully"
    Write-Host ""
    Write-Host "You can now install the MSIX by double-clicking it."
    Write-Host "MSIX file: $msixPath"
} else {
    Write-Host "✗ Failed to import certificate"
}

Write-Host ""
Write-Host "Press any key to exit..."
Read-Host
