import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.v1.router import api_router
from backend.app.core.config import settings


def _prewarm_models():
	"""Pre-warm AI detection models in the background so the first proctoring frame runs instantly."""
	try:
		from backend.app.proctoring.analyzer import _models
		_models()
	except Exception:
		pass


@asynccontextmanager
async def lifespan(app: FastAPI):
	if os.getenv("TESTING_ENV") != "1":
		threading.Thread(target=_prewarm_models, daemon=True).start()
	yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

# Enable CORS for live cross-origin frontend-to-backend communication on Render / custom domains
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

app.mount(
	"/demo",
	StaticFiles(directory=Path(__file__).parent / "static", html=True),
	name="demo",
)
app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(api_router)

# Serve compiled Frontend static assets and SPA if Frontend/dist is present
frontend_dist = Path(__file__).resolve().parents[2] / "Frontend" / "dist"
if frontend_dist.exists() and (frontend_dist / "index.html").exists():
	assets_dir = frontend_dist / "assets"
	if assets_dir.exists():
		app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend_assets")

	@app.get("/{full_path:path}", include_in_schema=False)
	async def serve_spa(full_path: str):
		if full_path.startswith("api/") or full_path == "api" or full_path.startswith("demo"):
			raise HTTPException(status_code=404, detail="Not Found")
		target_file = frontend_dist / full_path
		if full_path and target_file.is_file():
			return FileResponse(target_file)
		return FileResponse(frontend_dist / "index.html")
