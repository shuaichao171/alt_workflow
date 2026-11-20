# Loading this library does not launch applications or change desktops.
function Initialize-DesktopLaunchNative {
    if ($env:OS -ne 'Windows_NT' -or [IntPtr]::Size -ne 8) { throw 'Use 64-bit Windows PowerShell or PowerShell 7 on Windows.' }
    $build = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuild
    if ($build -ne '19045') { throw "Unsupported Windows build $build; no application was launched. This adapter is verified for Windows 10 22H2 build 19045." }
    if (-not ('AltWorkflow.DesktopLaunch.Native' -as [type])) { Add-Type -Path (Join-Path $PSScriptRoot 'virtual_desktop.cs') }
}

function Get-DesktopLaunchSnapshot([string[]]$ExecutablePaths) {
    [AltWorkflow.DesktopLaunch.Native]::Capture($ExecutablePaths)
}

function Get-DesktopLaunchLocation($Controller, [long]$Handle) {
    $location = $Controller.Locate($Handle)
    $current = @($Controller.Inventory() | Where-Object Current)
    [pscustomobject]@{ DesktopId = $location.DesktopId; OnCurrentDesktop = $location.OnCurrentDesktop; CurrentDesktopId = $current[0].Id }
}

function Invoke-DesktopLaunchMove($Controller, $Window, [string]$DesktopId) {
    $Controller.Move($Window, $DesktopId)
}

function Save-DesktopLaunchState($State, [switch]$CreateNew) {
    $ErrorActionPreference = 'Stop'
    $path = $State.Journal.StatePath
    $json = $State.Journal | ConvertTo-Json -Depth 10
    $encoding = New-Object Text.UTF8Encoding($false)
    if ($CreateNew) {
        $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        try { $bytes = $encoding.GetBytes($json); $stream.Write($bytes, 0, $bytes.Length); $stream.Flush() }
        finally { $stream.Dispose() }
        return
    }
    $temporary = $path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporary, $json, $encoding)
    [IO.File]::Replace($temporary, $path, [NullString]::Value)
}

function New-DesktopLaunchState {
    param($Controller, $Destination, $Baseline, [string[]]$ExecutablePaths, [datetime]$StartedUtc,
        [string]$StatePath, [bool]$AllowNewWindowsInExistingProcess = $false)
    $ErrorActionPreference = 'Stop'
    $journal = [pscustomobject][ordered]@{
        SchemaVersion = 1; StatePath = [IO.Path]::GetFullPath($StatePath); Status = 'prepared'
        StartedUtc = $StartedUtc.ToUniversalTime().ToString('o'); LauncherExecutable = $null; ArgumentCount = 0
        InitialProcessId = 0; InitialProcess = $null; NewProcesses = @()
        ExecutablePaths = @($ExecutablePaths); Destination = $Destination
        AllowNewWindowsInExistingProcess = $AllowNewWindowsInExistingProcess
        BaselineProcessKeys = @($Baseline.Processes | ForEach-Object Key)
        BaselineWindowKeys = @($Baseline.Windows | ForEach-Object Key)
        Windows = @(); FirstVerifiedMoveMs = $null; FinishedUtc = $null; Failure = $null
        LiveVerifiedWindows = 0; ClosedMovedWindows = 0
    }
    $state = [pscustomobject]@{ Journal = $journal; Controller = $Controller; Records = @{}; Completed = @{}; SeenProcesses = @{} }
    Save-DesktopLaunchState $state -CreateNew
    $state
}

function Test-DesktopLaunchCandidate($State, $Window) {
    $journal = $State.Journal
    if (-not $Window.Handle -or -not $Window.Visible -or $Window.Owner -ne 0 -or $Window.ToolWindow) { return $false }
    if ($journal.ExecutablePaths -notcontains $Window.ExecutablePath) { return $false }
    if ($journal.BaselineWindowKeys -contains $Window.Key) { return $false }
    if ($journal.BaselineProcessKeys -contains $Window.ProcessKey) { return [bool]$journal.AllowNewWindowsInExistingProcess }
    ([datetime]$Window.StartedUtc).ToUniversalTime() -ge ([datetime]$journal.StartedUtc).ToUniversalTime()
}

function Get-DesktopLaunchComError($ErrorRecord) {
    $exception = $ErrorRecord.Exception
    while ($null -ne $exception) {
        if ($exception -is [Runtime.InteropServices.COMException]) { return $exception }
        $exception = $exception.InnerException
    }
    return $null
}

function Update-DesktopLaunchState($State, $Snapshot, [double]$ElapsedMs, $Stopwatch) {
    $ErrorActionPreference = 'Stop'
    $seen = @{}
    foreach ($process in @($Snapshot.Processes)) {
        if ($null -eq $process -or $State.SeenProcesses.ContainsKey($process.Key)) { continue }
        if ($State.Journal.ExecutablePaths -notcontains $process.ExecutablePath -or $State.Journal.BaselineProcessKeys -contains $process.Key) { continue }
        if (([datetime]$process.StartedUtc).ToUniversalTime() -lt ([datetime]$State.Journal.StartedUtc).ToUniversalTime()) { continue }
        $State.Journal.NewProcesses += $process
        $State.SeenProcesses[$process.Key] = $true
    }
    foreach ($window in @($Snapshot.Windows)) {
        if (-not (Test-DesktopLaunchCandidate $State $window)) { continue }
        $seen[$window.Key] = $true
        if ($State.Completed.ContainsKey($window.Key)) { continue }
        if (-not $State.Records.ContainsKey($window.Key)) {
            $entry = [pscustomobject][ordered]@{
                Key = $window.Key; Window = $window; FirstDetectedMs = $ElapsedMs; Attempts = 0
                Status = 'pending'; DesktopIdBefore = $null; DesktopIdAfter = $null
                MoveCompletedMs = $null; DetectionToMoveMs = $null; MoveApiMs = $null
                CurrentDesktopBefore = $null; CurrentDesktopAfter = $null; Error = $null
            }
            $State.Records[$window.Key] = $entry
            $State.Journal.Windows += $entry
        }
        $entry = $State.Records[$window.Key]
        $entry.Attempts++
        # Persist the exact window identity before any move, including a retry.
        Save-DesktopLaunchState $State
        $before = $null
        try {
            $before = Get-DesktopLaunchLocation $State.Controller $window.Handle
            $entry.DesktopIdBefore = $before.DesktopId
            $callMs = $Stopwatch.Elapsed.TotalMilliseconds
            if ($before.DesktopId -ne $State.Journal.Destination.Target.Id) {
                $move = Invoke-DesktopLaunchMove $State.Controller $window $State.Journal.Destination.Target.Id
                $entry.CurrentDesktopBefore = $move.CurrentDesktopBefore
                $entry.CurrentDesktopAfter = $move.CurrentDesktopAfter
                $entry.Status = 'moved'
            } else {
                $entry.Status = 'already_on_target'
                $entry.CurrentDesktopBefore = $before.CurrentDesktopId
                $entry.CurrentDesktopAfter = $before.CurrentDesktopId
            }
            $doneMs = $Stopwatch.Elapsed.TotalMilliseconds
            $after = Get-DesktopLaunchLocation $State.Controller $window.Handle
            if ($after.DesktopId -ne $State.Journal.Destination.Target.Id) { throw 'Desktop ID verification failed.' }
            if ($after.OnCurrentDesktop -and $after.CurrentDesktopId -ne $after.DesktopId) { throw 'Window remains visible on the current desktop, possibly pinned to all desktops; pinning was not changed.' }
        } catch {
            $comError = Get-DesktopLaunchComError $_
            # A visible HWND can precede shell application-view registration.
            $retryable = $null -ne $comError -and $comError.ErrorCode -in @(-2147024809, -2147023728, -2147467259)
            $entry.Error = $_.Exception.Message
            if ($retryable -and $ElapsedMs - $entry.FirstDetectedMs -lt 2000) {
                $entry.Status = 'waiting_for_shell_view'; Save-DesktopLaunchState $State; continue
            }
            $entry.Status = 'failed'; Save-DesktopLaunchState $State; throw
        }
        $entry.DesktopIdAfter = $after.DesktopId
        $entry.MoveCompletedMs = $doneMs
        $entry.DetectionToMoveMs = $doneMs - $entry.FirstDetectedMs
        $entry.MoveApiMs = $doneMs - $callMs
        $entry.Error = $null
        $State.Completed[$window.Key] = $entry
        if ($null -eq $State.Journal.FirstVerifiedMoveMs) { $State.Journal.FirstVerifiedMoveMs = $doneMs }
        Save-DesktopLaunchState $State
    }
    foreach ($key in @($State.Records.Keys)) {
        $entry = $State.Records[$key]
        if (-not $seen.ContainsKey($key) -and -not $State.Completed.ContainsKey($key) -and $entry.Status -ne 'failed') {
            $entry.Status = 'disappeared_before_move'
        }
    }
}

function Complete-DesktopLaunchState($State, $Snapshot) {
    $ErrorActionPreference = 'Stop'
    $State.Journal.LiveVerifiedWindows = 0
    $State.Journal.ClosedMovedWindows = 0
    $current = @{}
    foreach ($window in @($Snapshot.Windows)) { $current[$window.Key] = $window }
    foreach ($key in @($State.Completed.Keys)) {
        if (-not $current.ContainsKey($key)) { $State.Journal.ClosedMovedWindows++; continue }
        $entry = $State.Completed[$key]
        $location = Get-DesktopLaunchLocation $State.Controller $entry.Window.Handle
        if ($location.DesktopId -ne $State.Journal.Destination.Target.Id -or ($location.OnCurrentDesktop -and $location.CurrentDesktopId -ne $location.DesktopId)) {
            throw 'A moved window changed desktop or remained pinned during observation; it was not moved again.'
        }
        $State.Journal.LiveVerifiedWindows++
    }
    $pending = @($State.Journal.Windows | Where-Object { $_.Status -in @('pending','waiting_for_shell_view','failed') })
    if ($pending.Count) { throw 'Some detected windows could not be moved; inspect the state file.' }
    $State.Journal.Status = if ($State.Journal.LiveVerifiedWindows -gt 0) { 'completed' } else { 'moved_then_closed' }
    $State.Journal.FinishedUtc = [datetime]::UtcNow.ToString('o')
    Save-DesktopLaunchState $State
    $State.Journal
}

function Start-AppOnDesktop {
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
    $file = Get-Item -LiteralPath $FilePath -ErrorAction Stop
    if ($file.PSIsContainer -or $file.Extension -ine '.exe') { throw 'FilePath must identify an existing executable, not a command, URI or shortcut.' }
    $FilePath = $file.FullName
    $paths = if ($MatchExecutablePath.Count) { @($MatchExecutablePath) } else { @($FilePath) }
    $paths = @(foreach ($path in $paths) {
        $item = Get-Item -LiteralPath $path -ErrorAction Stop
        if ($item.PSIsContainer -or $item.Extension -ine '.exe') { throw 'Every matched path must identify an existing executable.' }
        $item.FullName
    })
    if (-not $WorkingDirectory) { $WorkingDirectory = $file.DirectoryName }
    $working = Get-Item -LiteralPath $WorkingDirectory -ErrorAction Stop
    if (-not $working.PSIsContainer) { throw 'WorkingDirectory must be a directory.' }
    $StatePath = [IO.Path]::GetFullPath($StatePath)
    if (-not [IO.Directory]::Exists([IO.Path]::GetDirectoryName($StatePath))) { throw 'Create the task work directory before calling the launcher.' }
    if (Test-Path -LiteralPath $StatePath) { throw 'StatePath already exists; use a fresh per-run filename.' }
    Initialize-DesktopLaunchNative
    $arguments = [AltWorkflow.DesktopLaunch.Native]::BuildArguments($ArgumentList)
    $controller = New-Object AltWorkflow.DesktopLaunch.Controller
    $destination = $controller.EnsureDestination($DesktopNumber)
    $baseline = Get-DesktopLaunchSnapshot $paths
    $started = [datetime]::UtcNow
    $state = New-DesktopLaunchState -Controller $controller -Destination $destination -Baseline $baseline -ExecutablePaths $paths -StartedUtc $started -StatePath $StatePath -AllowNewWindowsInExistingProcess ([bool]$AllowNewWindowsInExistingProcess)
    $state.Journal.LauncherExecutable = $FilePath
    $state.Journal.ArgumentCount = $ArgumentList.Count
    $state.Journal.Status = 'launching'
    Save-DesktopLaunchState $state
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $FilePath; $info.Arguments = $arguments; $info.WorkingDirectory = $working.FullName
    $info.UseShellExecute = $false; $info.WindowStyle = [Diagnostics.ProcessWindowStyle]::Normal
    $watch = [Diagnostics.Stopwatch]::StartNew()
    try {
        $initial = [Diagnostics.Process]::Start($info)
        $state.Journal.InitialProcessId = $initial.Id
        $state.Journal.InitialProcess = [AltWorkflow.DesktopLaunch.Native]::ReadProcess($initial.Id)
        $initial.Dispose()
        Save-DesktopLaunchState $state
        while ($true) {
            $snapshot = Get-DesktopLaunchSnapshot $paths
            Update-DesktopLaunchState $state $snapshot $watch.Elapsed.TotalMilliseconds $watch
            if ($null -ne $state.Journal.FirstVerifiedMoveMs) {
                if ($watch.Elapsed.TotalMilliseconds - $state.Journal.FirstVerifiedMoveMs -ge $ObserveSeconds * 1000) { break }
            } elseif ($watch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                throw (New-Object TimeoutException('No eligible new window appeared before the launch timeout. Existing windows were not moved.'))
            }
            [Threading.Thread]::Sleep($PollIntervalMs)
        }
        Complete-DesktopLaunchState $state (Get-DesktopLaunchSnapshot $paths)
    } catch {
        $state.Journal.Status = if ($_.Exception -is [TimeoutException]) { 'timed_out' } elseif ($state.Completed.Count -gt 0) { 'partial_failure' } else { 'failed' }
        $state.Journal.Failure = $_.Exception.Message
        $state.Journal.FinishedUtc = [datetime]::UtcNow.ToString('o')
        try { Save-DesktopLaunchState $state } catch { Write-Warning 'Could not update launch journal; retain the previous pending records.' }
        throw
    } finally { $watch.Stop() }
}
