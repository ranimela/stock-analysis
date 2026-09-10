@echo off
REM ====================================================================
REM Stock Analysis - Weekly Database Update & ntfy Notification Batch Script
REM ====================================================================

title Stock Analysis Weekly DB Update

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo [%DATE% %TIME%] Starting Stock Analysis Weekly Database Update...
echo [%DATE% %TIME%] Starting Stock Analysis Weekly Database Update... >> "%SCRIPT_DIR%update_db_weekly.log"
echo.

python -u update_db_weekly.py
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% EQU 0 (
    echo.
    echo [%DATE% %TIME%] SUCCESS: Database updated successfully.
    echo [%DATE% %TIME%] SUCCESS: Database updated successfully. >> "%SCRIPT_DIR%update_db_weekly.log"
) else (
    echo.
    echo [%DATE% %TIME%] ERROR: Database update failed with exit code %EXIT_CODE%.
    echo [%DATE% %TIME%] ERROR: Database update failed with exit code %EXIT_CODE%. >> "%SCRIPT_DIR%update_db_weekly.log"
)

echo -------------------------------------------------------------------- >> "%SCRIPT_DIR%update_db_weekly.log"
exit /b %EXIT_CODE%
