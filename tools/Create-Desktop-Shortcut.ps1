# Author: Gabriel Pinheiro de Carvalho
# Creates the shortcut "Songsterr Import.lnk" on the desktop.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$exe = Join-Path $root "tools\SongsterrImport.Desktop\bin\Debug\net8.0-windows10.0.19041.0\SongsterrImport.Desktop.exe"
$work = Split-Path -Parent $exe
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "Songsterr Import.lnk"
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Error "Exe not found. Run first: Iniciar-Songsterr-Import.bat or: dotnet build tools\SongsterrImport.sln"
    exit 1
}
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnk)
$sc.TargetPath = $exe
$sc.WorkingDirectory = $work
$sc.Description = "Clone Hero — Songsterr Import (WPF)"
$sc.Save()
Write-Host "Shortcut created: $lnk"
