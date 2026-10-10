"""Main FastAPI application entrypoint for Rentaliq."""

import logging
from typing import Any, Dict
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as agent_router
from app.config import settings

# Configure standard logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rentaliq")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Rentaliq is an AI-powered Equipment Rental Decision Agent. "
        "It interprets contractor inquiries, executes verification tools, "
        "enforces hard safety policies, and produces AUTO_QUOTE, REQUEST_INFO, "
        "or MANUAL_REVIEW decisions with complete audit traces."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for local Streamlit or web UI integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include agent routes
app.include_router(agent_router)


from pathlib import Path
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML_PATH = STATIC_DIR / "index.html"
LOGIN_HTML_PATH = STATIC_DIR / "login.html"
REGISTER_HTML_PATH = STATIC_DIR / "register.html"

# Mount static files directory
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_dashboard():
    """Serve the interactive demonstration web app interface."""
    if INDEX_HTML_PATH.exists():
        return HTMLResponse(content=INDEX_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Rentaliq Agent API</h1><p>Visit <a href='/docs'>/docs</a></p>")


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def serve_login():
    """Serve the contractor and provider login page."""
    if LOGIN_HTML_PATH.exists():
        return HTMLResponse(content=LOGIN_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Rentaliq Login</h1><p>Login page not found.</p>", status_code=404)


@app.get("/register", response_class=HTMLResponse, include_in_schema=False)
def serve_register():
    """Serve the contractor and provider registration page."""
    if REGISTER_HTML_PATH.exists():
        return HTMLResponse(content=REGISTER_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Rentaliq Registration</h1><p>Registration page not found.</p>", status_code=404)


@app.get("/health", summary="Service health check", tags=["System"])
def health_check() -> Dict[str, Any]:
    """Return health status and active configuration mode."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "execution_mode": settings.execution_mode,
        "llm_configured": bool(settings.llm_api_key),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
