# The desktop credential owner must remain logged in. Keep the existing task
# identity and action; the launcher already holds the single-manager OS lock.
[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$taskName = 'AINewsDesk'
$pythonPath = Join-Path $projectRoot '.runtime/workbench-python/Scripts/pythonw.exe'
$launcherPath = Join-Path $projectRoot 'launcher.pyw'
$task = Get-ScheduledTask -TaskName $taskName
if ($task.Actions.Count -ne 1 -or
    [IO.Path]::GetFullPath($task.Actions[0].Execute) -ne $pythonPath -or
    $task.Actions[0].Arguments -ne ('"' + $launcherPath + '"') -or
    [IO.Path]::GetFullPath($task.Actions[0].WorkingDirectory) -ne $projectRoot) {
    throw 'Refusing to change a task with a different action or project owner.'
}
if ($task.Principal.LogonType -ne 'Interactive') {
    throw 'Expected the existing interactive credential owner; no identity migration is allowed.'
}
$logonTriggers = @($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' })
if ($logonTriggers.Count -ne 1) { throw 'Expected exactly one existing user logon trigger.' }

if ($PSCmdlet.ShouldProcess($taskName, 'Enable continuous one-minute recovery for the existing workbench launcher')) {
    $backupRoot = Join-Path $projectRoot '.local/workbench-deployment/autostart-backups'
    New-Item -ItemType Directory -Force $backupRoot | Out-Null
    $backupPath = Join-Path $backupRoot ((Get-Date -Format 'yyyyMMdd-HHmmss-ffff') + '.xml')
    Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath $backupPath -Encoding utf8
    # No repetition duration means indefinite repetition. Do not replace the
    # task action, principal or original logon trigger, or stop a running task.
    $recovery = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $recovery.Repetition.StopAtDurationEnd = $false
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $settings.IdleSettings.StopOnIdleEnd = $false
    Set-ScheduledTask -TaskName $taskName -Trigger @($logonTriggers + @($recovery)) -Settings $settings | Out-Null
    [pscustomobject]@{ status = 'configured'; task = $taskName; backup = $backupPath; recoveryInterval = 'PT1M'; identityChanged = $false; runningProcessesStopped = $false } | ConvertTo-Json -Compress
}
