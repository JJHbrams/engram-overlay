param(
    [ValidateSet("xeyes", "robot-arm", "robot-arm-3d", "robot-arm-3d-v2")]
    [string]$Overlay = "xeyes",
    [ValidateSet("observer", "replace")]
    [string]$Mode = "replace"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$launcher = Join-Path $venvRoot "Scripts\engram-custom-overlay.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv $venvRoot
}

$editableTarget = "${repoRoot}[tools]"
& $venvPython -m pip install --disable-pip-version-check -e $editableTarget
if ($LASTEXITCODE -ne 0) {
    throw "Editable install failed"
}
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Overlay launcher was not created: $launcher"
}

$userProfilePath = [Environment]::GetFolderPath("UserProfile")
$installDir = Join-Path $userProfilePath ".engram\overlays\$Overlay"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
$manifestPath = Join-Path $installDir "manifest.yaml"
$launcherYaml = $launcher.Replace("\", "/").Replace('"', '\"')
$overlayName = switch ($Overlay) {
    "robot-arm" { "Engram 3-Link Robot Arm" }
    "robot-arm-3d" { "Engram 3D Robot Arm" }
    "robot-arm-3d-v2" { "Engram Textured 3D Robot Arm V2" }
    default { "Engram XEyes" }
}
$manifest = @"
schema_version: 1
id: $Overlay
name: $overlayName
command:
  - "$launcherYaml"
  - "--overlay"
  - "$Overlay"
  - "--mode"
  - "$Mode"
supported_modes: [observer, replace]
"@
[System.IO.File]::WriteAllText($manifestPath, $manifest, [System.Text.UTF8Encoding]::new($false))

Write-Output "Installed: $manifestPath"
Write-Output "Launcher: $launcher"
Write-Output "Select '$overlayName' in Settings > Overlay and restart Engram."
