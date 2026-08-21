@echo off
chcp 65001 >nul
title Decision-Clicker
setlocal

set "DIR=%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%DIR%src"

echo ========================================
echo   Decision-Clicker
echo ========================================
echo.

:: Läuft schon einer? Dann nur den Browser öffnen, keinen zweiten starten.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod -Uri 'http://127.0.0.1:8096/api/health' -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Der Server läuft bereits auf http://127.0.0.1:8096
    start "" "http://127.0.0.1:8096"
    goto :EOF
)

:: Browser öffnet sich, sobald der Server steht.
start "" /B powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8096'"

echo Starte Server auf http://127.0.0.1:8096 ...
echo Strg+C beendet ihn.
echo.
python -m decision_clicker

endlocal
