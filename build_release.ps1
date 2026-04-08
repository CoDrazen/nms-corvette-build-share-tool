param(
    [string]$ReleaseDir = "C:\NMS-App-Release"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$entryScript = Join-Path $repoRoot "ship_viewer.py"
$iconPath = Join-Path $repoRoot "icons\nms-app-icon-galaxy-nobg-256.ico"
$libnomExe = Join-Path $repoRoot "libNOM\libNOM.io.cli.exe"
$workRoot = Join-Path $repoRoot "build\pyinstaller"
$specRoot = Join-Path $repoRoot "build\spec"

if (-not (Test-Path -LiteralPath $entryScript)) {
    throw "Entry script not found: $entryScript"
}

if (-not (Test-Path -LiteralPath $iconPath)) {
    throw "Icon not found: $iconPath"
}

if (-not (Test-Path -LiteralPath $libnomExe)) {
    throw "libNOM executable not found: $libnomExe"
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null
New-Item -ItemType Directory -Force -Path $specRoot | Out-Null

$exeName = "NMS Corvette Build Share Tool"

$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", $exeName,
    "--icon", $iconPath,
    "--add-data", "$iconPath;icons",
    "--add-binary", "$libnomExe;libNOM",
    "--distpath", $ReleaseDir,
    "--workpath", $workRoot,
    "--specpath", $specRoot,
    $entryScript
)

& py @pyInstallerArgs

$exePath = Join-Path $ReleaseDir "$exeName.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Expected EXE was not created: $exePath"
}

Write-Output "Built release EXE:"
Write-Output $exePath
