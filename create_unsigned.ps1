$pwdPath = "C:\Users\timpe\Desktop\Microsoft Store - Unpaid IAP Version"
Set-Location $pwdPath
$packageDir = Join-Path $pwdPath "package_for_msix"

$msixPath = Join-Path $pwdPath "SereneSudoku.msix"
$bundleTxt = Join-Path $pwdPath "SereneSudoku-bundle.txt"
$bundlePath = Join-Path $pwdPath "SereneSudoku.msixbundle"

$makeappx = "C:\Program Files (x86)\Windows Kits\10\App Certification Kit\makeappx.exe"

Write-Output "Building unsigned MSIX package from $packageDir"
# Ensure StoreBridge helper is included if present (built via `dotnet build Tools\StoreBridge -c Release`)
Try {
	$bridgeCandidates = @(
		# Possible build output locations (19041 and 22621 target frameworks)
		Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.19041.0\StoreBridge.exe",
		Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.19041.0\win-x64\StoreBridge.exe",
		Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.19041.0\win-x86\StoreBridge.exe",
		Join-Path $pwdPath "Tools\StoreBridge\bin\Release\net6.0-windows10.0.19041.0\publish\StoreBridge.exe",
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

Write-Output "Bundling MSIX into unsigned MSIXBUNDLE"
& $makeappx bundle /o /f $bundleTxt /p $bundlePath

Write-Output "SUCCESS: Unsigned MSIX and MSIXBUNDLE created (ready for Partner Center signing)."
