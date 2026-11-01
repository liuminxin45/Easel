# Project-local entry point; forward arguments and exit status to the pinned CLI.
$ErrorActionPreference = 'Stop'
$codexSpecProject = Split-Path -Parent $PSScriptRoot
$codexSpecBin = Join-Path $codexSpecProject '.runtime/codex-spec/Scripts'
$codexSpecCli = Join-Path $codexSpecBin 'codex-spec.exe'
if (-not (Test-Path -LiteralPath $codexSpecCli -PathType Leaf)) {
    throw 'Run pwsh -NoProfile -File ./scripts/install_codex_spec.ps1 first.'
}
$codexSpecPreviousPath = $env:PATH
$codexSpecPreviousUtf8 = $env:PYTHONUTF8
$codexSpecExitCode = 1
Push-Location -LiteralPath $codexSpecProject
try {
    $env:PATH = $codexSpecBin + [IO.Path]::PathSeparator + $codexSpecPreviousPath
    $env:PYTHONUTF8 = '1'
    & $codexSpecCli @args
    $codexSpecExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $codexSpecPreviousPath
    $env:PYTHONUTF8 = $codexSpecPreviousUtf8
    Pop-Location
}
exit $codexSpecExitCode
