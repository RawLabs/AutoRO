$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DriveRoot = $AppDir
$PythonExe = Join-Path $DriveRoot "Tools\Python\python-3.12.10-embed-amd64\python.exe"
$DatabasePath = Join-Path $DriveRoot "runtime\Database\autoro.db"
$PopplerBin = Join-Path $DriveRoot "Tools\Poppler\poppler-26.02.0\Library\bin"
$LlamafileExe = Join-Path $DriveRoot "Llamafile\llamafile-0.10.3.exe"
$ModelFile = Join-Path $DriveRoot "Models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
$Port = 8000
$ModelPort = 8080
$Url = "http://127.0.0.1:$Port"

Set-Location $AppDir

if (-not (Test-Path $PythonExe)) {
    Write-Host "AutoRO portable Python was not found:" -ForegroundColor Red
    Write-Host $PythonExe
    Read-Host "Press Enter to close"
    exit 1
}

if (-not (Test-Path $DatabasePath)) {
    Write-Host "AutoRO database was not found:" -ForegroundColor Red
    Write-Host $DatabasePath
    Read-Host "Press Enter to close"
    exit 1
}

if (-not (Test-Path $LlamafileExe)) {
    Write-Host "AutoRO Llamafile was not found:" -ForegroundColor Red
    Write-Host $LlamafileExe
    Read-Host "Press Enter to close"
    exit 1
}

if (-not (Test-Path $ModelFile)) {
    Write-Host "AutoRO Qwen3 model was not found:" -ForegroundColor Red
    Write-Host $ModelFile
    Read-Host "Press Enter to close"
    exit 1
}

$PdfToText = Join-Path $PopplerBin "pdftotext.exe"
if (-not (Test-Path $PdfToText)) {
    Write-Host "Poppler pdftotext.exe was not found:" -ForegroundColor Red
    Write-Host $PdfToText
    Write-Host "Estimate conversion requires Poppler on Windows."
    Read-Host "Press Enter to close"
    exit 1
}

$env:PATH = "$PopplerBin;$env:PATH"

& $PythonExe -c "import fastapi,jinja2,uvicorn,reportlab,PIL" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "AutoRO Python dependencies are missing." -ForegroundColor Red
    Write-Host "Expected packages include FastAPI, Jinja2, Uvicorn, ReportLab, and Pillow."
    Write-Host "Check Tools\Python and Tools\Wheelhouse on the SSD."
    Read-Host "Press Enter to close"
    exit 1
}

& $PythonExe -c "import shutil,sys; sys.exit(0 if shutil.which('pdftotext') else 1)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "pdftotext.exe is not available on PATH." -ForegroundColor Red
    Write-Host $PdfToText
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host "Starting AutoRO server and model..."
Write-Host "Separate windows will open. Leave them open while using AutoRO."
Write-Host "If startup fails, they will stay open and show the error."

Start-Process -FilePath "cmd.exe" -ArgumentList "/k", "title AutoRO Qwen Model && start_model.bat" -WorkingDirectory "$AppDir\Llamafile"
$Command = "`"$PythonExe`" -m uvicorn app.main:app --host 127.0.0.1 --port $Port"
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", $Command -WorkingDirectory $AppDir

Write-Host "Waiting for AutoRO and the shared Qwen model to respond..."
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    $appReady = $false
    $modelReady = $false
    try {
        $client = New-Object Net.Sockets.TcpClient
        $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $connected = $iar.AsyncWaitHandle.WaitOne(1000, $false)
        if ($connected -and $client.Connected) {
            $client.EndConnect($iar)
            $appReady = $true
        }
        $client.Close()
    } catch {}
    try {
        $modelResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$ModelPort/v1/models" -TimeoutSec 2
        $modelReady = $modelResponse.StatusCode -ge 200 -and $modelResponse.StatusCode -lt 300
    } catch {}
    if ($appReady -and $modelReady) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $ready) {
    Write-Host "AutoRO or the Qwen model did not become ready." -ForegroundColor Red
    Write-Host "Check the AutoRO server and Qwen model windows for errors."
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host "AutoRO is ready. Opening browser..."
Start-Process $Url
Write-Host "Keep the AutoRO server and model windows open while using AutoRO."
Read-Host "Press Enter to close"
