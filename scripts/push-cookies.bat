@echo off
REM Export Firefox YouTube cookies and push to the DaBot server via scp.
REM Usage: push-cookies.bat [user@host] [remote_path] [python_cmd]
REM   Default server: haama@server
REM   Default remote: /home/haama/DaBot/cookies.txt
REM   Default python: python

setlocal enabledelayedexpansion

set SERVER=%~1
if "%SERVER%"=="" set SERVER=haama@server

set REMOTE_PATH=%~2
if "%REMOTE_PATH%"=="" set REMOTE_PATH=/home/haama/DaBot/cookies.txt

set PYTHON_CMD=%~3
if "%PYTHON_CMD%"=="" set PYTHON_CMD=python

set SCRIPT_PATH=.\export-cookies.py
set LOCAL_COOKIE=cookies.txt

echo Exporting Firefox YouTube cookies...
%PYTHON_CMD% %SCRIPT_PATH% -o %LOCAL_COOKIE%
if errorlevel 1 (
    echo ERROR: export-cookies.py failed
    exit /b 1
)
if not exist %LOCAL_COOKIE% (
    echo ERROR: %LOCAL_COOKIE% not created
    exit /b 1
)

echo Pushing to %SERVER%:%REMOTE_PATH% ...
scp %LOCAL_COOKIE% %SERVER%:%REMOTE_PATH%
if errorlevel 1 (
    echo ERROR: scp failed
    exit /b 1
)

echo Cleaning up local file...
del /f /q %LOCAL_COOKIE% 2>nul

echo Done.