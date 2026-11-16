$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Extensions
$stream = [IO.MemoryStream]::new()
$writer = [IO.BinaryWriter]::new($stream)
$writer.Write([Text.Encoding]::ASCII.GetBytes('RIFF'))
$writer.Write([int]16036)
$writer.Write([Text.Encoding]::ASCII.GetBytes('WAVEfmt '))
$writer.Write([int]16)
$writer.Write([int16]1)
$writer.Write([int16]1)
$writer.Write([int]8000)
$writer.Write([int]16000)
$writer.Write([int16]2)
$writer.Write([int16]16)
$writer.Write([Text.Encoding]::ASCII.GetBytes('data'))
$writer.Write([int]16000)
$writer.Write([byte[]]::new(16000))
$stream.Position = 0
$player = [System.Media.SoundPlayer]::new($stream)
try {
    $player.Load()
    $player.PlayLooping()
    Write-Output "SILENT_AUDIO_READY $PID"
    Start-Sleep -Seconds 45
} finally { $player.Stop(); $player.Dispose(); $writer.Dispose(); $stream.Dispose() }
