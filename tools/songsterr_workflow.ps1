# Sequência no README: baixar MIDI, import, sync (não chama o app WPF).
# Uso (na raiz do repositório):
#   powershell -ExecutionPolicy Bypass -File tools/songsterr_workflow.ps1
#   -RepoRoot $PWD
#   -CookieFile "$env:LOCALAPPDATA\SongsterrImport\cookies.json"
#   -SongsterrUrl "https://www.songsterr.com/a/wsa/...-s21961"
#   -DownloadTo "Songs\System of a Down - Toxicity\songsterr_in.mid"
#   -OutSongsterrMid "Songs\System of a Down - Toxicity\notes.generated.mid"
#   -SyncSource "C:\caminho\com\notes.generated.ja.escrito" (pasta com notes.generated.mid)
#   -SyncSongsSub "System of a Down - Toxicity"
# Parâmetros opcionais: -RefPath, -InitialOffsetTicks, -DedupBeats, -FilterWeakSnares, -NoConvertFlams

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
    [double] $DedupBeats = 0.0625,
    [switch] $FilterWeakSnares,
    [switch] $NoConvertFlams,
    [string] $SyncSource = "",
    [string] $SyncSongsSub = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$env:PYTHONPATH = "src;src\chart_generation"

# Resolve-Path pode falhar se ainda não existir: criar diretório pai
function Ensure-ParentDir {
    param([string] $FilePath)
    $dir = Split-Path -Parent $FilePath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { $null = New-Item -ItemType Directory -Path $dir -Force }
}

$downloadScript = Join-Path $RepoRoot "src\songsterr_parsing\download_songsterr_midi.py"
$importScript = Join-Path $RepoRoot "src\songsterr_parsing\import_songsterr.py"
$syncScript = Join-Path $RepoRoot "copy_song_to_clone_hero.ps1"

if (-not (Test-Path -LiteralPath $downloadScript)) {
    throw "Não encontrado: $downloadScript"
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
if ($LASTEXITCODE -ne 0) { throw "download_songsterr_midi.py falhou com código $LASTEXITCODE" }

$importArgs = @(
    "-3", $importScript,
    $dlPath,
    $outPath,
    "--initial-offset-ticks", "$InitialOffsetTicks",
    "--dedup-beats", "$DedupBeats"
)
if ($RefPath -and $RefPath.Trim() -ne "") {
    $rRef = if ([IO.Path]::IsPathRooted($RefPath)) { $RefPath } else { Join-Path $RepoRoot $RefPath }
    $importArgs += @("--ref-path", $rRef)
}
if ($FilterWeakSnares) {
    $importArgs += @("--filter-weak-snares")
}
if ($NoConvertFlams) {
    $importArgs += @("--no-convert-flams")
}

Set-Location -LiteralPath $RepoRoot
Write-Host "== 2) import_songsterr ==" -ForegroundColor Cyan
& $Python @importArgs
if ($LASTEXITCODE -ne 0) { throw "import_songsterr.py falhou com código $LASTEXITCODE" }

if ($SyncSource -and $SyncSongsSub) {
    Write-Host "== 3) copy_song_to_clone_hero.ps1 ==" -ForegroundColor Cyan
    & $syncScript -SourcePath $SyncSource -SongsSubPath $SyncSongsSub
    if ($LASTEXITCODE -ne 0) { throw "copy_song_to_clone_hero.ps1 falhou" }
}
else {
    Write-Host "(sem sync) use -SyncSource e -SyncSongsSub para copiar com copy_song_to_clone_hero.ps1" -ForegroundColor Yellow
}

Write-Host "Concluído." -ForegroundColor Green
