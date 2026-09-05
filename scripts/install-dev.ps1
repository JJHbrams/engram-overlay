param(
    [string]$Overlay = "xeyes",
    [ValidateSet("observer", "replace")]
    [string]$Mode = "replace",
    [switch]$EyeEmission,
    [double]$Scale = 1.0,
    [switch]$All,
    [switch]$List,
    [switch]$Presentation
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
if ($All) {
    if ($EyeEmission -or $Scale -ne 1.0 -or $Presentation) {
        throw "-EyeEmission, -Scale and -Presentation apply to a single overlay; drop -All or install that overlay on its own"
    }
    $targets = $known
} else {
    if ($known -notcontains $Overlay) {
        throw "Unknown overlay '$Overlay'. Available: $($known -join ', ')"
    }
    if ($EyeEmission -and $Overlay -notin @("robot-arm-3d-v2", "robot-arm-3d-v3")) {
        throw "Eye emission is only supported by robot-arm-3d-v2 and robot-arm-3d-v3"
    }
    if ($Scale -ne 1.0 -and $Overlay -ne "bolttagu-2d") {
        throw "Scale is only supported by bolttagu-2d"
    }
    if ($Presentation -and $Overlay -ne "bolttagu-2d") {
        throw "Presentation is only supported by bolttagu-2d"
    }
    if ($Scale -lt 0.2 -or $Scale -gt 4.0) {
        throw "Scale must be between 0.2 and 4.0"
    }
    $targets = @($Overlay)
}

$userProfilePath = [Environment]::GetFolderPath("UserProfile")
$launcherYaml = $launcher.Replace("\", "/").Replace('"', '\"')
$installed = @()

foreach ($id in $targets) {
    $spec = $catalog | Where-Object { $_.id -eq $id }
    $installDir = Join-Path $userProfilePath ".engram\overlays\$id"
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    $manifestPath = Join-Path $installDir "manifest.yaml"

    $commandTail = @(
        '  - "--mode"'
        "  - `"$Mode`""
    )
    if ($EyeEmission) {
        $commandTail += '  - "--eye-emission"'
    }
    if ($Scale -ne 1.0) {
        $commandTail += '  - "--scale"'
        $commandTail += ('  - "{0}"' -f $Scale)
    }
    if ($Presentation) {
        # Engram's launcher owns show/hide for this renderer.
        $commandTail += '  - "--presentation"'
    }
    $commandTailYaml = $commandTail -join "`n"

    $manifest = @"
schema_version: 1
id: $id
name: $($spec.name)
command:
  - "$launcherYaml"
  - "--overlay"
  - "$id"
$commandTailYaml
supported_modes: [observer, replace]
"@
    [System.IO.File]::WriteAllText($manifestPath, $manifest, [System.Text.UTF8Encoding]::new($false))
    $installed += [pscustomobject]@{ Id = $id; Name = $spec.name; Manifest = $manifestPath }
}

$installed | Format-Table -AutoSize Id, Name, Manifest | Out-String | Write-Output
Write-Output "Launcher: $launcher"
if ($installed.Count -eq 1) {
    Write-Output "Select '$($installed[0].Name)' in Settings > Overlay and restart Engram."
} else {
    Write-Output "$($installed.Count) presets registered. Pick one in Settings > Overlay and restart Engram."
}
Write-Output "This script never changes the current selection."
