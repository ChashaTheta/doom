$ErrorActionPreference = "Stop"
Write-Host "== Jarvis Local setup ==" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python was not found. Install Python 3.11+ (64-bit) and enable Add Python to PATH." -ForegroundColor Red
    exit 1
}

python --version
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

New-Item -ItemType Directory -Force -Path "data", "workspace", "workspace\notes" | Out-Null
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example" -ForegroundColor Green
}
Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next: install/start Ollama, then run:"
Write-Host '  ollama pull qwen2.5:3b'
Write-Host '  .\.venv\Scripts\Activate.ps1'
Write-Host '  python -m uvicorn app:app --host 127.0.0.1 --port 8000'
