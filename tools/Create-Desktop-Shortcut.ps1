# Autor: Gabriel Pinheiro de Carvalho
# Cria o atalho "Songsterr Import.lnk" na área de trabalho.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$exe = Join-Path $root "tools\SongsterrImport.Desktop\bin\Debug\net8.0-windows\SongsterrImport.Desktop.exe"
$work = Split-Path -Parent $exe
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "Songsterr Import.lnk"
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Error "Exe não encontrado. Rode antes: Iniciar-Songsterr-Import.bat ou: dotnet build tools\SongsterrImport.sln"
    exit 1
}
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnk)
$sc.TargetPath = $exe
$sc.WorkingDirectory = $work
$sc.Description = "Clone Hero — Songsterr Import (WPF)"
$sc.Save()
Write-Host "Atalho criado: $lnk"
