[CmdletBinding()]
param([Alias("n")][int]$Lines = 80, [Alias("f")][switch]$Follow, [switch]$Out, [switch]$Err, [string]$Job, [switch]$Help)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if ($Help) { Write-Host "Usage: logs_windows.bat [--lines N] [--follow] [--out|--err] [--job TASK_ID]"; exit 0 }
if ($Lines -lt 1) { $Lines = 80 }
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = if ($env:PPT_SERVICE_LOG_DIR) { $env:PPT_SERVICE_LOG_DIR } else { Join-Path $RootDir "runtime" }
$StdoutLog = if ($env:PPT_SERVICE_STDOUT_LOG) { $env:PPT_SERVICE_STDOUT_LOG } else { Join-Path $LogDir "service_api.out.log" }
$StderrLog = if ($env:PPT_SERVICE_STDERR_LOG) { $env:PPT_SERVICE_STDERR_LOG } else { Join-Path $LogDir "service_api.err.log" }
$JobsDir = if ($env:PPT_SERVICE_JOBS_DIR) { $env:PPT_SERVICE_JOBS_DIR } else { Join-Path $RootDir "service_data\jobs" }
if ($Job) { if ($Job -match "[\\\/]" -or $Job.Contains("..") -or $Job.Trim() -eq "") { throw "Unsafe task id: $Job" }; $targets = @((Join-Path (Join-Path $JobsDir $Job) "run.log")) }
elseif ($Out -and -not $Err) { $targets = @($StdoutLog) }
elseif ($Err -and -not $Out) { $targets = @($StderrLog) }
else { $targets = @($StdoutLog, $StderrLog) }
# The detached launcher and task storage both write UTF-8 logs.
$existing = @($targets | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
foreach ($target in $targets) { if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { Write-Host "[WARN] Log file not found: $target" } }
if (-not $existing) { Write-Host "[INFO] No log files available yet."; exit 0 }
$LogEncoding = "UTF8"
foreach ($target in $existing) { Write-Host "===== $target ====="; Get-Content -LiteralPath $target -Tail $Lines -Encoding $LogEncoding }
if (-not $Follow) { exit 0 }
Write-Host "[INFO] Following logs. Press Ctrl+C to stop."
Get-Content -LiteralPath $existing[0] -Tail 0 -Wait -Encoding $LogEncoding
