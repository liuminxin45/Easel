[CmdletBinding()]
param(
    [string]$AppRoot = 'D:/Projects/Easel',
    [string]$RuntimeRoot = 'D:/Services/EaselHealthControl',
    [string]$PythonBase = 'C:/Users/38482/AppData/Local/Programs/Python/Python311/python.exe',
    [switch]$Start
)
$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$appPath = [IO.Path]::GetFullPath($AppRoot)
$runtimePath = [IO.Path]::GetFullPath($RuntimeRoot)
if ($runtimePath.StartsWith($appPath.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or $runtimePath -eq $appPath) {
    throw 'Controller runtime must be outside the application.'
}
New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
$owner = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $runtimePath /inheritance:r /grant:r "${owner}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot protect controller runtime owner.' }
$pythonDirectory = Join-Path $runtimePath 'python'
$python = Join-Path $pythonDirectory 'Scripts/python.exe'
$pythonw = Join-Path $pythonDirectory 'Scripts/pythonw.exe'
if (!(Test-Path -LiteralPath $python)) {
    & $PythonBase -m venv --without-pip $pythonDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create independent Python environment.' }
}
& $python -I -c 'import sys; assert sys.version_info >= (3,11)'
if ($LASTEXITCODE -ne 0) { throw 'Independent Python must be >= 3.11.' }
$files = [ordered]@{}
Get-ChildItem -LiteralPath (Join-Path $sourceRoot 'easel_health_control') -Filter '*.py' -File | Sort-Object Name | ForEach-Object {
    $files['easel_health_control/'+$_.Name] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$manifest = [ordered]@{schema=1; files=$files}
$raw = $manifest | ConvertTo-Json -Depth 5 -Compress
$digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($raw))).ToLowerInvariant()
$release = $digest.Substring(0,16)
$releaseRoot = Join-Path $runtimePath ('releases/'+$release)
if (!(Test-Path -LiteralPath $releaseRoot)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $releaseRoot 'easel_health_control') | Out-Null
    foreach ($name in $files.Keys) {
        Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination (Join-Path $releaseRoot $name)
    }
    [IO.File]::WriteAllText((Join-Path $releaseRoot 'controller-release.json'), $raw, [Text.UTF8Encoding]::new($false))
}
foreach ($name in $files.Keys) {
    if ((Get-FileHash -LiteralPath (Join-Path $releaseRoot $name)).Hash.ToLowerInvariant() -ne $files[$name]) { throw 'Immutable controller release differs.' }
}
$configPath = Join-Path $runtimePath 'config.json'
if (!(Test-Path -LiteralPath $configPath)) {
    $config = Get-Content -LiteralPath (Join-Path $sourceRoot 'config.example.json') -Raw | ConvertFrom-Json
    $config.app_root = $appPath
    $config.state_root = Join-Path $runtimePath 'state'
    $config | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configPath -Encoding utf8NoBOM
}
$launch = Join-Path $runtimePath 'launch.pyw'
Copy-Item -LiteralPath (Join-Path $sourceRoot 'launch.pyw') -Destination $launch -Force
$selection = @{release=$release; manifest_sha256=$digest}
$selection | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimePath 'active.json.new') -Encoding utf8NoBOM
Move-Item -LiteralPath (Join-Path $runtimePath 'active.json.new') -Destination (Join-Path $runtimePath 'active.json') -Force
$backupRoot = Join-Path $runtimePath 'task-backups'
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
$principal = New-ScheduledTaskPrincipal -UserId $owner -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
foreach ($entry in @(@{name='EaselHealthControl'; action='run'},@{name='EaselHealthDaily'; action='daily'})) {
    $name = $entry.name
    $arguments = '"'+$launch+'" '+$entry.action
    $old = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($old) {
        if (@($old.Actions).Count -ne 1 -or $old.Actions.Execute -ne $pythonw -or $old.Actions.Arguments -ne $arguments -or
            $old.Actions.WorkingDirectory -ne $runtimePath -or $old.Principal.UserId -notin @($owner,$owner.Split('\')[-1])) {
            throw 'Refusing to replace a task with different ownership.'
        }
        Export-ScheduledTask -TaskName $name | Set-Content -LiteralPath (Join-Path $backupRoot ($name+'-'+(Get-Date -Format 'yyyyMMdd-HHmmssffff')+'.xml')) -Encoding utf8NoBOM
    }
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $runtimePath
    if ($entry.action -eq 'run') {
        $logon = New-ScheduledTaskTrigger -AtLogOn -User $owner
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
        $triggers = @($logon,$trigger)
        $taskSettings = $settings
    } else {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        $daily = New-ScheduledTaskTrigger -Daily -At ([DateTime]::Today.AddHours($config.daily_hour).AddMinutes($config.daily_minute))
        $repeated = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 59)
        $daily.Repetition = $repeated.Repetition
        $triggers = @($daily)
        # A real accepted Agent run may take time; do not kill it after 2 min.
        $taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    }
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $taskSettings -Principal $principal -Force | Out-Null
}
if ($Start) { Start-ScheduledTask -TaskName 'EaselHealthControl' }
@{installed=$true;release=$release;manifest_sha256=$digest;runtime=$runtimePath;tasks=@('EaselHealthControl','EaselHealthDaily');daily_started=$false} | ConvertTo-Json -Compress
