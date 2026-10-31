# Project-local entry point; forward all arguments to the pinned CLI.
$ErrorActionPreference = 'Stop'
$specKitProject = Split-Path -Parent $PSScriptRoot
$specKitBin = Join-Path $specKitProject '.runtime/spec-kit/Scripts'
$specKitCli = Join-Path $specKitBin 'specify.exe'
if (-not (Test-Path -LiteralPath $specKitCli -PathType Leaf)) {
    throw 'Run pwsh -NoProfile -File ./scripts/install_spec_kit.ps1 first.'
}

$specKitPreviousPath = $env:PATH
$specKitExitCode = 1
Push-Location -LiteralPath $specKitProject
try {
    $env:PATH = $specKitBin + [IO.Path]::PathSeparator + $specKitPreviousPath
    & $specKitCli @args
    $specKitExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $specKitPreviousPath
    Pop-Location
}
exit $specKitExitCode
