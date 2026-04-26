# Equivalente a sync_songs.sh — Windows (PowerShell 5+)
# Uso: .\sync_songs.ps1 <pasta-origem> <destino-sob-Songs>
# Ex.: .\sync_songs.ps1 "C:\repo\original\custom\SoD" "System of a Down - Soil"
# Exige notes.songsterr.mid na origem; grava notes.mid em Songs/<destino>/ e copia o resto
# (exceto *.mid e *.chart) da origem.

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $SourcePath,
    [Parameter(Mandatory = $true, Position = 1)]
    [string] $SongsSubPath
)

$ErrorActionPreference = "Stop"

if ($SourcePath -in @("-h", "--help", "")) {
    Write-Error "Uso: sync_songs.ps1 <pasta-origem> <destino-sob-Songs>"
    exit 1
}

$repoDir = $PSScriptRoot
if (-not (Test-Path -LiteralPath $repoDir -PathType Container)) {
    throw "Diretório do script inválido: $repoDir"
}

$sourceDir = Resolve-Path -LiteralPath $SourcePath
if (-not (Test-Path -LiteralPath $sourceDir -PathType Container)) {
    Write-Error "A origem não é uma pasta ou não existe: $SourcePath"
    exit 1
}

$rawDest = $SongsSubPath
if ($rawDest -like "Songs/*" -or $rawDest -like "Songs\*") {
    $songRelPath = $rawDest -replace "^[Ss]ongs[/\\]", ""
}
elseif ($rawDest -like "songs/*" -or $rawDest -like "songs\*") {
    $songRelPath = $rawDest -replace "^[Ss]ongs[/\\]", ""
}
else {
    $songRelPath = $rawDest
}

if ([string]::IsNullOrWhiteSpace($songRelPath) -or $songRelPath -eq "." -or $songRelPath -eq "..") {
    Write-Error "Destino inválido: indique a pasta da música sob Songs/ (ex.: 'System of a Down - Soil'). Recebido: '$SongsSubPath'"
    exit 1
}

if ($songRelPath -like "*`..*") {
    Write-Error "'..' não é permitido no destino. Use só o caminho desejado em Songs/."
    exit 1
}

$destSongDir = Join-Path -Path $repoDir -ChildPath (Join-Path "Songs" $songRelPath)
$null = New-Item -ItemType Directory -Path $destSongDir -Force

$songsterrMid = Join-Path $sourceDir "notes.songsterr.mid"
if (-not (Test-Path -LiteralPath $songsterrMid -PathType Leaf)) {
    Write-Error "Falta notes.songsterr.mid em: $sourceDir"
    exit 1
}

$items = Get-ChildItem -LiteralPath $sourceDir -ErrorAction SilentlyContinue
if ($null -ne $items) {
    foreach ($item in $items) {
        $name = $item.Name
        if ($name -like "*.mid" -or $name -like "*.chart") {
            continue
        }
        $destItem = Join-Path $destSongDir $name
        if ($item.PSIsContainer) {
            Copy-Item -LiteralPath $item.FullName -Destination $destItem -Recurse -Force
        }
        else {
            Copy-Item -LiteralPath $item.FullName -Destination $destItem -Force
        }
    }
}

$outNotes = Join-Path $destSongDir "notes.mid"
Copy-Item -LiteralPath $songsterrMid -Destination $outNotes -Force

Write-Host "Sync concluído: notes.songsterr.mid -> Songs/$songRelPath/notes.mid"
Write-Host "   Origem: $sourceDir"
Write-Host "   Destino: $destSongDir"
