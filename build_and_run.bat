@echo off
setlocal
set "REPO=%~dp0"
set "PBASE=%REPO%tools\SongsterrImport.Desktop\bin\Debug"
set "SLN=%REPO%tools\SongsterrImport.sln"
set "CSPROJ=%REPO%tools\SongsterrImport.Desktop\SongsterrImport.Desktop.csproj"
title SongsterrImport
cd /d "%REPO%"

where dotnet >nul 2>&1
if errorlevel 1 (
  echo dotnet not found. Install the .NET 8 SDK. See:
  echo https://dotnet.microsoft.com/download
  pause
  exit /b 1
)

echo Build...
dotnet build "%SLN%" -c Debug --nologo -v q
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

set "EXE="
if exist "%PBASE%\net8.0-windows10.0.19041.0\SongsterrImport.Desktop.exe" set "EXE=%PBASE%\net8.0-windows10.0.19041.0\SongsterrImport.Desktop.exe"
if not defined EXE if exist "%PBASE%\net8.0-windows\SongsterrImport.Desktop.exe" set "EXE=%PBASE%\net8.0-windows\SongsterrImport.Desktop.exe"

if not defined EXE (
  echo No exe under bin\Debug - launching via dotnet run...
  start "" /D "%REPO%" dotnet run --no-build -c Debug --project "%CSPROJ%"
  endlocal
  exit /b 0
)

echo Open app...
start "" "%EXE%"
endlocal
exit /b 0
