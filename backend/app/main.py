import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

# Load .env for local dev — override=False means system env vars always win
load_dotenv(override=False)
from fastapi.middleware.cors import CORSMiddleware

import app.db_models  # noqa: F401 — register ORM models with Base.metadata
from app.models.features import GarmentType
from app.api.analyze import router as analyze_router
from app.api.export import router as export_router
from app.api.generate import router as generate_router
from app.api.instructions import router as instructions_router
from app.api.patterns import router as patterns_router
from app.api.provider import router as provider_router
from app.api.templates import router as templates_router
from app.database import Base, engine

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured")
    yield


app = FastAPI(title="Seamster API", version="0.1.0", lifespan=lifespan)

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(generate_router, prefix="/api")
app.include_router(instructions_router, prefix="/api")
app.include_router(patterns_router, prefix="/api")
app.include_router(provider_router, prefix="/api")
app.include_router(templates_router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    from app.llm import get_provider

    try:
        provider = get_provider()
        return {"status": "ok", "llm_provider": provider.name, "llm_model": provider.model}
    except ValueError as exc:
        # Misconfigured LLM_PROVIDER — report it without failing the health probe.
        return {"status": "ok", "llm_provider": "invalid", "llm_error": str(exc)}


@app.get("/api/garment-types")
def garment_types() -> dict:
    return {"types": [t.value for t in GarmentType]}


@app.get("/api/skirt-types")
def skirt_types() -> dict:
    """Kept for backward compatibility."""
    return {
        "silhouettes": ["straight", "pencil", "a_line", "circle", "gathered", "pleated", "wrap"],
        "waistband_types": ["straight", "contoured", "elastic", "facing", "yoke"],
        "closure_types": ["center_back_zip", "side_zip", "button_front", "hook_and_eye", "none"],
        "details": [
            "kick_pleat", "back_vent", "side_slits", "patch_pockets",
            "welt_pockets", "belt_loops", "lining_visible", "topstitching",
        ],
    }
