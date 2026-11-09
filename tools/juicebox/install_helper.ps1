<#
.SYNOPSIS
  Install, update or remove the OpenJuice JuiceBox helper as a Windows scheduled task.

.DESCRIPTION
  Copies juicebox_helper.py and the two modules it imports to a local folder, because the
  task starts at boot before any network share is mounted. Then registers a task that:
    - starts at boot, and every 5 minutes if it is not already running;
    - runs as the current user whether or not anyone is logged on, without a stored password
      and without administrator rights;
    - never times out, and keeps running on battery.
  Re-running the script updates the copied files and restarts the task.

  -Uninstall first hands the charger back to the vendor cloud, so it is not left pointed at a
  resolver that is about to stop, then removes the task. Config, logs and telemetry are kept.

  Run from an elevated PowerShell: registering a task that runs while logged off needs it.

.EXAMPLE
  .\install_helper.ps1
.EXAMPLE
  .\install_helper.ps1 -Uninstall
#>
param(
    [switch]$Uninstall,
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA 'OpenJuice'),
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
$TaskName = 'OpenJuice JuiceBox helper'
$InstallDir = Join-Path $DataDir 'helper'
$Files = 'juicebox_helper.py', 'juicebox_dns.py', 'juicebox_collector.py'

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this from an elevated PowerShell.'
}
if (-not $Python) { $Python = (Get-Command python.exe -ErrorAction Stop).Source }
if ($Python -like '*\WindowsApps\*') {
    throw "$Python is the Microsoft Store alias, which does not run from a logged-off task. Pass -Python with a real python.exe."
}
$helper = Join-Path $InstallDir 'juicebox_helper.py'
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

function Stop-Helper {
    if ($existing -and $existing.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 2
    }
}

if ($Uninstall) {
    if (Test-Path $helper) {
        Write-Host 'Handing the charger back to the vendor cloud first...'
        & $Python $helper --data-dir $DataDir release
    }
    if ($existing) {
        Stop-Helper
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed the task '$TaskName'."
    }
    Write-Host "Config, logs and telemetry are still in $DataDir"
    return
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Stop-Helper                                    # frees the files and the UDP ports; no hand-back
foreach ($f in $Files) {
    Copy-Item -Path (Join-Path $PSScriptRoot $f) -Destination (Join-Path $InstallDir $f) -Force
}

$esc = { param($s) [Security.SecurityElement]::Escape($s) }
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$start = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
$arguments = "`"$helper`" --data-dir `"$DataDir`" run"
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>OpenJuice: keeps the JuiceBox under local control. DNS redirect, telemetry listener and a watchdog that recovers a hung or rebooted WiFi module. See tools/juicebox/juicebox_helper.py.</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger><Enabled>true</Enabled></BootTrigger>
    <TimeTrigger>
      <Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>$start</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$(& $esc $user)</UserId>
      <LogonType>S4U</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$(& $esc $Python)</Command>
      <Arguments>$(& $esc $arguments)</Arguments>
      <WorkingDirectory>$(& $esc $InstallDir)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed '$TaskName' as $user, running $helper"

$config = Join-Path $DataDir 'helper.json'
if ((Test-Path $config) -and ((Get-Content $config -Raw | ConvertFrom-Json).mode -eq 'released')) {
    Write-Host 'Note: helper.json says mode "released", so the helper will not reattach the charger.'
    Write-Host "      Resume local control with:  python `"$helper`" attach"
}
Write-Host 'Waiting 20 s for the first status...'
Start-Sleep -Seconds 20
& $Python $helper --data-dir $DataDir status
