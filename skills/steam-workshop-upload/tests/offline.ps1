[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$Workspace)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$workflowRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$testRoot = Join-Path ([IO.Path]::GetFullPath($Workspace)) ('offline-' + [Guid]::NewGuid().ToString('N').Substring(0, 12))
$modRoot = Join-Path $testRoot '中文 mod'
$jobDirectory = Join-Path $modRoot '_ai_work\workshop'
New-Item -ItemType Directory -Path $jobDirectory -Force | Out-Null
$configPath = Join-Path $jobDirectory 'job.json'
$checks = 0

function Assert-That([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:checks++
}
function Write-Fixture([string]$RelativePath, [string]$Content) {
    $path = Join-Path $modRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
    [IO.File]::WriteAllText($path, $Content, [Text.UTF8Encoding]::new($false))
}
function Save-Job {
    [IO.File]::WriteAllText($configPath, ($script:job | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
}
function Run-Cli([string]$Command, [int]$ExpectedExit = 0) {
    $output = & $script:executable $Command $configPath 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne $ExpectedExit) { throw "Unexpected exit $exitCode for $Command`: $($output -join [Environment]::NewLine)" }
    $output | Set-Content -LiteralPath (Join-Path $testRoot ($Command + '.log')) -Encoding UTF8
}
function Read-Plan { Get-Content -LiteralPath ([IO.Path]::ChangeExtension($configPath, '.plan.json')) -Raw -Encoding UTF8 | ConvertFrom-Json }
function Assert-UploadNotAuthorized([string]$Scenario) {
    Save-Job
    Run-Cli 'upload' 5
    Assert-That ((Get-Content -LiteralPath (Join-Path $testRoot 'upload.log') -Raw -Encoding UTF8) -match '等待用户明确要求上传') ($Scenario + ': upload must stop at the authorization guard.')
}
function New-FixtureAuthorization {
    # Synthetic data for isolated offline tests only. Every upload in this suite
    # must stop at an authorization/target guard or failed plan before Steam.
    return @{
        decision = 'authorized'; operation = 'update'; app_id = 322330; workshop_id = '1'
        user_request = 'Synthetic offline fixture: upload DST item 1. Never submit to Steam.'
    }
}

Write-Fixture 'modinfo.lua' "-- version = 'wrong'`nconfiguration_options = {{version = 'also-wrong'}}`nversion = '1.1'`nname = '测试'`n"
Write-Fixture 'modmain.lua' '-- main'
Write-Fixture 'scripts/sub/中文.lua' '-- script'
Write-Fixture 'scripts/old.bak' 'backup'
Write-Fixture 'anim/a.zip' 'archive bytes'
Write-Fixture 'native/plugin.dll' 'native bytes'
Write-Fixture 'binary.exe' 'executable bytes'
Write-Fixture 'KEEP.PNG' 'uppercase extension'
Write-Fixture 'filtered.png' 'lowercase extension'
Write-Fixture 'data/test.tex' 'texture'
Write-Fixture 'README.md' 'documentation retained unless explicitly excluded'
Write-Fixture 'logs/log.txt' 'logs retained unless explicitly excluded'
Write-Fixture 'docs/notes.md' 'excluded by this job'
Write-Fixture '.hidden' 'dot file'
Write-Fixture '.git/config' 'dot directory'
Write-Fixture 'bad.illegaldummyformat' 'official illegal placeholder'
Write-Fixture 'mod.manifest' 'original DS manifest'
$junctionTarget = Join-Path $testRoot 'junction-target'
New-Item -ItemType Directory -Path $junctionTarget -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $junctionTarget 'outside.lua'), '-- outside')
$junction = New-Item -ItemType Junction -Path (Join-Path $modRoot 'linked') -Target $junctionTarget -Force

$script:job = [ordered]@{
    operation = 'update'; app_id = 322330; workshop_id = '1'
    source_directory = '../..'; include = @('**'); exclude = @('docs/**', '**/*.bak')
}
Save-Job
$entry = Join-Path $workflowRoot 'scripts\workshop.ps1'
$shellExecutable = (Get-Process -Id $PID).Path
$buildOutput = & $shellExecutable -NoProfile -File $entry plan $configPath 2>&1
if ($LASTEXITCODE -ne 0) { throw ($buildOutput -join [Environment]::NewLine) }
$script:executable = Join-Path $jobDirectory '_workshop_tool\source\bin\Release\net10.0\win-x86\publish\WorkshopUpload.exe'
$plan = Read-Plan
$paths = @($plan.files | ForEach-Object { $_.path })
Assert-That ($plan.version -eq '1.1') 'modinfo parsing must ignore comments and nested tables.'
Assert-That ($paths -contains 'native/plugin.dll' -and $paths -contains 'binary.exe' -and $paths -contains 'anim/a.zip') 'Runtime DLL/EXE/ZIP files must survive filtering.'
Assert-That ($paths -contains 'scripts/sub/中文.lua') 'Unicode paths must survive.'
Assert-That ($paths -contains 'README.md' -and $paths -contains 'logs/log.txt') 'Do not add an implicit documentation/log blacklist.'
Assert-That ($paths -contains 'KEEP.PNG' -and $paths -notcontains 'filtered.png') 'Official redundant extension matching must be case-sensitive.'
Assert-That ($paths -notcontains '.hidden' -and $paths -notcontains '.git/config' -and $paths -notcontains 'bad.illegaldummyformat') 'Official exclusions failed.'
Assert-That ($paths -notcontains 'linked/outside.lua') 'Directory junction must not be traversed.'
Assert-That ($paths -notcontains 'docs/notes.md' -and $paths -notcontains 'scripts/old.bak') 'Job excludes failed.'
Assert-That (-not ($paths -match '^_ai_work/')) 'Work artifacts must not recurse into the payload.'
Assert-That ((Get-Content -LiteralPath (Join-Path $modRoot 'mod.manifest') -Raw) -eq 'original DS manifest') 'Source manifest must remain unchanged.'

$manifestPath = Join-Path $plan.payload_directory 'mod.manifest'
$manifest = [IO.BinaryReader]::new([IO.File]::OpenRead($manifestPath))
try {
    Assert-That ([Text.Encoding]::ASCII.GetString($manifest.ReadBytes(4)) -eq 'MNFS') 'Invalid manifest magic.'
    Assert-That ($manifest.ReadUInt32() -eq 1) 'Invalid manifest format version.'
    $manifestPaths = @('binary.exe', 'KEEP.PNG', 'modinfo.lua', 'modmain.lua', 'README.md', 'anim/a.zip', 'data/test.tex', 'logs/log.txt', 'native/plugin.dll', 'scripts/sub/中文.lua')
    Assert-That ($manifest.ReadUInt32() -eq $manifestPaths.Count) 'Invalid manifest entry count.'
    foreach ($path in $manifestPaths) {
        [uint64]$hash = 0
        foreach ($byte in [Text.Encoding]::UTF8.GetBytes($path.ToLowerInvariant())) { $hash = ($hash * 65599 + $byte) -band [uint64]4294967295 }
        Assert-That ($manifest.ReadUInt32() -eq $hash) ('Invalid ordered SDBM hash: ' + $path)
    }
    Assert-That ($manifest.BaseStream.Position -eq $manifest.BaseStream.Length) 'Unexpected manifest bytes.'
} finally { $manifest.Dispose() }
Run-Cli 'check'

Assert-UploadNotAuthorized 'An explicit ID with no upload instruction'
$script:job.force = $true
Assert-UploadNotAuthorized 'force cannot grant upload permission'
$script:job.target_source = 'list'
$script:job.target_confirmation = @{ decision = 'confirmed'; app_id = 322330; workshop_id = '1'; user_reply = 'ID 没错' }
Assert-UploadNotAuthorized 'Confirming a list ID does not authorize upload'
$script:job.Remove('target_source')
$script:job.Remove('target_confirmation')
$script:job.Remove('force')
$script:job.update_content = $false
$script:job.update_metadata = $true
$script:job.title = 'Offline fixture'
Assert-UploadNotAuthorized 'Metadata-only updates require upload authorization'
$script:job.operation = 'create'
$script:job.workshop_id = '0'
$script:job.update_content = $true
$script:job.update_preview = $true
$script:job.preview_file = '../../filtered.png'
Assert-UploadNotAuthorized 'Creating a new item requires upload authorization'
$script:job.operation = 'update'
$script:job.workshop_id = '1'
$script:job.Remove('update_content')
$script:job.Remove('update_metadata')
$script:job.Remove('update_preview')
$script:job.Remove('preview_file')
$script:job.Remove('title')
$script:job.upload_authorization = @{}
Assert-UploadNotAuthorized 'Empty authorization defaults to pending'
foreach ($invalidField in @('decision', 'operation', 'app_id', 'workshop_id', 'user_request')) {
    $script:job.upload_authorization = New-FixtureAuthorization
    $script:job.upload_authorization[$invalidField] = switch ($invalidField) {
        'decision' { 'pending' }
        'operation' { 'create' }
        'app_id' { 219740 }
        'workshop_id' { '2' }
        'user_request' { ' ' }
    }
    Assert-UploadNotAuthorized ('Invalid authorization field ' + $invalidField)
}
Assert-That (-not (Test-Path -LiteralPath ([IO.Path]::ChangeExtension($configPath, '.result.json')))) 'Unauthorized attempts must not create a submission receipt.'
Assert-That (-not (Test-Path -LiteralPath ([IO.Path]::ChangeExtension($configPath, '.upload.log')))) 'Unauthorized attempts must not reach the upload writer.'
$script:job.upload_authorization = New-FixtureAuthorization
Save-Job
# A complete authorization passes its guard; the changed config deliberately
# leaves the plan stale, proving the positive path without touching Steam.
Run-Cli 'upload' 1
Assert-That ((Get-Content -LiteralPath (Join-Path $testRoot 'upload.log') -Raw -Encoding UTF8) -match '任务配置已变化') 'Complete upload authorization must reach offline plan validation.'

$script:job.target_source = 'list'
Save-Job
Run-Cli 'plan'
Run-Cli 'check'
Run-Cli 'upload' 4
$script:job.force = $true
Save-Job
Run-Cli 'plan'
Run-Cli 'upload' 4
$script:job.target_confirmation = @{ decision = 'pending'; app_id = 322330; workshop_id = '1'; user_reply = '可能是这个' }
Save-Job
Run-Cli 'plan'
Run-Cli 'upload' 4
$script:job.target_confirmation = @{ decision = 'confirmed'; app_id = 219740; workshop_id = '1'; user_reply = '确认' }
Save-Job
Run-Cli 'upload' 4
$script:job.target_confirmation.app_id = 322330
$script:job.target_confirmation.workshop_id = '2'
Save-Job
Run-Cli 'upload' 4
$script:job.target_confirmation.workshop_id = '1'
$script:job.target_confirmation.user_reply = ' '
Save-Job
Run-Cli 'upload' 4
Assert-That (-not (Test-Path -LiteralPath ([IO.Path]::ChangeExtension($configPath, '.result.json')))) 'Unconfirmed/list-mismatched targets must stop before Steam and submission, even with force.'
# A complete confirmation passes the target guard, then a stale file plan
# stops upload before Steam. This tests the positive path without publishing.
$script:job.target_confirmation.user_reply = '确认联机版 ID 1'
Save-Job
Run-Cli 'upload' 1
Assert-That ((Get-Content -LiteralPath (Join-Path $testRoot 'upload.log') -Raw -Encoding UTF8) -match '任务配置已变化') 'Confirmed target must pass the guard and reach offline plan validation.'
$script:job.Remove('target_source')
$script:job.Remove('target_confirmation')
$script:job.Remove('force')
Save-Job
Run-Cli 'plan'
$plan = Read-Plan

Write-Fixture 'scripts/sub/中文.lua' '-- changed'
Run-Cli 'check' 1
# This upload call must stop at offline plan validation, before loading any DLL.
Run-Cli 'upload' 1
Assert-That (-not (Test-Path -LiteralPath ([IO.Path]::ChangeExtension($configPath, '.result.json')))) 'Changed source must stop before submission.'
Write-Fixture 'scripts/sub/中文.lua' '-- script'
Run-Cli 'check'
[IO.File]::AppendAllText((Join-Path $plan.payload_directory 'modmain.lua'), 'tampered')
Run-Cli 'check' 1
Run-Cli 'plan'
$plan = Read-Plan
$script:job.include = @('modinfo.lua', 'scripts/**/*.lua', 'filtered.png')
$script:job.upload_redundant_files = $true
Save-Job
Run-Cli 'check' 1
Run-Cli 'plan'
$plan = Read-Plan
$paths = @($plan.files | ForEach-Object { $_.path })
Assert-That ($paths.Count -eq 4 -and $paths -contains 'filtered.png' -and $paths -contains 'scripts/sub/中文.lua') 'Explicit selection or redundant-file opt-in failed.'
Assert-That ($paths -notcontains 'modmain.lua' -and $paths -notcontains 'native/plugin.dll') 'Allowlist must control the final upload.'

$script:job.app_id = 219740
$script:job.include = @('**')
Save-Job
Run-Cli 'plan'
$plan = Read-Plan
Assert-That ((Get-Content -LiteralPath (Join-Path $plan.payload_directory 'mod.manifest') -Raw) -eq 'original DS manifest') 'DS must preserve the existing manifest.'
$script:job.include = @('../outside.lua')
Save-Job
Run-Cli 'plan' 1
$script:job.include = @('**')
$script:job.unknown_typo = $true
Save-Job
Run-Cli 'plan' 1
$script:job.Remove('unknown_typo')
$script:job.operation = 'create'
$script:job.workshop_id = '0'
Save-Job
Run-Cli 'plan' 1

Write-Host "PASS: $checks invariant checks, plus source/config/payload tamper and invalid-job rejection."
Write-Host "Artifacts: $testRoot"
