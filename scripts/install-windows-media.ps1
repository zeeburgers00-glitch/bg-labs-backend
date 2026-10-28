$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$Requirements = Join-Path $Root 'skills\requirements.txt'
$Venv = Join-Path $Root 'skills\.venv'
$PythonCmd = Get-Command py -ErrorAction SilentlyContinue
if (-not $PythonCmd) { $PythonCmd = Get-Command python -ErrorAction SilentlyContinue }
if (-not $PythonCmd) {
  throw 'Python 3.11 x64 is required. Install it from python.org, enable the Python launcher, then rerun this script.'
}
$Python = $PythonCmd.Source
$VersionOutput = & $Python --version 2>&1
if ($LASTEXITCODE -ne 0 -or $VersionOutput -notmatch 'Python 3\.(11|12|13)\.') {
  throw "Use Python 3.11, 3.12, or 3.13 x64. Detected: $VersionOutput"
}
if (-not (Test-Path -LiteralPath $Requirements -PathType Leaf)) {
  throw "Pinned requirements file not found: $Requirements"
}

Write-Host 'Creating the local-only ViMax skills environment...' -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath (Join-Path $Venv 'Scripts\python.exe'))) {
  & $Python -m venv $Venv
  if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $VenvPython -m pip install --disable-pip-version-check -r $Requirements
if ($LASTEXITCODE -ne 0) { throw 'Installing pinned local requirements failed.' }

Write-Host 'Checking installed media dependencies...' -ForegroundColor Cyan
& $VenvPython -c "import fastapi, pydantic, scenedetect, cv2, numpy; print('Python media imports: OK')"
if ($LASTEXITCODE -ne 0) { throw 'One or more Python media imports failed.' }
$Ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($Ffmpeg) {
  & $Ffmpeg.Source -version | Select-Object -First 1
} else {
  & $VenvPython -c "import imageio_ffmpeg; print('Bundled FFmpeg:', imageio_ffmpeg.get_ffmpeg_exe())"
  if ($LASTEXITCODE -ne 0) { throw 'Neither system FFmpeg nor imageio-ffmpeg is available.' }
}
Write-Host ''
Write-Host 'Local media dependencies installed. No model or voice was downloaded.' -ForegroundColor Green
Write-Host 'Set VIMAX_SKILLS_PYTHON to:' -ForegroundColor Yellow
Write-Host $VenvPython
Write-Host 'Configure a licensed Piper .onnx voice and matching .onnx.json before creating narration jobs.'
Write-Host 'Keep the local companion bound to 127.0.0.1; never expose it publicly.'
