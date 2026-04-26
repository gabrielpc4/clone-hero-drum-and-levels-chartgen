@echo off
chcp 65001 >nul
setlocal
title Songsterr Import — compilar e abrir
cd /d "%~dp0"

set "SLN=%cd%\tools\SongsterrImport.sln"
set "EXE=%cd%\tools\SongsterrImport.Desktop\bin\Debug\net8.0-windows\SongsterrImport.Desktop.exe"

where dotnet >nul 2>&1
if errorlevel 1 (
  echo Não encontrei "dotnet" no PATH. Instale o .NET 8 SDK.
  echo https://dotnet.microsoft.com/download
  pause
  exit /b 1
)

echo Compilando...
dotnet build "%SLN%" -c Debug --nologo -v q
if errorlevel 1 (
  echo.
  echo A compilação falhou.
  pause
  exit /b 1
)

if not exist "%EXE%" (
  echo Exe não encontrado: %EXE%
  pause
  exit /b 1
)

echo Abrindo o aplicativo...
start "" "%EXE%"

endlocal
exit /b 0
