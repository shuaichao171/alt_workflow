param([Parameter(Mandatory)][string]$WorkDir, [switch]$IncludeNotepad)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\desktop_launch.ps1')
Initialize-DesktopLaunchNative
$suiteStarted = [datetime]::UtcNow
$run = Join-Path $WorkDir ([guid]::NewGuid().ToString('N') + ' native test')
New-Item -ItemType Directory -Path $run -Force | Out-Null
$fixture = Join-Path $run 'launch-fixture.exe'
$launcher = Join-Path $run 'launcher-fixture.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'The existing .NET Framework C# compiler was not found.' }
& $compiler /nologo /target:winexe /platform:x64 /reference:System.Windows.Forms.dll /reference:System.Drawing.dll (('/out:')+$fixture) (Join-Path $PSScriptRoot 'launch_fixture.cs')
if ($LASTEXITCODE -ne 0) { throw 'Fixture compilation failed.' }
Copy-Item -LiteralPath $fixture -Destination $launcher
$controller = New-Object AltWorkflow.DesktopLaunch.Controller
$initialDesktop = @($controller.Inventory() | Where-Object Current)[0].Id
$script:assertions = 0
$script:extraOwned = @()
function Assert($value, $message) { $script:assertions++; if (-not $value) { throw $message } }
function Journal([string]$Name) { Join-Path $run ($Name+'.json') }
function Wait-Window([int]$ProcessId) {
    for ($attempt=0; $attempt -lt 200; $attempt++) {
        $windows = @((Get-DesktopLaunchSnapshot @($fixture)).Windows | Where-Object { $_.ProcessId -eq $ProcessId -and $_.Visible -and $_.Owner -eq 0 -and -not $_.ToolWindow })
        if ($windows.Count) { return $windows[0] }
        [Threading.Thread]::Sleep(25)
    }
    throw 'Fixture window did not appear.'
}
try {
    # Own this baseline window, but make it preexisting relative to the launcher.
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$fixture; $info.Arguments='--mode single'; $info.UseShellExecute=$false
    $baselineProcess=[Diagnostics.Process]::Start($info)
    $baselineWindow=Wait-Window $baselineProcess.Id
    $baselineDesktop=$controller.Locate($baselineWindow.Handle).DesktopId
    $record=Join-Path $run 'arguments.txt'
    $unicode=[string][char]0x6d4b+[string][char]0x8bd5
    $arguments=@('--mode','single','--record',$record,'--payload','','spaced value','literal"quote','C:\with space\',$unicode,'$(not executed)')
    $resultJson=& (Join-Path $PSScriptRoot '..\scripts\start_on_desktop.ps1') -FilePath $fixture -ArgumentList $arguments -StatePath (Journal 'normal') -ObserveSeconds .6
    $result=$resultJson | ConvertFrom-Json
    Assert ($result.Status -eq 'completed' -and $result.LiveVerifiedWindows -ge 1) 'A new arbitrary executable must start and move.'
    Assert ($result.Windows[0].Window.ProcessId -ne $baselineProcess.Id) 'The old instance must not be selected.'
    Assert ($controller.Locate($baselineWindow.Handle).DesktopId -eq $baselineDesktop) 'A preexisting visible window must stay on its original desktop.'
    $decoded=@(foreach($line in [IO.File]::ReadAllLines($record)){[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($line))})
    Assert ($decoded.Count -eq $arguments.Count) 'Argument count must survive empty strings and quoting.'
    for($index=0;$index -lt $arguments.Count;$index++){Assert ([string]::Equals($decoded[$index],$arguments[$index],[StringComparison]::Ordinal)) "Argument $index did not round-trip."}
    Assert (@($controller.Inventory() | Where-Object Current)[0].Id -eq $initialDesktop) 'Launching and moving must not switch the current desktop.'

    $replacement=Start-AppOnDesktop -FilePath $fixture -ArgumentList @('--mode','recreate') -StatePath (Journal 'recreated-window') -ObserveSeconds 1
    Assert ($replacement.Windows.Count -ge 2 -and $replacement.LiveVerifiedWindows -ge 1) 'A later main window must be discovered after the splash.'
    Assert (@($replacement.Windows | Where-Object {$_.DesktopIdAfter -ne $replacement.Destination.Target.Id}).Count -eq 0) 'Every detected application window must verify on the destination.'

    $detached=Start-AppOnDesktop -FilePath $launcher -ArgumentList @('--mode','detach','--child-exe',$fixture) -MatchExecutablePath @($fixture) -StatePath (Journal 'replacement-process') -ObserveSeconds .6
    Assert ($detached.Status -eq 'completed') 'A short-lived launcher must not end observation of its final executable.'
    Assert (@($detached.Windows | Where-Object {$_.Window.ProcessId -eq $detached.InitialProcessId}).Count -eq 0) 'A different final executable must be explicitly selected.'
    Assert ($controller.Locate($baselineWindow.Handle).DesktopId -eq $baselineDesktop) 'Process replacement must still preserve the old instance.'

    $timedOut=$false
    try { Start-AppOnDesktop -FilePath $fixture -ArgumentList @('--mode','headless') -StatePath (Journal 'timeout') -TimeoutSeconds 1 -ObserveSeconds 0 | Out-Null } catch {$timedOut=$true}
    $timeoutJournal=Get-Content -LiteralPath (Journal 'timeout') -Raw | ConvertFrom-Json
    Assert ($timedOut -and $timeoutJournal.Status -eq 'timed_out' -and $timeoutJournal.Windows.Count -eq 0) 'No-window startup must time out without selecting an existing instance.'
    Assert ($controller.Locate($baselineWindow.Handle).DesktopId -eq $baselineDesktop) 'A timeout must not move the baseline window.'

    $signal=Join-Path $run 'open-window.signal'
    $serverInfo=New-Object Diagnostics.ProcessStartInfo
    $serverInfo.FileName=$fixture
    $serverInfo.Arguments=[AltWorkflow.DesktopLaunch.Native]::BuildArguments(@('--mode','reuse-server','--signal',$signal))
    $serverInfo.UseShellExecute=$false
    $server=[Diagnostics.Process]::Start($serverInfo)
    $serverWindow=Wait-Window $server.Id
    $serverDesktop=$controller.Locate($serverWindow.Handle).DesktopId
    $rejected=$false
    try { Start-AppOnDesktop -FilePath $fixture -ArgumentList @('--mode','reuse-client','--signal',$signal) -StatePath (Journal 'reuse-without-optin') -TimeoutSeconds 1 -ObserveSeconds 0 | Out-Null } catch {$rejected=$true}
    $serverBaseline=@((Get-DesktopLaunchSnapshot @($fixture)).Windows | Where-Object {$_.ProcessId -eq $server.Id -and $_.Visible -and $_.Owner -eq 0 -and -not $_.ToolWindow})
    Assert ($rejected -and $serverBaseline.Count -ge 2) 'A new window in an old process must remain excluded without opt-in.'
    foreach($oldWindow in $serverBaseline){Assert ($controller.Locate($oldWindow.Handle).DesktopId -eq $serverDesktop) 'Default process-reuse handling must preserve server windows.'}
    $reused=Start-AppOnDesktop -FilePath $fixture -ArgumentList @('--mode','reuse-client','--signal',$signal) -AllowNewWindowsInExistingProcess -StatePath (Journal 'reuse-with-optin') -ObserveSeconds .6
    Assert ($reused.Status -eq 'completed' -and $reused.Windows.Count -eq 1 -and $reused.Windows[0].Window.ProcessId -eq $server.Id) 'Explicit opt-in must move only the new window in the reused process.'
    foreach($oldWindow in $serverBaseline){Assert ($controller.Locate($oldWindow.Handle).DesktopId -eq $serverDesktop) 'Existing HWNDs must stay on their desktops even with process-reuse opt-in.'}

    if($IncludeNotepad){
        $notepad=Join-Path $env:WINDIR 'System32\notepad.exe'
        $note=Start-AppOnDesktop -FilePath $notepad -StatePath (Journal 'notepad') -ObserveSeconds .5
        $script:extraOwned=@($note.Windows | ForEach-Object Window)
        Assert ($note.Status -eq 'completed' -and $note.LiveVerifiedWindows -ge 1) 'The installed Notepad application must also move.'
    }
    Assert (@($controller.Inventory() | Where-Object Current)[0].Id -eq $initialDesktop) 'The current desktop must still be unchanged after the suite.'
    $baselineProcess.Dispose()
    $server.Dispose()
    "PASS $script:assertions native launch assertions; journals: $run"
} finally {
    # Exact fixture paths plus process start times exclude all user applications.
    $owned=@((Get-DesktopLaunchSnapshot @($fixture,$launcher)).Processes | Where-Object {$_.StartedUtc -ge $suiteStarted})
    $owned+=@($script:extraOwned)
    foreach($entry in $owned){
        $process=Get-Process -Id $entry.ProcessId -ErrorAction SilentlyContinue
        if($null -eq $process){continue}
        if($process.Path -ine $entry.ExecutablePath -or $process.StartTime.ToUniversalTime() -ne ([datetime]$entry.StartedUtc).ToUniversalTime()){continue}
        [void]$process.CloseMainWindow()
        if(-not $process.WaitForExit(4000)){$process.Kill();[void]$process.WaitForExit(4000)}
        $process.Dispose()
    }
}
