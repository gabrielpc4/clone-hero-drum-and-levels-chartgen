# Renames songs\Songs\<short> to match original\custom\<full> when the only difference
# is a trailing " (charter)" segment. Stops on ambiguous short names (two customs share the same base).
# Usage (repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\align_songs_folders_to_custom.ps1
#   -RepoRoot $PWD
param(
    [string] $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$customPath = Join-Path $RepoRoot "original\custom"
$songsPath = Join-Path $RepoRoot "Songs"
if (-not (Test-Path -LiteralPath $customPath -PathType Container)) {
    throw "Pasta inexistente: $customPath"
}
if (-not (Test-Path -LiteralPath $songsPath -PathType Container)) {
    throw "Pasta inexistente: $songsPath"
}

function Get-NameWithoutCharterSuffix {
    param([string] $folderName)
    if ($folderName -match '^(.*) \([^)]+\)\s*$') {
        return $matches[1].TrimEnd()
    }
    return $folderName
}

# Quais "short" tem mais de um custom com o mesmo prefixo? (ex.: mesmo nome sem o sufixo)
$byShort = @{}
foreach ($dir in Get-ChildItem -LiteralPath $customPath -Directory) {
    $full = $dir.Name
    $short = Get-NameWithoutCharterSuffix -folderName $full
    if (-not $byShort.ContainsKey($short)) {
        $byShort[$short] = [System.Collections.ArrayList]@()
    }
    $null = $byShort[$short].Add($full)
}

$ambiguous = @()
foreach ($short in $byShort.Keys) {
    if ($byShort[$short].Count -gt 1) {
        $names = $byShort[$short] -join " | "
        $ambiguous += "Mais de um `original\custom\` com base '$short'`: $names"
    }
}
if ($ambiguous.Count -gt 0) {
    $ambiguous | ForEach-Object { Write-Warning $_ }
    throw "Ajuste manual: ha nomes de pasta ambiguos. Nada foi renomeado em Songs/."
}

foreach ($dir in Get-ChildItem -LiteralPath $customPath -Directory) {
    $full = $dir.Name
    $short = Get-NameWithoutCharterSuffix -folderName $full
    if ($short -eq $full) {
        continue
    }
    $destFull = Join-Path $songsPath $full
    if (Test-Path -LiteralPath $destFull -PathType Container) {
        continue
    }
    $sourceShort = Join-Path $songsPath $short
    if (Test-Path -LiteralPath $sourceShort -PathType Container) {
        Write-Host "Renomeando: Songs\$short  ->  Songs\$full" -ForegroundColor Cyan
        Rename-Item -LiteralPath $sourceShort -NewName $full
    }
}

Write-Host "Concluido." -ForegroundColor Green
