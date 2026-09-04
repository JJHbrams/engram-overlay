param(
    [ValidateSet("xeyes", "bolttagu-2d", "rabbit-2d", "robot-arm", "robot-arm-3d", "robot-arm-3d-v2", "robot-arm-3d-v3")]
    [string]$Overlay = "xeyes",
    [ValidateSet("observer", "replace")]
    [string]$Mode = "replace",
    [switch]$EyeEmission,
    [double]$Scale = 1.0
)

$ErrorActionPreference = "Stop"
if ($EyeEmission -and $Overlay -notin @("robot-arm-3d-v2", "robot-arm-3d-v3")) {
    throw "Eye emission is only supported by robot-arm-3d-v2 and robot-arm-3d-v3"
}
if ($Scale -ne 1.0 -and $Overlay -ne "bolttagu-2d") {
    throw "Scale is only supported by bolttagu-2d"
}
if ($Scale -lt 0.2 -or $Scale -gt 4.0) {
    throw "Scale must be between 0.2 and 4.0"
}
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
    "bolttagu-2d" { "Bolttagu" }
    "rabbit-2d" { "Rabbit" }
    "robot-arm" { "Engram 3-Link Robot Arm" }
    "robot-arm-3d" { "Engram 3D Robot Arm" }
    "robot-arm-3d-v2" { "Engram Textured 3D Robot Arm V2" }
    "robot-arm-3d-v3" { "CCTV" }
    default { "Engram XEyes" }
}
$eyeEmissionArg = if ($EyeEmission) { '  - "--eye-emission"' } else { $null }
$scaleArgs = if ($Scale -ne 1.0) { @('  - "--scale"', ('  - "{0}"' -f $Scale)) } else { @() }
$commandTail = @(
    '  - "--mode"'
    "  - `"$Mode`""
)
if ($eyeEmissionArg) {
    $commandTail += $eyeEmissionArg
}
if ($scaleArgs.Count -gt 0) {
    $commandTail += $scaleArgs
}
$commandTailYaml = $commandTail -join "`n"
$manifest = @"
schema_version: 1
id: $Overlay
name: $overlayName
command:
  - "$launcherYaml"
  - "--overlay"
  - "$Overlay"
$commandTailYaml
supported_modes: [observer, replace]
"@
[System.IO.File]::WriteAllText($manifestPath, $manifest, [System.Text.UTF8Encoding]::new($false))

Write-Output "Installed: $manifestPath"
Write-Output "Launcher: $launcher"
Write-Output "Select '$overlayName' in Settings > Overlay and restart Engram."
