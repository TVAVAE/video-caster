# Run from PowerShell: .\build-windows.ps1 -Python python
# -DisplayDriverZip: a downloaded VirtualDisplayDriver-x86.Driver.Only.zip (else it is downloaded);
# see third_party\VirtualDisplayDriver\README.md
param([string]$Python = "python", [string]$DisplayDriverZip = "")

# The Virtual Display Driver for 'Use the TV as a second display', pinned to one release file
$VddUrl = "https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/25.7.23/VirtualDisplayDriver-x86.Driver.Only.zip"
$VddSha256 = "E24210692B442B39AF763536330CE78B423F19342B7A7792C26DE3944E418B3A"

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    throw "Build the Windows executable on Windows."
}

Push-Location $PSScriptRoot
$originalPath = $env:PATH
try {
    $buildPython = Join-Path $PSScriptRoot ".venv-build\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $buildPython)) {
        & $Python -m venv .venv-build
        if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment." }
    }
    & $buildPython -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Could not install build dependencies." }

    # The virtual display driver: the pinned release file, checked, unpacked into build\display-driver
    # (VideoCaster.spec puts that folder into the executable)
    New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "build") > $null
    $vddZip = if ($DisplayDriverZip) { (Resolve-Path -LiteralPath $DisplayDriverZip).Path } else {
        Join-Path $PSScriptRoot "build\VirtualDisplayDriver-x86.Driver.Only.zip" }
    if (-not (Test-Path -LiteralPath $vddZip)) {
        Write-Host "Downloading the Virtual Display Driver: $VddUrl"
        Invoke-WebRequest -Uri $VddUrl -OutFile $vddZip -UseBasicParsing
    }
    $hash = (Get-FileHash -LiteralPath $vddZip -Algorithm SHA256).Hash
    if ($hash -ne $VddSha256) { throw "The Virtual Display Driver zip isn't the pinned release file (SHA-256 $hash)." }
    $vddDir = Join-Path $PSScriptRoot "build\display-driver"
    $vddTemp = Join-Path $PSScriptRoot "build\display-driver-unpack"
    foreach ($d in @($vddDir, $vddTemp)) { if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force } }
    Expand-Archive -LiteralPath $vddZip -DestinationPath $vddTemp
    $inf = Get-ChildItem -LiteralPath $vddTemp -Recurse -Filter "MttVDD.inf" | Select-Object -First 1
    if (-not $inf) { throw "MttVDD.inf is missing from the Virtual Display Driver zip." }
    New-Item -ItemType Directory -Path $vddDir > $null
    foreach ($name in @("MttVDD.inf", "MttVDD.dll", "mttvdd.cat", "vdd_settings.xml")) {
        Copy-Item -LiteralPath (Join-Path $inf.DirectoryName $name) -Destination $vddDir
    }
    foreach ($name in @("MttVDD.dll", "mttvdd.cat")) {
        $sig = Get-AuthenticodeSignature -LiteralPath (Join-Path $vddDir $name)
        if ($sig.Status -ne "Valid") { throw "$name in the Virtual Display Driver isn't validly signed ($($sig.Status))." }
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "third_party\VirtualDisplayDriver\LICENSE") -Destination $vddDir
    Remove-Item -LiteralPath $vddTemp -Recurse -Force
    Write-Host "Virtual Display Driver: $vddDir (checked)"
    # Other tools on PATH can carry old Windows/ICU DLLs. Let PyInstaller find
    # system libraries in Windows and package libraries in the build environment.
    $env:PATH = @((Split-Path $buildPython), "$env:SystemRoot\System32", $env:SystemRoot) -join ';'
    & $buildPython -m PyInstaller --clean --noconfirm VideoCaster.spec
    if ($LASTEXITCODE -ne 0) { throw "Executable build failed." }
    $executableName = if ($env:VIDEOCASTER_BUILD_CONSOLE -eq '1') { 'VideoCaster-debug.exe' } else { 'VideoCaster.exe' }
    Write-Host "Built: $(Join-Path $PSScriptRoot "dist\$executableName")"
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
