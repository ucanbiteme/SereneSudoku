$pwdPath = "C:\Users\timpe\Desktop\Microsoft Store - Unpaid IAP Version"
Set-Location $pwdPath
$packageDir = Join-Path $pwdPath "package_for_msix"
$distDir = Join-Path $pwdPath "dist\SereneSudoku"

# Preserve AppxManifest.xml and any other packaging files already in package_for_msix,
# then sync the full dist folder contents into it (overwriting stale build artifacts)
if (Test-Path $distDir) {
    Write-Output "Syncing dist folder into package_for_msix..."
    Get-ChildItem -Path $distDir | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $packageDir -Recurse -Force
    }
    Write-Output "Sync complete."
} else {
    Write-Output "No dist folder found - using existing package_for_msix contents with existing AppxManifest.xml"
}

$msixPath = Join-Path $pwdPath "SereneSudoku.msix"
$bundleTxt = Join-Path $pwdPath "SereneSudoku-bundle.txt"
$bundlePath = Join-Path $pwdPath "SereneSudoku.msixbundle"

$signtool = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"
$makeappx = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\makeappx.exe"

Write-Output "Building MSIX package from $packageDir"
# Ensure StoreBridge helper is included if present (built via dotnet build Tools\StoreBridge -c Release)
Try {
    $bridgeCandidates = @(
        # 19041 targets
        Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.19041.0\StoreBridge.exe",
        Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.19041.0\win-x64\StoreBridge.exe",
        Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.19041.0\win-x86\StoreBridge.exe",
        Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.19041.0\publish\StoreBridge.exe",
        # 22621 targets
        Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.22621.0\StoreBridge.exe",
        Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.22621.0\win-x64\StoreBridge.exe",
        Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.22621.0\win-x86\StoreBridge.exe",
        Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.22621.0\publish\StoreBridge.exe"
    )

    $destBridgeDir = Join-Path $packageDir "_internal\StoreBridge"
    if (-not (Test-Path $destBridgeDir)) { New-Item -ItemType Directory -Path $destBridgeDir | Out-Null }

    $found = $false
    foreach ($c in $bridgeCandidates) {
        if (Test-Path $c) {
            Write-Output "Found StoreBridge build at: $c -> copying into package"
            Copy-Item -Path $c -Destination (Join-Path $destBridgeDir "StoreBridge.exe") -Force
            $found = $true
            break
        }
    }

    if (-not $found) {
        Write-Output "StoreBridge.exe not found in expected build locations. If you want StoreBridge enabled, run: dotnet build Tools\StoreBridge -c Release and re-run this script."
    }
} Catch {
    Write-Output "Warning: error while attempting to include StoreBridge: $_"
}

& $makeappx pack /d $packageDir /p $msixPath /o

Write-Output "Creating a self-signed signing certificate"
$cert = New-SelfSignedCertificate -Subject "CN=Serene Sudoku" -CertStoreLocation Cert:\CurrentUser\My -KeyExportPolicy Exportable -KeyAlgorithm RSA -KeyLength 2048 -NotAfter (Get-Date).AddYears(10) -FriendlyName "Serene Sudoku Test Signing Certificate" -Type CodeSigningCert
$secure = ConvertTo-SecureString "Sudoku4Ever" -AsPlainText -Force
$pfxPath = Join-Path $pwdPath "serenesudoku_new.pfx"
$cerPath = Join-Path $pwdPath "serenesudoku_new.cer"
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $secure
Export-Certificate -Cert $cert -FilePath $cerPath
Write-Output "Importing signing certificate into CurrentUser\Root so package trust can validate"
Import-Certificate -FilePath $cerPath -CertStoreLocation Cert:\CurrentUser\Root | Out-Null

Write-Output "Signing MSIX package"
& $signtool sign /fd SHA256 /a /f $pfxPath /p Sudoku4Ever /tr http://timestamp.digicert.com /td SHA256 $msixPath

Write-Output "Bundling MSIX into MSIXBUNDLE"
& $makeappx bundle /f $bundleTxt /p $bundlePath /o

Write-Output "Signing MSIXBUNDLE package"
& $signtool sign /fd SHA256 /a /f $pfxPath /p Sudoku4Ever /tr http://timestamp.digicert.com /td SHA256 $bundlePath

Write-Output "SUCCESS: MSIX and MSIXBUNDLE rebuilt and signed."
