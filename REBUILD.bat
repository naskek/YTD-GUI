@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_installer.ps1"
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%BUILD_EXIT_CODE%"=="0" (
  echo Build completed successfully.
) else (
  echo Build failed with exit code %BUILD_EXIT_CODE%.
)
pause
exit /b %BUILD_EXIT_CODE%
