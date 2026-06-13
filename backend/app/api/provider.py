"""Runtime LLM provider selection for the UI toggle.

GET  /api/provider → the active provider plus the list the toggle should offer.
POST /api/provider → switch the active provider (e.g. Claude ↔ local Ollama).

The choice is held in process memory (see app.llm.factory); it overrides the
LLM_PROVIDER env var for the life of the server but is not persisted to disk.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.llm import AVAILABLE_PROVIDERS, get_provider, set_provider

logger = logging.getLogger(__name__)
router = APIRouter()

# Human-readable labels for each provider key, shown in the UI toggle.
_LABELS: dict[str, str] = {
    "anthropic": "Claude",
    "ollama": "Local (Ollama)",
}


class ProviderRequest(BaseModel):
    provider: str


def _state() -> dict:
    """Current active provider + the options the toggle can present."""
    try:
        active = get_provider()
        active_name, model = active.name, active.model
    except ValueError as exc:
        # Misconfigured key — report without crashing so the UI can still render.
        active_name, model = "invalid", str(exc)
    return {
        "active": active_name,
        "model": model,
        "providers": [{"key": k, "label": _LABELS.get(k, k)} for k in AVAILABLE_PROVIDERS],
    }


@router.get("/provider")
def get_provider_endpoint() -> dict:
    """Return the active LLM provider and the available options."""
    return _state()


@router.post("/provider")
def set_provider_endpoint(req: ProviderRequest) -> dict:
    """Switch the active LLM provider at runtime."""
    try:
        set_provider(req.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info("LLM provider switched to '%s' via API", req.provider)
    return _state()
