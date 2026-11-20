[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$FilePath,
    [AllowEmptyCollection()][AllowEmptyString()][string[]]$ArgumentList = @(),
    [string]$WorkingDirectory,
    [string[]]$MatchExecutablePath = @(),
    [ValidateRange(0,64)][int]$DesktopNumber = 0,
    [ValidateRange(1,300)][double]$TimeoutSeconds = 45,
    [ValidateRange(0,120)][double]$ObserveSeconds = 10,
    [ValidateRange(10,500)][int]$PollIntervalMs = 20,
    [switch]$AllowNewWindowsInExistingProcess,
    [Parameter(Mandatory)][string]$StatePath
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'desktop_launch.ps1')
$result = Start-AppOnDesktop @PSBoundParameters
$result | ConvertTo-Json -Depth 10
