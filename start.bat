@echo off
REM NovelAgent one-key launcher (Windows). Double-click to start backend API + web UI.
REM Behavior is driven by config\server.yaml (host / port / CORS / IP whitelist / open_browser).
REM You may append args to override, e.g.:  start.bat --port 9000 --host 0.0.0.0
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM First run: build the web UI if dist is missing (needs Node.js + npm).
if exist "web\dist\index.html" goto run
if not exist "web\package.json" goto run

where npm >nul 2>nul
if errorlevel 1 goto nonode

echo [NovelAgent] Building web UI (first run)...
pushd web
call npm install
call npm run build
popd
goto run

:nonode
echo [NovelAgent] Node.js/npm not found; serving fallback page.
echo [NovelAgent] Install Node.js, then in the web folder run: npm install
echo [NovelAgent] followed by: npm run build

:run
where py >nul 2>nul
if errorlevel 1 goto usepython
py -m app.main serve %*
goto done

:usepython
python -m app.main serve %*

:done
set EXITCODE=%errorlevel%
if not "%EXITCODE%"=="0" (
    echo.
    echo [NovelAgent] Startup failed with exit code %EXITCODE%.
    echo [NovelAgent] Make sure dependencies are installed:  pip install -e .
    pause
)
endlocal
