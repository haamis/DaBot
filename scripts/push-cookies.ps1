<#
.SYNOPSIS
    Export Firefox YouTube cookies and push to the DaBot server via scp.

.DESCRIPTION
    Runs export-cookies.py (requires Python + browser-cookie3), then copies
    the resulting cookies.txt to the server. The bot picks up the new file
    automatically on next extraction (no restart needed).

.PARAMETER Server
    SSH target: user@host or host (uses current user). Default: haama@server
.PARAMETER RemotePath
    Destination path on server. Default: /home/haama/DaBot/cookies.txt
.PARAMETER PythonCmd
    Python executable. Default: python
.PARAMETER ScriptPath
    Path to export-cookies.py. Default: .\export-cookies.py
.PARAMETER KeepLocal
    Keep local cookies.txt after push. Default: false (clean up).

.EXAMPLE
    .\push-cookies.ps1 -Server haama@192.168.1.50

.EXAMPLE
    .\push-cookies.ps1 -Server myserver -RemotePath /opt/dabot/cookies.txt
#>

param(
    [string]$Server = "haama@server",
    [string]$RemotePath = "/home/haama/DaBot/cookies.txt",
    [string]$PythonCmd = "python",
    [string]$ScriptPath = ".\export-cookies.py",
    [switch]$KeepLocal
)

$ErrorActionPreference = "Stop"
$localCookie = "cookies.txt"

try {
    Write-Host "Exporting Firefox YouTube cookies..." -ForegroundColor Cyan
    & $PythonCmd $ScriptPath -o $localCookie
    if (-not (Test-Path $localCookie)) {
        throw "export-cookies.py did not create $localCookie"
    }
    $bytes = (Get-Item $localCookie).Length
    Write-Host "Local file: $bytes bytes" -ForegroundColor Green

    Write-Host "Pushing to $Server:$RemotePath ..." -ForegroundColor Cyan
    scp $localCookie "$Server:$RemotePath"
    Write-Host "Done." -ForegroundColor Green
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if (-not $KeepLocal -and (Test-Path $localCookie)) {
        Remove-Item $localCookie -Force -ErrorAction SilentlyContinue
    }
}