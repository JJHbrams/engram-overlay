<#
.SYNOPSIS
    Install a renderer as a standalone runtime and, optionally, start it with Windows.

.DESCRIPTION
    Event API v2 made the renderer its own program. Engram publishes a loopback
    API and nothing else -- it does not start, stop, or own this process -- so a
    renderer needs somewhere to live and something to start it. That is all this
    script does.

    The runtime is a plain venv under LOCALAPPDATA with the package installed
    into it, copied rather than linked: once installed it owes nothing to this
    checkout, and deleting or moving the repository leaves it running.

    Use scripts/install-dev.ps1 instead while working on the code -- that one
    links the checkout so edits take effect without reinstalling.
#>
param(
    [string]$Overlay = "bolttagu-2d",
    [string]$Root,
    [ValidateRange(0.2, 4.0)]
    [double]$Scale = 1.0,
    [switch]$EyeEmission,
    [switch]$Presentation,
    [switch]$NoFacePointer,
    [switch]$Autostart,
    [switch]$RemoveAutostart,
    [switch]$Start,
    [switch]$List,
    [switch]$RemoveLegacyManifests
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Root) {
    $Root = Join-Path $env:LOCALAPPDATA "engram-overlay"
}
$runtime = Join-Path $Root "runtime"
$runtimePython = Join-Path $runtime "Scripts\python.exe"
# The console launcher shows errors; the windowed one starts without a black
# flash, which is the only reason autostart is bearable.
$consoleLauncher = Join-Path $runtime "Scripts\engram-custom-overlay.exe"
$windowedLauncher = Join-Path $runtime "Scripts\engram-custom-overlayw.exe"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$runValue = "EngramOverlay"

function Remove-LegacyManifests {
    <#
        v1 manifests told Engram how to spawn a renderer. v2 spawns nothing, so
        every one of them is inert -- and misleading, because the command inside
        still points at whatever checkout installed it.

        Only the manifest goes. The rest of the directory is the renderer's own
        state, mapping.json above all, and deleting a mapping someone built by
        hand to tidy up a dead file would be a poor trade.
    #>
    $overlaysDir = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".engram\overlays"
    if (-not (Test-Path -LiteralPath $overlaysDir)) {
        Write-Output "No legacy manifests: $overlaysDir does not exist."
        return
    }
    $removed = @()
    $kept = @()
    foreach ($dir in Get-ChildItem -LiteralPath $overlaysDir -Directory) {
        $manifest = Join-Path $dir.FullName "manifest.yaml"
        if (Test-Path -LiteralPath $manifest) {
            Remove-Item -LiteralPath $manifest -Force
            $removed += $dir.Name
        }
        $survivors = Get-ChildItem -LiteralPath $dir.FullName -Force
        if ($survivors) {
            $kept += [pscustomobject]@{
                Overlay = $dir.Name
                Kept    = ($survivors | ForEach-Object { $_.Name }) -join ", "
            }
        }
    }
    if ($removed) {
        Write-Output "Removed $($removed.Count) inert v1 manifest(s): $($removed -join ', ')"
    } else {
        Write-Output "No v1 manifests found."
    }
    if ($kept) {
        Write-Output ""
        Write-Output "Left in place:"
        $kept | Format-Table -AutoSize Overlay, Kept | Out-String | Write-Output
    }
}

if ($RemoveLegacyManifests) {
    Remove-LegacyManifests
    if (-not ($Autostart -or $RemoveAutostart -or $Start -or $List)) {
        exit 0
    }
}

if ($RemoveAutostart) {
    if (Get-ItemProperty -Path $runKey -Name $runValue -ErrorAction SilentlyContinue) {
        Remove-ItemProperty -Path $runKey -Name $runValue
        Write-Output "Autostart removed. A renderer already running stays running."
    } else {
        Write-Output "Autostart was not set."
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $runtimePython)) {
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    python -m venv $runtime
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the runtime venv at $runtime"
    }
}

# Not editable: the runtime keeps its own copy so it survives this checkout.
& $runtimePython -m pip install --disable-pip-version-check --upgrade $repoRoot
if ($LASTEXITCODE -ne 0) {
    throw "Runtime install failed"
}
foreach ($launcher in @($consoleLauncher, $windowedLauncher)) {
    if (-not (Test-Path -LiteralPath $launcher)) {
        throw "Launcher was not created: $launcher"
    }
}

# The installed runtime is the source of truth for what it can render, so the
# roster is read back out of it rather than from the checkout.
$catalogJson = & $runtimePython -c @"
import json
from engram_overlay.registry import overlay_catalog
print(json.dumps([{'id': s.id, 'name': s.name, 'backend': s.backend, 'summary': s.summary} for s in overlay_catalog()]))
"@
if ($LASTEXITCODE -ne 0) {
    throw "Could not read the overlay catalog from the runtime"
}
$catalog = $catalogJson | ConvertFrom-Json

if ($List) {
    & $consoleLauncher --list-overlays
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

$windowedCommand = ('"{0}" {1}' -f $windowedLauncher, ($rendererArgs -join " "))
$consoleCommand = ('"{0}" {1}' -f $consoleLauncher, ($rendererArgs -join " "))

# One .cmd so the same options can be run by hand, and read later to see what
# was installed. It uses the console launcher: if the renderer fails to start,
# the reason should be visible rather than swallowed.
$startScript = Join-Path $Root "start-overlay.cmd"
[System.IO.File]::WriteAllText(
    $startScript,
    "@echo off`r`nrem Written by scripts/install-runtime.ps1 -- re-run it to change these options.`r`n$consoleCommand %*`r`n",
    [System.Text.UTF8Encoding]::new($false)
)

if ($Autostart) {
    New-Item -Path $runKey -Force | Out-Null
    Set-ItemProperty -Path $runKey -Name $runValue -Value $windowedCommand
}

Write-Output ""
Write-Output "Installed $($spec.Name) ($Overlay)"
Write-Output "  Runtime  : $runtime"
Write-Output "  Start    : $startScript"
if ($Autostart) {
    Write-Output "  Autostart: on (HKCU Run\$runValue) -- remove with -RemoveAutostart"
} else {
    $existing = Get-ItemProperty -Path $runKey -Name $runValue -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Output "  Autostart: still set from an earlier run -- re-run with -Autostart to update it"
    } else {
        Write-Output "  Autostart: off -- add it with -Autostart"
    }
}
Write-Output ""
Write-Output "The renderer connects to Engram on its own and waits if Engram is not running."
Write-Output "Start it, then pick it in Settings > Overlay; Engram lists renderers that are connected."

if ($Start) {
    Start-Process -FilePath $windowedLauncher -ArgumentList $rendererArgs
    Write-Output ""
    Write-Output "Started."
}
