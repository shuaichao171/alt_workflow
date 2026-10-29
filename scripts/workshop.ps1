<# Build the small CLI in the target project's work directory, then run it. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('plan', 'check', 'inspect', 'list', 'upload')]
    [string]$Command,
    [Parameter(Mandatory = $true, Position = 1)]
    [string]$Config,
    [string]$SteamApiDll
)

$ErrorActionPreference = 'Stop'
$workflowRoot = Split-Path -Parent $PSScriptRoot
$configPath = (Resolve-Path -LiteralPath $Config).Path
$jobDirectory = Split-Path -Parent $configPath
$toolRoot = Join-Path $jobDirectory '_workshop_tool'
$sourceDirectory = Join-Path $workflowRoot 'skills\steam-workshop-upload\scripts'
$localSource = Join-Path $toolRoot 'source'
$projectPath = Join-Path $localSource 'WorkshopUpload.csproj'
$publishDirectory = Join-Path $localSource 'bin\Release\net10.0\win-x86\publish'
$executablePath = Join-Path $publishDirectory 'WorkshopUpload.exe'

# Never put generated code, logs or upload payloads in the workflow repository.
$workflowPrefix = $workflowRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
if ($configPath.StartsWith($workflowPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Put the job JSON in the target project (for example _ai_work/workshop/job.json), outside alt_workflow.'
}

$dotnetCommand = Get-Command dotnet -ErrorAction Stop
$sdkVersions = & $dotnetCommand.Source --list-sdks
if (-not ($sdkVersions -match '^10\.')) { throw '.NET 10 SDK is required.' }
New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
New-Item -ItemType Directory -Path $localSource -Force | Out-Null
# Build with relative default output paths. MSBuild's absolute ArtifactsPath
# transforms break on apostrophes in paths such as Don't Starve Mod Tools.
foreach ($sourceFile in @('WorkshopUpload.csproj', 'Program.cs', 'Job.cs', 'Planner.cs', 'ModInfo.cs', 'PublishedList.cs', 'SteamworksWorkshopUploader.cs')) {
    Copy-Item -LiteralPath (Join-Path $sourceDirectory $sourceFile) -Destination (Join-Path $localSource $sourceFile) -Force
}
$buildLog = Join-Path $toolRoot 'build.log'
$buildOutput = & $dotnetCommand.Source publish $projectPath -c Release -r win-x86 --self-contained false --nologo 2>&1
$buildExitCode = $LASTEXITCODE
$buildOutput | Set-Content -LiteralPath $buildLog -Encoding UTF8
if ($buildExitCode -ne 0) {
    $buildOutput | ForEach-Object { Write-Host $_ }
    throw "Build failed. See $buildLog"
}

# plan/check are completely offline and do not require Steam or its DLL.
if ($Command -in @('inspect', 'list', 'upload')) {
    if (-not $SteamApiDll) {
        $SteamApiDll = Join-Path $workflowRoot 'skills\steam-workshop-upload\assets\win-x86\steam_api.dll'
    }
    if (-not $SteamApiDll -or -not (Test-Path -LiteralPath $SteamApiDll -PathType Leaf)) {
        throw 'The bundled 32-bit steam_api.dll is missing. Restore assets/win-x86/steam_api.dll or pass -SteamApiDll.'
    }
    $dllTarget = Join-Path $publishDirectory 'steam_api.dll'
    if ([IO.Path]::GetFullPath($SteamApiDll) -ne [IO.Path]::GetFullPath($dllTarget)) {
        Copy-Item -LiteralPath $SteamApiDll -Destination $dllTarget -Force
    }
}

& $executablePath $Command $configPath
exit $LASTEXITCODE
