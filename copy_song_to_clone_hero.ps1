# Copia os arquivos de uma pasta de musica para Songs/ no Clone Hero.
# Uso: .\copy_song_to_clone_hero.ps1 <pasta-origem> <destino-sob-Songs>
# Ex.: .\copy_song_to_clone_hero.ps1 "C:\repo\original\custom\SoD" "System of a Down - Soil"
# Exige notes.generated.mid na origem; grava notes.mid em Songs/<destino>/ e copia o resto
# (exceto *.mid e *.chart) da origem.

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $SourcePath,
    [Parameter(Mandatory = $true, Position = 1)]
    [string] $SongsSubPath
)

$ErrorActionPreference = "Stop"

function Compute-AudioCacheKey {
    param(
        [Parameter(Mandatory = $true)]
        [string] $AudioPath
    )

    $fileInfo = Get-Item -LiteralPath $AudioPath
    $identity = [string]::Join(
        "|",
        @(
            $fileInfo.FullName.ToLowerInvariant(),
            $fileInfo.Length.ToString(),
            $fileInfo.LastWriteTimeUtc.Ticks.ToString()
        )
    )

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($identity))
    }
    finally {
        $sha256.Dispose()
    }

    return ([System.BitConverter]::ToString($hashBytes).Replace("-", "").ToLowerInvariant())
}

function Get-PreferredAudioSourcePath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FolderPath
    )

    $supportedExtensions = @(".ogg", ".opus", ".wav", ".mp3", ".flac", ".m4a", ".mp4")
    $priorityPaths = @()
    foreach ($extension in $supportedExtensions) {
        $priorityPaths += (Join-Path $FolderPath ("song" + $extension))
    }

    foreach ($pathValue in $priorityPaths) {
        if (Test-Path -LiteralPath $pathValue -PathType Leaf) {
            return $pathValue
        }
    }

    $audioFiles = Get-ChildItem -LiteralPath $FolderPath -File |
        Where-Object { $supportedExtensions -contains $_.Extension.ToLowerInvariant() } |
        Sort-Object Name

    if ($audioFiles.Count -eq 0) {
        return ""
    }

    $firstOgg = $audioFiles | Where-Object { $_.Extension.Equals(".ogg", [System.StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1
    if ($null -ne $firstOgg) {
        return $firstOgg.FullName
    }

    return $audioFiles[0].FullName
}

function Resolve-FfmpegExecutablePath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $RepositoryRootPath
    )

    $bundledFfmpegPath = Join-Path $RepositoryRootPath "tools\\ffmpeg\\bin\\ffmpeg.exe"
    if (Test-Path -LiteralPath $bundledFfmpegPath -PathType Leaf) {
        return $bundledFfmpegPath
    }

    $ffmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($null -ne $ffmpegCommand) {
        return $ffmpegCommand.Source
    }

    return ""
}

function Ensure-OggAudioInDestination {
    param(
        [Parameter(Mandatory = $true)]
        [string] $SourceFolderPath,
        [Parameter(Mandatory = $true)]
        [string] $DestinationFolderPath,
        [Parameter(Mandatory = $true)]
        [string] $RepositoryRootPath
    )

    $sourceAudioPath = Get-PreferredAudioSourcePath -FolderPath $SourceFolderPath
    if ([string]::IsNullOrWhiteSpace($sourceAudioPath)) {
        throw "Nenhum arquivo de audio suportado foi encontrado na origem para gerar song.ogg."
    }

    $destinationOggPath = Join-Path $DestinationFolderPath "song.ogg"
    if ($sourceAudioPath.EndsWith(".ogg", [System.StringComparison]::OrdinalIgnoreCase)) {
        Copy-Item -LiteralPath $sourceAudioPath -Destination $destinationOggPath -Force
        return
    }

    $ffmpegExecutablePath = Resolve-FfmpegExecutablePath -RepositoryRootPath $RepositoryRootPath
    if ([string]::IsNullOrWhiteSpace($ffmpegExecutablePath)) {
        throw "ffmpeg nao encontrado. Coloque em tools\\ffmpeg\\bin\\ffmpeg.exe ou configure no PATH."
    }

    $cacheRoot = Join-Path $RepositoryRootPath "_cache_ogg"
    $null = New-Item -ItemType Directory -Path $cacheRoot -Force

    $cacheKey = Compute-AudioCacheKey -AudioPath $sourceAudioPath
    $cachedOggPath = Join-Path $cacheRoot ($cacheKey + ".ogg")
    if (-not (Test-Path -LiteralPath $cachedOggPath -PathType Leaf)) {
        $arguments = @(
            "-y",
            "-loglevel", "error",
            "-i", $sourceAudioPath,
            "-vn",
            "-c:a", "libvorbis",
            "-q:a", "5",
            $cachedOggPath
        )
        & $ffmpegExecutablePath @arguments | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "ffmpeg falhou ao converter '$sourceAudioPath' para ogg (exit $LASTEXITCODE)."
        }
    }

    Copy-Item -LiteralPath $cachedOggPath -Destination $destinationOggPath -Force
}

if ($SourcePath -in @("-h", "--help", "")) {
    Write-Error "Uso: copy_song_to_clone_hero.ps1 <pasta-origem> <destino-sob-Songs>"
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

$songsterrMid = Join-Path $sourceDir "notes.generated.mid"
if (-not (Test-Path -LiteralPath $songsterrMid -PathType Leaf)) {
    Write-Error "Falta notes.generated.mid em: $sourceDir"
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
Ensure-OggAudioInDestination -SourceFolderPath $sourceDir -DestinationFolderPath $destSongDir -RepositoryRootPath $repoDir

Write-Host "sync_status: ok"
