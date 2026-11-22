@echo off
setlocal EnableExtensions DisableDelayedExpansion
for /f "tokens=2 delims=:" %%C in ('chcp') do set "DJ_OLD_CODEPAGE=%%C"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "DOUJIE_START_LOG="
set "DJ_PUSHED="
set "DJ_PY_OPTION="
set "DJ_EXIT=1"

if not defined LOCALAPPDATA goto project_log
set "DJ_LOG_DIR=%LOCALAPPDATA%\DoujieStudio"
if not exist "%DJ_LOG_DIR%\." md "%DJ_LOG_DIR%" 2>nul
set "DOUJIE_START_LOG=%DJ_LOG_DIR%\startup.log"
call :try_log
if not errorlevel 1 goto log_ready
:project_log
set "DOUJIE_START_LOG=%~dp0doujie-startup.log"
call :try_log
if not errorlevel 1 goto log_ready
set "DOUJIE_START_LOG="
echo Could not open a startup log. Diagnostics will appear in this window.
:log_ready
if defined DOUJIE_START_LOG echo Startup log "%DOUJIE_START_LOG%"
call :record "Startup requested."
pushd "%~dp0" >nul
if errorlevel 1 goto bad_directory
set "DJ_PUSHED=1"
if not exist "launch.py" goto missing_launcher

if defined DOUJIE_PYTHON goto use_override
if defined DOUJIE_VOICE_DIR if exist "%DOUJIE_VOICE_DIR%\runtime\python\python.exe" (
  set "DJ_PYTHON=%DOUJIE_VOICE_DIR%\runtime\python\python.exe"
  call :record "Trying configured voice runtime."
  goto run
)
if exist "voice\runtime\python\python.exe" (
  set "DJ_PYTHON=voice\runtime\python\python.exe"
  call :record "Trying bundled voice runtime."
  goto run
)
if exist "..\windring-island\voice\runtime\python\python.exe" (
  set "DJ_PYTHON=..\windring-island\voice\runtime\python\python.exe"
  call :record "Trying adjacent Windring runtime."
  goto run
)
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto use_py
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto no_python
set "DJ_PYTHON=python"
call :record "Using system Python."
goto run

:use_override
set "DJ_PYTHON=%DOUJIE_PYTHON%"
call :record "Trying explicit Python override."
goto run
:use_py
set "DJ_PYTHON=py"
set "DJ_PY_OPTION=-3"
call :record "Using Windows Python launcher."
:run
rem Keep Python/Electron output on the caller's console. Diagnostics written to disk
rem are selected messages only: command arguments, environment and live events stay out.
"%DJ_PYTHON%" %DJ_PY_OPTION% -u launch.py %*
set "DJ_EXIT=%ERRORLEVEL%"
call :record "Launcher exit code %DJ_EXIT%."
if "%DJ_EXIT%"=="0" goto finish
if "%DJ_EXIT%"=="9009" echo Python could not start. Check DOUJIE_PYTHON or install Python 3.10 or newer.
goto failed

:bad_directory
echo Cannot enter the project directory. Check the folder permissions.
call :record "Failed to enter project directory."
goto failed
:missing_launcher
echo Missing launch.py. Extract the complete project before running this script.
call :record "Missing launch.py in the project directory."
goto failed
:no_python
echo Install Python 3.10 or newer, or set DOUJIE_PYTHON to python.exe.
call :record "No supported Python runtime found."
:failed
echo(
echo Startup failed (exit code %DJ_EXIT%). See the error above.
if defined DOUJIE_START_LOG echo Startup log "%DOUJIE_START_LOG%"
pause
:finish
if defined DJ_PUSHED popd
if defined DJ_OLD_CODEPAGE chcp %DJ_OLD_CODEPAGE% >nul
endlocal & exit /b %DJ_EXIT%

:try_log
(type nul >>"%DOUJIE_START_LOG%") 2>nul || exit /b 1
if not exist "%DOUJIE_START_LOG%" exit /b 1
exit /b 0

:record
if defined DOUJIE_START_LOG >>"%DOUJIE_START_LOG%" echo([%date% %time%] %~1
exit /b 0
