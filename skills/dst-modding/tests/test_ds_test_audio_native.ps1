param([Parameter(Mandatory)][string]$WorkDir)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\scripts\ds_test_audio.ps1')
Initialize-DsTestAudioNative
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
$fixture = Join-Path $PSScriptRoot 'fixtures\silent_audio_session.ps1'
$command = "& '" + $fixture.Replace("'", "''") + "'"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
$out = Join-Path $WorkDir 'silent-session.out'
$err = Join-Path $WorkDir 'silent-session.err'
$worker = $null
$original = $null
try {
    $worker = Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList '-NoProfile','-EncodedCommand',$encoded -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $deadline = [datetime]::UtcNow.AddSeconds(15)
    while ([datetime]::UtcNow -lt $deadline) {
        $original = @([DsTestAudio.CoreAudio]::Snapshot() | Where-Object {$_.ProcessId -eq $worker.Id}) | Select-Object -First 1
        if ($null -ne $original) { break }
        if ($worker.HasExited) { throw ('Silent fixture exited: ' + (Get-Content -LiteralPath $err -Raw)) }
        Start-Sleep -Milliseconds 200
    }
    if ($null -eq $original) { throw 'No audio session found for the isolated silent fixture.' }
    $others = @([DsTestAudio.CoreAudio]::Snapshot() | Where-Object {$_.ProcessId -ne $worker.Id})
    $targetMute = -not $original.Muted
    if (-not [DsTestAudio.CoreAudio]::SetMute($original.EndpointId,$original.InstanceId,$original.ProcessId,$targetMute)) { throw 'Mute change was not confirmed.' }
    $changed = @([DsTestAudio.CoreAudio]::Snapshot() | Where-Object {$_.InstanceId -eq $original.InstanceId -and $_.EndpointId -eq $original.EndpointId})[0]
    if ($changed.Muted -ne $targetMute -or $changed.Volume -ne $original.Volume) { throw 'Mute/volume round trip failed.' }
    if (-not [DsTestAudio.CoreAudio]::SetMute($original.EndpointId,$original.InstanceId,$original.ProcessId,$original.Muted)) { throw 'Original mute state was not restored.' }
    $after = @([DsTestAudio.CoreAudio]::Snapshot())
    foreach ($before in $others) {
        $same = @($after | Where-Object {$_.EndpointId -eq $before.EndpointId -and $_.InstanceId -eq $before.InstanceId})
        if ($same.Count -gt 0 -and ($same[0].Muted -ne $before.Muted -or $same[0].Volume -ne $before.Volume)) {
            throw 'Another audio session changed during validation; inspect external interference.'
        }
    }
    Write-Output 'PASS isolated native mute/readback/restore; volume and other sessions unchanged'
} finally {
    try {
        if ($null -ne $original) {
            [DsTestAudio.CoreAudio]::SetMute($original.EndpointId,$original.InstanceId,$original.ProcessId,$original.Muted) | Out-Null
        }
    } finally {
        if ($null -ne $worker -and -not $worker.HasExited) { Stop-Process -Id $worker.Id -Force }
    }
}
