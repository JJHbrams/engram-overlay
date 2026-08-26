param(
    [int]$Build = 0,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if ($Build -le 0) {
    $Build = [int](& git -C $repoRoot rev-list --count HEAD)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not derive Build from Git history"
    }
}

$previousBuild = $env:SEMVER4_BUILD
try {
    $env:SEMVER4_BUILD = $Build.ToString()
    & $Python -m build $repoRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Package build failed"
    }
} finally {
    $env:SEMVER4_BUILD = $previousBuild
}

$baseVersion = (Get-Content (Join-Path $repoRoot "VERSION") -Raw).Trim()
Write-Output "Built engram-custom-overlay $baseVersion.$Build"
