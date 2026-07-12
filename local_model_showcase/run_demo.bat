@echo off
setlocal
cd /d "%~dp0"
echo [1/3] Installing Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo [2/3] Downloading YOLO weights...
python download_models.py
if errorlevel 1 goto failed

echo [3/3] Starting local demo service...
start "" http://127.0.0.1:9100
python -m uvicorn app:app --host 0.0.0.0 --port 9100
goto end

:failed
echo.
echo Startup failed. Check the error above.
pause

:end
endlocal
