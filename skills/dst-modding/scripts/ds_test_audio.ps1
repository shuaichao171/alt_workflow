# Dot-source once from a Windows single-player test driver. No audio changes on load.
function Initialize-DsTestAudioNative {
    if ('DsTestAudio.CoreAudio' -as [type]) { return }
    Add-Type -Path (Join-Path $PSScriptRoot 'ds_test_audio.cs')
}

function Get-DsTestAudioSessions {
    Initialize-DsTestAudioNative
    [DsTestAudio.CoreAudio]::Snapshot()
}

function Set-DsTestAudioSessionMute {
    param($Session, [bool]$Muted)
    Initialize-DsTestAudioNative
    [DsTestAudio.CoreAudio]::SetMute($Session.EndpointId, $Session.InstanceId, [uint32]$Session.ProcessId, $Muted)
}

function Get-DsTestAudioProcesses {
    foreach ($process in @(Get-Process -Name dontstarve_steam -ErrorAction SilentlyContinue)) {
        try {
            [pscustomobject]@{
                ProcessId = $process.Id
                Executable = $process.Path
                StartedUtc = $process.StartTime.ToUniversalTime().ToString('o')
            }
        } catch {
            # The short-lived Steam launcher can exit between enumeration and inspection.
            Write-Verbose "Could not inspect process $($process.Id): $_"
        }
    }
}

function Save-DsTestAudioState {
    param([Parameter(Mandatory)]$State)
    $temporary = $State.StatePath + '.tmp'
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8 -ErrorAction Stop
    Move-Item -LiteralPath $temporary -Destination $State.StatePath -Force -ErrorAction Stop
}

function New-DsTestAudioState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$GameExecutable,
        [Parameter(Mandatory)][datetime]$StartedAfterUtc,
        [Parameter(Mandatory)][string]$StatePath
    )
    $executable = [IO.Path]::GetFullPath($GameExecutable)
    if ([IO.Path]::GetFileName($executable) -ine 'dontstarve_steam.exe') {
        throw 'Audio control is restricted to the single-player dontstarve_steam.exe.'
    }
    $path = [IO.Path]::GetFullPath($StatePath)
    if (Test-Path -LiteralPath $path) { throw 'Audio state already exists; restore it or choose a fresh run path.' }
    if (-not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($path)) -PathType Container)) {
        throw 'Create the test work directory before creating audio state.'
    }
    $state = [pscustomobject]@{
        Version = 1
        GameExecutable = $executable
        StartedAfterUtc = $StartedAfterUtc.ToUniversalTime().ToString('o')
        StatePath = $path
        Entries = @()
        Complete = $false
    }
    Save-DsTestAudioState $state
    return $state
}

function Read-DsTestAudioState {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$StatePath)
    $path = [IO.Path]::GetFullPath($StatePath)
    $state = Get-Content -LiteralPath $path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    if ($state.Version -ne 1 -or [IO.Path]::GetFileName($state.GameExecutable) -ine 'dontstarve_steam.exe') {
        throw 'Unsupported audio state.'
    }
    $state.StatePath = $path
    return $state
}

function Update-DsTestAudioMute {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$State)
    if ($State.Complete) { throw 'This audio run has already been restored.' }
    $after = [datetime]::Parse($State.StartedAfterUtc).ToUniversalTime()
    $owned = @{}
    foreach ($process in @(Get-DsTestAudioProcesses)) {
        if ($process.Executable -ieq $State.GameExecutable -and
            [datetime]::Parse($process.StartedUtc).ToUniversalTime() -ge $after) {
            $owned[[uint32]$process.ProcessId] = $process
        }
    }
    $matched = 0
    $confirmed = 0
    foreach ($session in @(Get-DsTestAudioSessions)) {
        if (-not $owned.ContainsKey([uint32]$session.ProcessId)) { continue }
        $matched++
        $entry = @($State.Entries | Where-Object {
            $_.EndpointId -eq $session.EndpointId -and $_.InstanceId -eq $session.InstanceId
        }) | Select-Object -First 1
        if ($null -eq $entry) {
            $original = [bool]$session.Muted
            # Windows can carry a test's temporary mute into a replacement PID.
            # Reuse this run's first application/endpoint baseline for that PID.
            $prior = @($State.Entries | Where-Object { $_.EndpointId -eq $session.EndpointId })
            if ($prior.Count -gt 0 -and -not @($prior | Where-Object { $_.ProcessId -eq $session.ProcessId })) {
                $original = [bool]$prior[0].OriginalMuted
            }
            $entry = [pscustomobject]@{
                EndpointId = $session.EndpointId
                InstanceId = $session.InstanceId
                ProcessId = $session.ProcessId
                ProcessStartedUtc = $owned[[uint32]$session.ProcessId].StartedUtc
                OriginalMuted = $original
                Restored = $false
                Applied = $false
            }
            $State.Entries = @($State.Entries) + @($entry)
            # Persist recovery data before the first write to Windows.
            Save-DsTestAudioState $State
        }
        if ($session.Muted -or (Set-DsTestAudioSessionMute -Session $session -Muted $true)) {
            $entry.Applied = $true
            $confirmed++
            Save-DsTestAudioState $State
        }
    }
    [pscustomobject]@{ OwnedProcesses = $owned.Count; MatchedSessions = $matched; ConfirmedMuted = $confirmed }
}

function Restore-DsTestAudioMute {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$State)
    if ($State.Complete) { return [pscustomobject]@{ Complete = $true; Pending = 0 } }
    $sessions = @(Get-DsTestAudioSessions)
    $pending = 0
    foreach ($entry in @($State.Entries)) {
        if ($entry.Restored) { continue }
        $session = @($sessions | Where-Object {
            $_.EndpointId -eq $entry.EndpointId -and $_.InstanceId -eq $entry.InstanceId -and
            $_.ProcessId -eq $entry.ProcessId
        }) | Select-Object -First 1
        if ($null -eq $session) {
            # Do not claim restoration when the device/session is no longer reachable.
            $pending++
            continue
        }
        if ($session.Muted -eq $entry.OriginalMuted -or
            (Set-DsTestAudioSessionMute -Session $session -Muted ([bool]$entry.OriginalMuted))) {
            $entry.Restored = $true
            Save-DsTestAudioState $State
        } else { $pending++ }
    }
    $State.Complete = $pending -eq 0
    Save-DsTestAudioState $State
    [pscustomobject]@{ Complete = $State.Complete; Pending = $pending }
}
