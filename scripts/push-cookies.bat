@echo off
REM Export Firefox YouTube cookies and push to the DaBot server via scp.
REM Usage: push-cookies.bat [user@host] [remote_path] [python_cmd]
REM   Default server: haama@boksi.local
REM   Default remote: /home/haama/DaBot/cookies.txt
REM   Default python: python

setlocal

set "SERVER=%~1"
if "%SERVER%"=="" set "SERVER=haama@boksi.local"

set "REMOTE_PATH=%~2"
if "%REMOTE_PATH%"=="" set "REMOTE_PATH=/home/haama/DaBot/cookies.txt"

set "PYTHON_CMD=%~3"
if "%PYTHON_CMD%"=="" set "PYTHON_CMD=python"

REM Resolve relative to this .bat, not the caller's working directory.
set "SCRIPT_PATH=%~dp0export-cookies.py"
set "LOCAL_COOKIE=%TEMP%\dabot-cookies.txt"

echo Exporting Firefox YouTube cookies...
"%PYTHON_CMD%" "%SCRIPT_PATH%" -o "%LOCAL_COOKIE%"
if errorlevel 1 (
    echo ERROR: export failed; server cookies left untouched.
    if exist "%LOCAL_COOKIE%" del /f /q "%LOCAL_COOKIE%"
    exit /b 1
)
if not exist "%LOCAL_COOKIE%" (
    echo ERROR: %LOCAL_COOKIE% was not created.
    exit /b 1
)

echo Pushing to %SERVER%:%REMOTE_PATH% ...
scp "%LOCAL_COOKIE%" "%SERVER%:%REMOTE_PATH%"
if errorlevel 1 (
    echo ERROR: scp failed.
    del /f /q "%LOCAL_COOKIE%" 2>nul
    exit /b 1
)

del /f /q "%LOCAL_COOKIE%" 2>nul
echo Done.
