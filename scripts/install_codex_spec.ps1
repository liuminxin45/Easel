param([string]$PythonPath = '')

$ErrorActionPreference = 'Stop'
$codexSpecProject = Split-Path -Parent $PSScriptRoot
$codexSpecEnvironment = Join-Path $codexSpecProject '.runtime/codex-spec'
$codexSpecPython = Join-Path $codexSpecEnvironment 'Scripts/python.exe'
$codexSpecCli = Join-Path $codexSpecEnvironment 'Scripts/codex-spec.exe'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is required.' }
if (-not (Test-Path -LiteralPath $codexSpecPython -PathType Leaf)) {
    if (-not $PythonPath) {
        $PythonPath = Join-Path $codexSpecProject '.runtime/workbench-python/Scripts/python.exe'
    }
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw 'Project Python is missing; pass -PythonPath with an existing Python 3.11+ executable.'
    }
    & uv venv --python $PythonPath $codexSpecEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'Codex Spec environment creation failed.' }
}

& uv pip sync --require-hashes --link-mode copy --python $codexSpecPython (Join-Path $PSScriptRoot 'requirements-codex-spec.txt')
if ($LASTEXITCODE -ne 0) { throw 'Pinned Codex Spec installation failed.' }
$codexSpecVersion = & $codexSpecCli --version
if ($LASTEXITCODE -ne 0 -or $codexSpecVersion.Trim() -ne '0.1.0') {
    throw "Unexpected Codex Spec version: $codexSpecVersion"
}
Write-Output "codex-spec $codexSpecVersion"

# Check tracked project files; never overwrite custom guidance during reinstallation.
$codexSpecOutput = & $codexSpecCli check --kind installed --project-dir $codexSpecProject --json
if ($LASTEXITCODE -ne 0) { throw ($codexSpecOutput -join "`n") }
Write-Output ($codexSpecOutput -join "`n")
