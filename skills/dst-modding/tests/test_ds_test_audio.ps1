param([Parameter(Mandatory)][string]$WorkDir)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\ds_test_audio.ps1')
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
$game = Join-Path $WorkDir 'game\dontstarve_steam.exe'
$started = [datetime]::UtcNow
$script:processes = @(
    [pscustomobject]@{ProcessId=1;Executable=$game;StartedUtc=$started.AddHours(-1).ToString('o')},
    [pscustomobject]@{ProcessId=2;Executable=$game;StartedUtc=$started.AddSeconds(1).ToString('o')},
    [pscustomobject]@{ProcessId=3;Executable=(Join-Path $WorkDir 'other\dontstarve_steam.exe');StartedUtc=$started.AddSeconds(1).ToString('o')},
    [pscustomobject]@{ProcessId=4;Executable=(Join-Path $WorkDir 'game\dontstarve_steam_x64.exe');StartedUtc=$started.AddSeconds(1).ToString('o')}
)
function New-Session($instance, $process, $muted, $volume = .37) {
    [pscustomobject]@{EndpointId='device-1';InstanceId=$instance;ProcessId=$process;Muted=$muted;Volume=$volume;State=1}
}
$script:sessions = @((New-Session old 1 $false),(New-Session current 2 $false),
    (New-Session already-muted 2 $true),(New-Session other-copy 3 $false),(New-Session together 4 $false))
$script:writes = @()
$script:statePath = Join-Path $WorkDir ('audio-' + [guid]::NewGuid().ToString('N') + '.json')
function Get-DsTestAudioProcesses { $script:processes }
function Get-DsTestAudioSessions { $script:sessions }
function Set-DsTestAudioSessionMute {
    param($Session, [bool]$Muted)
    $onDisk = Get-Content -LiteralPath $script:statePath -Raw | ConvertFrom-Json
    if (-not @($onDisk.Entries | Where-Object {$_.InstanceId -eq $Session.InstanceId})) {
        throw 'Recovery state was not persisted before the audio write.'
    }
    $script:writes += $Session.InstanceId
    $Session.Muted = $Muted
    return $true
}
$script:assertions = 0
function Assert($condition, $message) {
    $script:assertions++
    if (-not $condition) { throw $message }
}
$state = New-DsTestAudioState -GameExecutable $game -StartedAfterUtc $started -StatePath $script:statePath
Assert ($script:writes.Count -eq 0) 'Loading/creating state must not mute anything.'
$result = Update-DsTestAudioMute $state
Assert ($result.OwnedProcesses -eq 1 -and $result.ConfirmedMuted -eq 2) 'Only the owned single-player process is selected.'
Assert (-not $script:sessions[0].Muted) 'A pre-existing user game must not be muted.'
Assert (-not $script:sessions[3].Muted) 'Another install with the same executable name must not be muted.'
Assert (-not $script:sessions[4].Muted) 'Together must not be muted.'
Assert ($script:writes.Count -eq 1) 'Already-muted audio needs no redundant write.'
Update-DsTestAudioMute $state | Out-Null
Assert ($state.Entries[0].OriginalMuted -eq $false) 'Repeated polling must retain the original unmuted state.'
$state = Read-DsTestAudioState $script:statePath
$result = Restore-DsTestAudioMute $state
Assert ($result.Complete) 'All reachable sessions should restore.'
Assert (-not $script:sessions[1].Muted) 'Originally unmuted audio must be unmuted again.'
Assert ($script:sessions[2].Muted) 'Originally muted audio must remain muted.'
Assert ($script:sessions[1].Volume -eq .37) 'Mute/restore must not change volume.'
$writeCount = $script:writes.Count
Restore-DsTestAudioMute $state | Out-Null
Assert ($script:writes.Count -eq $writeCount) 'Restoration must be idempotent.'
$rejected = $false
try { New-DsTestAudioState -GameExecutable $game -StartedAfterUtc $started -StatePath $script:statePath | Out-Null } catch {$rejected=$true}
Assert $rejected 'An existing recovery file must not be overwritten.'
$rejected = $false
try { New-DsTestAudioState -GameExecutable (Join-Path $WorkDir 'dontstarve_steam_x64.exe') -StartedAfterUtc $started -StatePath ($script:statePath+'.bad') | Out-Null } catch {$rejected=$true}
Assert $rejected 'The workflow must reject Together executable paths.'

$script:statePath = Join-Path $WorkDir ('restart-' + [guid]::NewGuid().ToString('N') + '.json')
$script:sessions = @((New-Session first 2 $false))
$state = New-DsTestAudioState -GameExecutable $game -StartedAfterUtc $started -StatePath $script:statePath
Update-DsTestAudioMute $state | Out-Null
$script:processes = @([pscustomobject]@{ProcessId=5;Executable=$game;StartedUtc=$started.AddSeconds(2).ToString('o')})
$script:sessions = @((New-Session replacement 5 $true))
Update-DsTestAudioMute $state | Out-Null
Assert ($state.Entries[1].OriginalMuted -eq $false) 'A replacement PID must not treat inherited test mute as the user baseline.'
$result = Restore-DsTestAudioMute $state
Assert (-not $script:sessions[0].Muted) 'The replacement process must restore to the pre-test mute state.'
Assert (-not $result.Complete -and $result.Pending -eq 1) 'A vanished session must remain a reported recovery item.'
Assert (Test-Path -LiteralPath $script:statePath) 'Incomplete restoration must retain recovery data.'
$script:sessions += (New-Session first 2 $true)
$result = Restore-DsTestAudioMute $state
Assert ($result.Complete) 'Recovery can be retried when a missing session becomes reachable.'

$script:statePath = Join-Path $WorkDir ('save-failure-' + [guid]::NewGuid().ToString('N') + '.json')
$state = New-DsTestAudioState -GameExecutable $game -StartedAfterUtc $started -StatePath $script:statePath
$state.StatePath = Join-Path $WorkDir ('missing-' + [guid]::NewGuid().ToString('N') + '\audio.json')
$script:sessions = @((New-Session unsaved 5 $false))
$writeCount = $script:writes.Count
$rejected = $false
$ErrorActionPreference = 'Continue'
try { Update-DsTestAudioMute $state | Out-Null } catch { $rejected = $true }
finally { $ErrorActionPreference = 'Stop' }
Assert $rejected 'State-file failure must terminate even when the caller allows non-terminating errors.'
Assert ($script:writes.Count -eq $writeCount -and -not $script:sessions[0].Muted) 'Never mute before recovery data is safely saved.'
Write-Output "PASS $script:assertions audio workflow assertions"
