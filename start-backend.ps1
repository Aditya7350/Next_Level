Write-Host "Starting AI Interview Backend with Proctoring (Python 3.12)..." -ForegroundColor Cyan
if (Test-Path ".\.venv-proctoring\Scripts\python.exe") {
    & ".\.venv-proctoring\Scripts\python.exe" -m uvicorn backend.app.main:app --reload --port 8000
} else {
    Write-Host "Warning: .venv-proctoring not found. Running with uv run..." -ForegroundColor Yellow
    uv run uvicorn backend.app.main:app --reload --port 8000
}
