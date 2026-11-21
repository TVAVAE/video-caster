# Run from PowerShell: .\build-windows.ps1 -Python python
param([string]$Python = "python")

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
