@echo off
setlocal EnableExtensions

set "APP_DIR=%~dp0"
set "DRIVE_ROOT=%APP_DIR%"
set "PYTHON_EXE=%DRIVE_ROOT%Tools\Python\python-3.12.10-embed-amd64\python.exe"
set "POPPLER_BIN=%DRIVE_ROOT%Tools\Poppler\poppler-26.02.0\Library\bin"
set "URL=http://127.0.0.1:8000"

pushd "%APP_DIR%" || (
    echo Could not open the AutoRO folder:
    echo %APP_DIR%
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo AutoRO portable Python was not found:
    echo %PYTHON_EXE%
    echo.
    echo Confirm the SSD contains Tools\Python\python-3.12.10-embed-amd64.
    pause
    exit /b 1
)

if not exist "%DRIVE_ROOT%runtime\Database\autoro.db" (
    echo AutoRO database was not found:
    echo %DRIVE_ROOT%runtime\Database\autoro.db
    echo.
    echo Confirm the SSD contains runtime\Database\autoro.db.
    pause
    exit /b 1
)

if not exist "%POPPLER_BIN%\pdftotext.exe" (
    echo Poppler pdftotext.exe was not found:
    echo %POPPLER_BIN%\pdftotext.exe
    echo.
    echo Estimate conversion requires Poppler on Windows.
    pause
    exit /b 1
)

if not exist "%DRIVE_ROOT%Llamafile\llamafile-0.10.3.exe" (
    echo Llamafile was not found:
    echo %DRIVE_ROOT%Llamafile\llamafile-0.10.3.exe
    pause
    exit /b 1
)

if not exist "%DRIVE_ROOT%Models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf" (
    echo Translator model was not found:
    echo %DRIVE_ROOT%Models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf
    pause
    exit /b 1
)

set "PATH=%POPPLER_BIN%;%PATH%"

"%PYTHON_EXE%" -c "import fastapi,jinja2,uvicorn,reportlab,PIL" >nul 2>nul
if errorlevel 1 (
    echo AutoRO Python dependencies are missing or embedded Python cannot load site-packages.
    echo.
    echo Test command:
    echo "%PYTHON_EXE%" -c "import fastapi,jinja2,uvicorn,reportlab,PIL"
    echo.
    echo Check Tools\Python, the python312._pth file, and Tools\Wheelhouse.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import shutil,sys; sys.exit(0 if shutil.which('pdftotext') else 1)" >nul 2>nul
if errorlevel 1 (
    echo pdftotext.exe is not available on PATH.
    echo Expected:
    echo %POPPLER_BIN%\pdftotext.exe
    pause
    exit /b 1
)

echo Starting AutoRO server and model...
echo Separate windows will open. Leave them open while using AutoRO.
echo.

start "AutoRO Qwen Model" /D "%APP_DIR%Llamafile" cmd.exe /k call "start_model.bat"

start "AutoRO Server" /D "%APP_DIR%" cmd.exe /k ""%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo Waiting for AutoRO and the shared Qwen model to respond...
for /l %%i in (1,1,120) do (
    "%PYTHON_EXE%" -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1',8000)) == 0 else 1)" >nul 2>nul
    if not errorlevel 1 (
        "%PYTHON_EXE%" -c "import sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/v1/models',timeout=2); sys.exit(0 if 200 ^<= r.status ^< 300 else 1)" >nul 2>nul
        if not errorlevel 1 goto ready
    )
    timeout /t 1 /nobreak >nul
)

echo.
echo AutoRO or its translator model did not become ready.
echo Check the AutoRO Server and AutoRO Qwen Model windows for the exact error.
echo.
pause
exit /b 1

:ready
echo AutoRO is ready. Opening browser...
start "" "%URL%"
echo.
echo Keep the AutoRO Server and model windows open while using AutoRO.
pause
popd
