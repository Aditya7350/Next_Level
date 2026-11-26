@echo off
if exist ".venv-proctoring\Scripts\python.exe" (
    echo Starting AI Interview Backend with Proctoring (Python 3.12)...
    ".venv-proctoring\Scripts\python.exe" -m uvicorn backend.app.main:app --reload --port 8000
) else (
    echo Starting AI Interview Backend with uv...
    uv run uvicorn backend.app.main:app --reload --port 8000
)
