<#
.SYNOPSIS
  Build OpenJuiceMonitor.exe with the C# compiler that ships with Windows (.NET Framework 4.x).
  No SDK or Visual Studio needed.

.DESCRIPTION
  Writes the exe to %LOCALAPPDATA%\OpenJuice\OpenJuiceMonitor.exe, next to the status.json it
  reads. -Run starts it afterwards. -Shortcut adds a Start menu shortcut, which is also what gives
  the monitor's notifications its name and icon instead of a generic one.

.EXAMPLE
  .\build_monitor.ps1 -Run
#>
param(
    [string]$Out = (Join-Path $env:LOCALAPPDATA 'OpenJuice\OpenJuiceMonitor.exe'),
    [switch]$Run,
    [switch]$Shortcut
)
$ErrorActionPreference = 'Stop'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path $csc)) { throw 'csc.exe not found; .NET Framework 4.x is required.' }
New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
# OpenJuiceMonitor.ico is the exe's own icon (Explorer, shortcuts). Regenerate it after changing the
# drawing with:  OpenJuiceMonitor.exe --file-icon OpenJuiceMonitor.ico
& $csc /nologo /target:winexe /optimize+ "/out:$Out" "/win32icon:$(Join-Path $PSScriptRoot 'OpenJuiceMonitor.ico')" `
    /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll /r:System.Web.Extensions.dll `
    (Join-Path $PSScriptRoot 'OpenJuiceMonitor.cs')
if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }
Write-Host "Built $Out"
# The charge-complete chime is Windows' "Print Complete" sound event, which ships with no sound
# assigned. Give it the stock file, unless the user has already chosen something.
$evt = 'HKCU:\AppEvents\Schemes\Apps\.Default\PrintComplete\.Current'
$wav = Join-Path $env:WINDIR 'Media\Windows Print complete.wav'
if (-not (Test-Path $evt)) { New-Item -Path $evt -Force | Out-Null }
if (-not (Get-ItemProperty -Path $evt).'(default)' -and (Test-Path $wav)) {
    Set-ItemProperty -Path $evt -Name '(default)' -Value $wav
    Write-Host "Print Complete sound set to $wav"
}
if ($Shortcut) {
    $lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'OpenJuice Monitor.lnk'
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sc.TargetPath = $Out
    $sc.WorkingDirectory = Split-Path $Out
    $sc.Description = 'Status window and tray icon for the JuiceBox helper'
    $sc.Save()
    Write-Host "Shortcut $lnk"
}
if ($Run) { Start-Process $Out }
