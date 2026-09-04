@echo off
REM ====================================================================
REM Stock Analysis - Weekly Database Update & ntfy Notification Batch Script
REM ====================================================================

title Stock Analysis Weekly DB Update

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo [%DATE% %TIME%] Starting Stock Analysis Weekly Database Update... >> "%SCRIPT_DIR%update_db_weekly.log"
echo.

python update_db_weekly.py >> "%SCRIPT_DIR%update_db_weekly.log" 2>&1
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% EQU 0 (
    echo [%DATE% %TIME%] SUCCESS: Database updated successfully. >> "%SCRIPT_DIR%update_db_weekly.log"
) else (
    echo [%DATE% %TIME%] ERROR: Database update failed with exit code %EXIT_CODE%. >> "%SCRIPT_DIR%update_db_weekly.log"
)

echo -------------------------------------------------------------------- >> "%SCRIPT_DIR%update_db_weekly.log"
exit /b %EXIT_CODE%
