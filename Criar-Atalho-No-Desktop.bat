@echo off
chcp 65001 >nul
setlocal
title Atalho Songsterr Import — área de trabalho
cd /d "%~dp0"

set "SLN=%cd%\tools\SongsterrImport.sln"
set "EXE=%cd%\tools\SongsterrImport.Desktop\bin\Debug\net8.0-windows\SongsterrImport.Desktop.exe"

where dotnet >nul 2>&1
if errorlevel 1 (
  echo Não encontrei "dotnet" no PATH. Instale o .NET 8 SDK.
  pause
  exit /b 1
)

if not exist "%EXE%" (
  echo Compilando para gerar o .exe...
  dotnet build "%SLN%" -c Debug --nologo -v q
  if errorlevel 1 (
    echo A compilação falhou.
    pause
    exit /b 1
  )
)

if not exist "%EXE%" (
  echo Ainda não existe o exe: %EXE%
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%cd%\tools\Create-Desktop-Shortcut.ps1"
if errorlevel 1 (
  echo Falha ao criar o atalho.
  pause
  exit /b 1
)

echo.
pause

endlocal
exit /b 0
