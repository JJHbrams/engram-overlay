<#
.SYNOPSIS
    Set up this checkout as a runnable renderer for development.

.DESCRIPTION
    Installs the package into the repository's own .venv as an editable install,
    so edits to src/ take effect the next time the renderer starts.

    It no longer writes manifests. Under Event API v2 Engram does not launch
    anything -- a renderer connects to it -- so a manifest describing how to
    spawn one has nothing left to do.

    Use scripts/install-runtime.ps1 to install a copy that outlives this
    checkout, or to start a renderer with Windows.
#>
param(
    [string]$Overlay = "bolttagu-2d",
    [ValidateRange(0.2, 4.0)]
    [double]$Scale = 1.0,
    [switch]$EyeEmission,
    [switch]$Presentation,
    [switch]$NoFacePointer,
    [switch]$List,
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$launcher = Join-Path $venvRoot "Scripts\engram-custom-overlay.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the venv at $venvRoot"
    }
}

$editableTarget = "${repoRoot}[tools]"
& $venvPython -m pip install --disable-pip-version-check -e $editableTarget
if ($LASTEXITCODE -ne 0) {
    throw "Editable install failed"
}
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Overlay launcher was not created: $launcher"
}

# The registry is the single source of truth for the preset roster. Reading it here
# keeps this script from carrying its own copy that drifts when an overlay is added.
$catalogJson = & $venvPython -c @"
import json
from engram_overlay.registry import overlay_catalog
print(json.dumps([{'id': s.id, 'name': s.name, 'backend': s.backend, 'summary': s.summary} for s in overlay_catalog()]))
"@
if ($LASTEXITCODE -ne 0) {
    throw "Could not read the overlay catalog"
}
$catalog = $catalogJson | ConvertFrom-Json

if ($List) {
    & $launcher --list-overlays
    exit 0
}

$known = $catalog | ForEach-Object { $_.id }
if ($known -notcontains $Overlay) {
    throw "Unknown overlay '$Overlay'. Available: $($known -join ', ')"
}
if ($EyeEmission -and $Overlay -notin @("robot-arm-3d-v2", "robot-arm-3d-v3")) {
    throw "Eye emission is only supported by robot-arm-3d-v2 and robot-arm-3d-v3"
}
foreach ($restricted in @(@{ On = $Scale -ne 1.0; Name = "Scale" },
                          @{ On = [bool]$Presentation; Name = "Presentation" },
                          @{ On = [bool]$NoFacePointer; Name = "NoFacePointer" })) {
    if ($restricted.On -and $Overlay -ne "bolttagu-2d") {
        throw "$($restricted.Name) is only supported by bolttagu-2d"
    }
}

$spec = $catalog | Where-Object { $_.id -eq $Overlay }
$rendererArgs = @("--overlay", $Overlay)
if ($EyeEmission) { $rendererArgs += "--eye-emission" }
if ($NoFacePointer) { $rendererArgs += "--no-face-pointer" }
if ($Scale -ne 1.0) { $rendererArgs += @("--scale", "$Scale") }
if ($Presentation) { $rendererArgs += "--presentation" }

Write-Output ""
Write-Output "Ready: $($spec.Name) ($Overlay)"
Write-Output "  Run: `"$launcher`" $($rendererArgs -join ' ')"
Write-Output ""
Write-Output "The renderer connects to Engram itself and waits if Engram is not running."
Write-Output "Once it is connected, pick it in Settings > Overlay."

if ($Start) {
    & $launcher @rendererArgs
}
