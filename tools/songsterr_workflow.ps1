# Sequence in README: download MIDI, import, sync (does not call the WPF app).
# Usage (in the repository root):
#   powershell -ExecutionPolicy Bypass -File tools/songsterr_workflow.ps1
#   -RepoRoot $PWD
#   -CookieFile "$env:LOCALAPPDATA\SongsterrImport\cookies.json"
#   -SongsterrUrl "https://www.songsterr.com/a/wsa/...-s21961"
#   -DownloadTo "Songs\System of a Down - Toxicity\songsterr_in.mid"
#   -OutSongsterrMid "Songs\System of a Down - Toxicity\notes.generated.mid"
#   -SyncSource "C:\path\with\notes.generated.already.written" (folder with notes.generated.mid)
#   -SyncSongsSub "System of a Down - Toxicity"
# Optional parameters: -RefPath, -InitialOffsetTicks, -FilterWeakSnares, -ExpertCymbalAlternationWhole

param(
    [string] $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string] $Python = "py",
    [Parameter(Mandatory = $true)]
    [string] $CookieFile,
    [Parameter(Mandatory = $true)]
    [string] $SongsterrUrl,
    [Parameter(Mandatory = $true)]
    [string] $DownloadTo,
    [Parameter(Mandatory = $true)]
    [string] $OutSongsterrMid,
    [string] $RefPath = "",
    [int] $InitialOffsetTicks = 768,
    [switch] $FilterWeakSnares,
    [switch] $ExpertCymbalAlternationWhole,
    [string] $SyncSource = "",
    [string] $SyncSongsSub = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$env:PYTHONPATH = "src;src\chart_generation"

# Resolve-Path may fail if it does not exist yet: create parent directory
function Ensure-ParentDir {
    param([string] $FilePath)
    $dir = Split-Path -Parent $FilePath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { $null = New-Item -ItemType Directory -Path $dir -Force }
}

$downloadScript = Join-Path $RepoRoot "src\songsterr_parsing\download_songsterr_midi.py"
$importScript = Join-Path $RepoRoot "src\songsterr_parsing\import_songsterr.py"
$syncScript = Join-Path $RepoRoot "copy_song_to_clone_hero.ps1"

if (-not (Test-Path -LiteralPath $downloadScript)) {
    throw "Not found: $downloadScript"
}

$cookiePath = (Resolve-Path -LiteralPath $CookieFile).Path
$dlPath = if ([IO.Path]::IsPathRooted($DownloadTo)) { $DownloadTo } else { Join-Path $RepoRoot $DownloadTo }
$outPath = if ([IO.Path]::IsPathRooted($OutSongsterrMid)) { $OutSongsterrMid } else { Join-Path $RepoRoot $OutSongsterrMid }
Ensure-ParentDir -FilePath $dlPath
Ensure-ParentDir -FilePath $outPath
$dlPath = [IO.Path]::GetFullPath($dlPath)
$outPath = [IO.Path]::GetFullPath($outPath)

Write-Host "== 1) Download MIDI Songsterr ==" -ForegroundColor Cyan
$downloadArgs = @("-3", $downloadScript, $SongsterrUrl, $dlPath, "--cookie-file", $cookiePath)
& $Python @downloadArgs
if ($LASTEXITCODE -ne 0) { throw "download_songsterr_midi.py failed with exit code $LASTEXITCODE" }

$importArgs = @(
    "-3", $importScript,
    $dlPath,
    $outPath,
    "--initial-offset-ticks", "$InitialOffsetTicks"
)
if ($RefPath -and $RefPath.Trim() -ne "") {
    $rRef = if ([IO.Path]::IsPathRooted($RefPath)) { $RefPath } else { Join-Path $RepoRoot $RefPath }
    $importArgs += @("--ref-path", $rRef)
}
if ($FilterWeakSnares) {
    $importArgs += @("--filter-weak-snares")
}
if ($ExpertCymbalAlternationWhole) {
    $importArgs += @("--expert-cymbal-alternation-whole")
}

Set-Location -LiteralPath $RepoRoot
Write-Host "== 2) import_songsterr ==" -ForegroundColor Cyan
& $Python @importArgs
if ($LASTEXITCODE -ne 0) { throw "import_songsterr.py failed with exit code $LASTEXITCODE" }

if ($SyncSource -and $SyncSongsSub) {
    Write-Host "== 3) copy_song_to_clone_hero.ps1 ==" -ForegroundColor Cyan
    & $syncScript -SourcePath $SyncSource -SongsSubPath $SyncSongsSub
    if ($LASTEXITCODE -ne 0) { throw "copy_song_to_clone_hero.ps1 falhou" }
}
else {
    Write-Host "(without sync) use -SyncSource and -SyncSongsSub to copy with copy_song_to_clone_hero.ps1" -ForegroundColor Yellow
}

Write-Host "Completed." -ForegroundColor Green
