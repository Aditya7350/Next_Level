from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.api.v1.router import api_router
from backend.app.core.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")
app.mount(
	"/demo",
	StaticFiles(directory=Path(__file__).parent / "static", html=True),
	name="demo",
)
app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(api_router)
