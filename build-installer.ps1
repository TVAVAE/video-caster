param(
    [Parameter(Mandatory = $true)][string]$FFmpegDirectory,
    [string]$ISCC = "ISCC.exe",
    [string]$Version = "0.3.2",
    [string]$Python = "python",
    [string]$DisplayDriverZip = "",
    [switch]$SkipAppBuild
)

$ErrorActionPreference = "Stop"
if ($env:VIDEOCASTER_BUILD_CONSOLE -eq '1') {
    throw 'Remove VIDEOCASTER_BUILD_CONSOLE before building the release installer.'
}
$ffmpegRoot = (Resolve-Path -LiteralPath $FFmpegDirectory).Path
foreach ($tool in @('ffmpeg.exe', 'ffprobe.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $ffmpegRoot "bin\$tool"))) {
        throw "Missing bin\$tool in FFmpegDirectory. Use an extracted Windows full build."
    }
}
$compiler = (Get-Command $ISCC -ErrorAction Stop).Source
$license = @('LICENSE', 'LICENSE.txt', 'COPYING.GPLv3') |
    ForEach-Object { Join-Path $ffmpegRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $license) { throw "The FFmpeg distribution must include its license." }

Push-Location $PSScriptRoot
try {
    if (-not $SkipAppBuild) { & .\build-windows.ps1 -Python $Python -DisplayDriverZip $DisplayDriverZip }
    $appExe = Join-Path $PSScriptRoot 'dist\VideoCaster.exe'
    if (-not (Test-Path -LiteralPath $appExe)) { throw 'Build dist\VideoCaster.exe first.' }
    $payload = Join-Path $PSScriptRoot 'build\installer-payload'
    $ffmpegBin = Join-Path $payload 'ffmpeg\bin'
    # Recreate only this dedicated payload directory; never package stale files.
    $expectedPayload = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'build\installer-payload'))
    if ([IO.Path]::GetFullPath($payload) -ne $expectedPayload) { throw 'Unexpected payload directory.' }
    if (Test-Path -LiteralPath $payload) { Remove-Item -LiteralPath $payload -Recurse -Force }
    New-Item -ItemType Directory -Path $ffmpegBin -Force > $null
    foreach ($tool in @('ffmpeg.exe', 'ffprobe.exe')) {
        Copy-Item -LiteralPath (Join-Path $ffmpegRoot "bin\$tool") -Destination $ffmpegBin
    }
    Get-ChildItem -LiteralPath (Join-Path $ffmpegRoot 'bin') -Filter '*.dll' -File |
        Copy-Item -Destination $ffmpegBin
    Copy-Item -LiteralPath $license -Destination (Join-Path $payload 'ffmpeg\LICENSE.txt')
    if (Test-Path -LiteralPath (Join-Path $ffmpegRoot 'README.txt')) {
        Copy-Item -LiteralPath (Join-Path $ffmpegRoot 'README.txt') -Destination (Join-Path $payload 'ffmpeg')
    }
    $ffmpegVersion = & (Join-Path $ffmpegBin 'ffmpeg.exe') -version
    if ($LASTEXITCODE -ne 0) { throw 'Bundled FFmpeg cannot run.' }
    @(
        'FFmpeg is a separate program distributed under its included license.',
        'Windows build and corresponding source information: https://www.gyan.dev/ffmpeg/builds/',
        'Upstream source: https://git.ffmpeg.org/ffmpeg.git',
        '',
        $ffmpegVersion
    ) | Set-Content -LiteralPath (Join-Path $payload 'ffmpeg\BUILD-INFO.txt') -Encoding UTF8
    Copy-Item -LiteralPath README.md -Destination (Join-Path $payload 'README.md')
    & $compiler "/DAppExe=$appExe" "/DPayloadDirectory=$payload" "/DOutputDirectory=$(Join-Path $PSScriptRoot 'dist')" "/DAppVersion=$Version" installer\VideoCaster.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    Write-Host "Built: $(Join-Path $PSScriptRoot 'dist\VideoCaster-Setup.exe')"
} finally {
    Pop-Location
}
