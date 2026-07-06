@echo off
REM Run as administrator to import certificate
setlocal enabledelayedexpansion

echo Importing Serene Sudoku certificate to Local Machine Root store...
certutil -addstore -enterprise -group policy Root "c:\Users\timpe\Desktop\Microsoft Store - Unpaid IAP Version\serenesudoku_new.cer"

if %errorlevel% neq 0 (
    echo Trying alternate method...
    certutil -addstore Root "c:\Users\timpe\Desktop\Microsoft Store - Unpaid IAP Version\serenesudoku_new.cer"
)

if %errorlevel% equ 0 (
    echo.
    echo SUCCESS: Certificate imported. You can now install the MSIX.
    echo Close this window and double-click SereneSudoku.msix
) else (
    echo ERROR: Failed to import certificate. You need admin privileges.
)

echo.
pause
