<#
.SYNOPSIS
  Build OpenJuiceMonitor.exe with the C# compiler that ships with Windows (.NET Framework 4.x).
  No SDK or Visual Studio needed.

.DESCRIPTION
  Writes the exe to %LOCALAPPDATA%\OpenJuice\OpenJuiceMonitor.exe, next to the status.json it
  reads. -Run starts it afterwards.

.EXAMPLE
  .\build_monitor.ps1 -Run
#>
param(
    [string]$Out = (Join-Path $env:LOCALAPPDATA 'OpenJuice\OpenJuiceMonitor.exe'),
    [switch]$Run
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
if ($Run) { Start-Process $Out }
