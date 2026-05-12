import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.db_models  # noqa: F401 — register ORM models with Base.metadata
from app.api.analyze import router as analyze_router
from app.api.export import router as export_router
from app.api.generate import router as generate_router
from app.api.patterns import router as patterns_router
from app.database import Base, engine

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured")
    yield


app = FastAPI(title="PatternSnap API", version="0.1.0", lifespan=lifespan)

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
app.include_router(patterns_router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/skirt-types")
def skirt_types() -> dict:
    return {
        "silhouettes": ["straight", "pencil", "a_line", "circle", "gathered", "pleated", "wrap"],
        "waistband_types": ["straight", "contoured", "elastic", "facing", "yoke"],
        "closure_types": ["center_back_zip", "side_zip", "button_fly", "hook_and_eye", "none"],
        "details": [
            "kick_pleat", "back_vent", "side_slits", "patch_pockets",
            "welt_pockets", "belt_loops", "lining_visible", "topstitching",
        ],
    }
