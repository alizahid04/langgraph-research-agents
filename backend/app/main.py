"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_workflow import router as workflow_router
from app.config import get_settings
from app.database import init_db
from app.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Research & Decision Intelligence Platform")
    logger.info(
        "OpenRouter configured: %s | Tavily configured: %s",
        settings.openrouter_configured,
        settings.tavily_configured,
    )
    if not settings.openrouter_configured or not settings.tavily_configured:
        logger.warning(
            "Missing API keys — research runs will be rejected with a 400 until "
            "OPENROUTER_API_KEY and TAVILY_API_KEY are set in .env"
        )
    init_db()
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Multi-Agent Research & Decision Intelligence Platform",
    description="Production-grade multi-agent research system built with FastAPI + LangGraph.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflow_router)


@app.get("/api/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "openrouter_configured": settings.openrouter_configured,
        "tavily_configured": settings.tavily_configured,
    }


# Serve the frontend (dashboard) as static files. index.html IS the dashboard —
# there is no separate landing page.
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
