param([Parameter(Mandatory)][string]$WorkDir)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\desktop_launch.ps1')
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
$started = [datetime]::UtcNow
$app = Join-Path $WorkDir 'app.exe'
$otherCopy = Join-Path $WorkDir 'other\app.exe'
$script:assertions = 0
function Assert($value, $message) { $script:assertions++; if (-not $value) { throw $message } }
function Window([long]$Handle, [int]$ProcessId, [datetime]$Start, [string]$Path = $app) {
    $processKey = '{0}:{1}' -f $ProcessId, $Start.Ticks
    [pscustomobject]@{Handle=$Handle;ProcessId=$ProcessId;StartedUtc=$Start;ExecutablePath=$Path;Visible=$true;Owner=0;ToolWindow=$false;ProcessKey=$processKey;Key=('{0}:{1}' -f $Handle,$processKey)}
}
$old = Window 100 1 $started.AddHours(-1)
$hidden = Window 101 1 $started.AddHours(-1)
$hidden.Visible = $false
$baseline = [pscustomobject]@{ Processes=@([pscustomobject]@{Key=$old.ProcessKey}); Windows=@($old,$hidden) }
$destination = [pscustomobject]@{OriginalCurrentId='source';Target=[pscustomobject]@{Id='target';Number=2};Created=$false}
function State {
    New-DesktopLaunchState -Controller $null -Destination $destination -Baseline $baseline -ExecutablePaths @($app) -StartedUtc $started -StatePath (Join-Path $WorkDir ([guid]::NewGuid().ToString('N')+'.json'))
}
$state = State
Assert (-not (Test-DesktopLaunchCandidate $state $old)) 'A preexisting window must be excluded.'
$hidden.Visible = $true
Assert (-not (Test-DesktopLaunchCandidate $state $hidden)) 'Showing a preexisting hidden window does not make it new.'
$newInOld = Window 102 1 $started.AddHours(-1)
Assert (-not (Test-DesktopLaunchCandidate $state $newInOld)) 'Existing-process windows require explicit opt-in.'
$state.Journal.AllowNewWindowsInExistingProcess = $true
Assert (Test-DesktopLaunchCandidate $state $newInOld) 'Opt-in allows a new HWND in the baseline process.'
Assert (-not (Test-DesktopLaunchCandidate $state $old)) 'Opt-in still excludes existing HWNDs.'
$state.Journal.AllowNewWindowsInExistingProcess = $false
Assert (-not (Test-DesktopLaunchCandidate $state (Window 200 2 $started.AddSeconds(1) $otherCopy))) 'Same filename in another install must not match.'
Assert (-not (Test-DesktopLaunchCandidate $state (Window 200 2 $started.AddHours(-1)))) 'Unseen old processes must fail the launch-time boundary.'
Assert (Test-DesktopLaunchCandidate $state (Window 200 2 $started.AddSeconds(1))) 'A new process at the exact path must match.'
Assert (Test-DesktopLaunchCandidate $state (Window 100 1 $started.AddSeconds(1))) 'Reused PID/HWND with a new process start time must have a new identity.'
$notVisible = Window 201 2 $started.AddSeconds(1); $notVisible.Visible=$false
Assert (-not (Test-DesktopLaunchCandidate $state $notVisible)) 'Hidden helper windows must not be moved.'
$owned = Window 202 2 $started.AddSeconds(1); $owned.Owner=100
Assert (-not (Test-DesktopLaunchCandidate $state $owned)) 'Owned popup windows must not be treated as independent app windows.'
$tool = Window 203 2 $started.AddSeconds(1); $tool.ToolWindow=$true
Assert (-not (Test-DesktopLaunchCandidate $state $tool)) 'Tool windows must be excluded.'

$script:locations = @{}
$script:moveCount = 0
$script:mode = 'transient'
$script:attempts = 0
function Get-DesktopLaunchLocation($Controller, [long]$Handle) {
    $id = if ($script:locations.ContainsKey($Handle)) {$script:locations[$Handle]} else {'source'}
    [pscustomobject]@{DesktopId=$id;OnCurrentDesktop=($id -eq 'source');CurrentDesktopId='source'}
}
function Invoke-DesktopLaunchMove($Controller, $Window, [string]$DesktopId) {
    $disk = Get-Content -LiteralPath $script:activeState.Journal.StatePath -Raw | ConvertFrom-Json
    Assert (@($disk.Windows | Where-Object Key -eq $Window.Key).Count -eq 1) 'Persist the exact identity before calling the move API.'
    $script:attempts++
    if ($script:mode -eq 'transient' -and $script:attempts -eq 1) { throw (New-Object Runtime.InteropServices.COMException('View not registered.', -2147024809)) }
    if ($script:mode -eq 'denied') { throw (New-Object Runtime.InteropServices.COMException('Denied.', -2147024891)) }
    $script:locations[$Window.Handle] = $DesktopId
    $script:moveCount++
    [pscustomobject]@{CurrentDesktopBefore='source';CurrentDesktopAfter='source'}
}
$script:activeState = State
$watch = [Diagnostics.Stopwatch]::StartNew()
$window = Window 200 2 $started.AddSeconds(1)
$snapshot = [pscustomobject]@{Windows=@($window)}
Update-DesktopLaunchState $script:activeState $snapshot $watch.Elapsed.TotalMilliseconds $watch
Assert ($script:moveCount -eq 0 -and $script:activeState.Journal.Windows[0].Status -eq 'waiting_for_shell_view') 'A registration race must remain pending.'
Update-DesktopLaunchState $script:activeState $snapshot $watch.Elapsed.TotalMilliseconds $watch
Assert ($script:moveCount -eq 1 -and $script:activeState.Completed.Count -eq 1) 'The newly registered view should move and verify.'
Update-DesktopLaunchState $script:activeState $snapshot $watch.Elapsed.TotalMilliseconds $watch
Assert ($script:moveCount -eq 1) 'Repeated observations must not keep moving the same window.'
$script:mode='success'
$replacement=Window 201 3 $started.AddSeconds(2)
Update-DesktopLaunchState $script:activeState ([pscustomobject]@{Windows=@($replacement)}) $watch.Elapsed.TotalMilliseconds $watch
Assert ($script:moveCount -eq 2) 'A replacement process/window must also move.'
$result=Complete-DesktopLaunchState $script:activeState ([pscustomobject]@{Windows=@($replacement)})
Assert ($result.LiveVerifiedWindows -eq 1 -and $result.ClosedMovedWindows -eq 1) 'Distinguish a closed splash from the live replacement window.'
$script:locations[[long]201]='source'
$rejected=$false
try { Complete-DesktopLaunchState $script:activeState ([pscustomobject]@{Windows=@($replacement)}) | Out-Null } catch {$rejected=$true}
Assert ($rejected -and $script:moveCount -eq 2) 'A later desktop change must be reported without fighting it.'

$script:activeState=State; $script:mode='denied'
$rejected=$false
try { Update-DesktopLaunchState $script:activeState ([pscustomobject]@{Windows=@((Window 300 4 $started.AddSeconds(3)))}) 0 $watch } catch {$rejected=$true}
Assert ($rejected -and $script:activeState.Journal.Windows[0].Status -eq 'failed') 'Access denial must stop immediately rather than retry as a registration race.'
$existing=$script:activeState.Journal.StatePath
$hash=(Get-FileHash -LiteralPath $existing).Hash
$rejected=$false
try { New-DesktopLaunchState -Controller $null -Destination $destination -Baseline $baseline -ExecutablePaths @($app) -StartedUtc $started -StatePath $existing | Out-Null } catch {$rejected=$true}
Assert ($rejected -and (Get-FileHash -LiteralPath $existing).Hash -eq $hash) 'A journal from another run must not be overwritten.'

$script:activeState=State; $script:mode='success'
$script:activeState.Journal.StatePath=Join-Path $WorkDir ('absent-'+[guid]::NewGuid().ToString('N')+'\state.json')
$before=$script:moveCount; $rejected=$false
$ErrorActionPreference='Continue'
try { Update-DesktopLaunchState $script:activeState ([pscustomobject]@{Windows=@((Window 400 5 $started.AddSeconds(4)))}) 0 $watch } catch {$rejected=$true}
finally {$ErrorActionPreference='Stop'}
Assert ($rejected -and $script:moveCount -eq $before) 'Journal write failure must prevent the move.'
$watch.Stop()
"PASS $script:assertions launch-policy assertions"
