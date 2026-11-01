[CmdletBinding(SupportsShouldProcess)]
param([switch]$Start)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$pythonPath=Join-Path $projectRoot '.runtime/workbench-python/Scripts/pythonw.exe'
$launcherPath=Join-Path $projectRoot 'health_launcher.pyw'
$owner=Get-ScheduledTask -TaskName 'AINewsDesk'
if ($owner.Principal.LogonType -ne 'Interactive' -or $owner.Actions.Count -ne 1 -or
    [IO.Path]::GetFullPath($owner.Actions[0].WorkingDirectory) -ne $projectRoot -or
    [IO.Path]::GetFullPath($owner.Actions[0].Execute) -ne $pythonPath -or
    $owner.Actions[0].Arguments -ne ('"'+(Join-Path $projectRoot 'launcher.pyw')+'"')) {
    throw 'The existing workbench task owner or action does not match.'
}
$taskName='AINewsDeskHealth'
$existing=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and ($existing.Principal.UserId -ne $owner.Principal.UserId -or
    $existing.Principal.LogonType -ne $owner.Principal.LogonType -or
    $existing.Actions.Count -ne 1 -or $existing.Actions[0].Execute -ne $pythonPath -or
    $existing.Actions[0].Arguments -ne ('"'+$launcherPath+'"') -or
    [IO.Path]::GetFullPath($existing.Actions[0].WorkingDirectory) -ne $projectRoot)) {
    throw 'Refusing to overwrite a different health task.'
}
if ($PSCmdlet.ShouldProcess($taskName,'Configure independent bounded health checks for the existing credential owner')) {
    $state=Join-Path $projectRoot '.local/workbench-deployment'
    New-Item -ItemType Directory -Force $state | Out-Null
    if ($existing) {
        $backup=Join-Path $state ('health-task-before-'+(Get-Date -Format 'yyyyMMdd-HHmmss-ffff')+'.xml')
        Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath $backup -Encoding utf8
    }
    $periodic=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $periodic.Repetition.StopAtDurationEnd=$false
    $logon=New-ScheduledTaskTrigger -AtLogOn -User $owner.Principal.UserId
    $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
      -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
      -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $settings.IdleSettings.StopOnIdleEnd=$false
    $action=New-ScheduledTaskAction -Execute $pythonPath -Argument ('"'+$launcherPath+'"') -WorkingDirectory $projectRoot
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $owner.Principal `
      -Trigger @($logon,$periodic) -Settings $settings -Force | Out-Null
    if ($Start) {Start-ScheduledTask -TaskName $taskName}
    [pscustomobject]@{status='configured';task=$taskName;owner=$owner.Principal.UserId;interval='PT1M';jobLimit='PT2M';businessProcessesStopped=$false} | ConvertTo-Json -Compress
}
