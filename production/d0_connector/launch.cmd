@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
if errorlevel 1 (
    echo Could not start the connector. Read the error above and retry after resolving it.
    pause
    exit /b 1
)
exit /b 0
