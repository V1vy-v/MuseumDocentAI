@echo off
rem Entry point for one-time backend setup. Double-click it or run it from cmd/PowerShell.
rem
rem Why this .cmd wrapper exists:
rem   The Windows default execution policy blocks unsigned .ps1 files
rem   ("... is not digitally signed ... UnauthorizedAccess").
rem   We relax the policy for THIS invocation only (-ExecutionPolicy Bypass),
rem   without touching the machine-wide setting.
rem   Comments here are ASCII on purpose: cmd.exe parses .cmd files in the OEM
rem   code page, so non-ASCII text in this file would break parsing.
rem
rem Usage:
rem   setup_backend.cmd               full setup (venv, deps, index if missing)
rem   setup_backend.cmd -CheckOnly    checks only, changes nothing
rem   setup_backend.cmd -SkipIndex    skip building the vector index

setlocal
set "SCRIPT=%~dp0setup_backend.ps1"

if not exist "%SCRIPT%" (
    echo [X] setup_backend.ps1 not found next to this file.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%
