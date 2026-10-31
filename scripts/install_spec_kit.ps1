param([string]$PythonPath = '')

$ErrorActionPreference = 'Stop'
$specKitProject = Split-Path -Parent $PSScriptRoot
$specKitEnvironment = Join-Path $specKitProject '.runtime/spec-kit'
$specKitPython = Join-Path $specKitEnvironment 'Scripts/python.exe'
$specKitCli = Join-Path $specKitEnvironment 'Scripts/specify.exe'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is required.' }
if (-not (Test-Path -LiteralPath (Join-Path $specKitProject '.specify/config.yml'))) {
    throw 'Restore the tracked Spec Kit project configuration before installing.'
}
if (-not (Test-Path -LiteralPath $specKitPython -PathType Leaf)) {
    if (-not $PythonPath) {
        $PythonPath = Join-Path $specKitProject '.runtime/workbench-python/Scripts/python.exe'
    }
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw 'Project Python is missing; pass -PythonPath with an existing Python 3.11+ executable.'
    }
    & uv venv --python $PythonPath $specKitEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'Spec Kit environment creation failed.' }
}

& uv pip sync --link-mode copy --python $specKitPython (Join-Path $PSScriptRoot 'requirements-spec-kit.txt')
if ($LASTEXITCODE -ne 0) { throw 'Pinned Spec Kit installation failed.' }
$specKitVersion = & $specKitCli --version
if ($LASTEXITCODE -ne 0 -or $specKitVersion.Trim() -ne 'specify 2.0.0') {
    throw "Unexpected Spec Kit version: $specKitVersion"
}
Write-Output $specKitVersion

# Restore only absent, hash-locked pack caches. Never initialize or upgrade here.
foreach ($specKitCommand in @(@('pack', 'restore'), @('pack', 'doctor'), @('context'))) {
    $specKitOutput = & $specKitCli @specKitCommand --project-dir $specKitProject --json
    if ($LASTEXITCODE -ne 0) { throw ($specKitOutput -join "`n") }
    $specKitResult = $specKitOutput | ConvertFrom-Json
    if ($specKitResult.status -ne 'ok') { throw ($specKitOutput -join "`n") }
    Write-Output "$($specKitCommand -join ' '): ok"
}
