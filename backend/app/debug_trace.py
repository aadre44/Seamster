"""Debug trace of the most recent AI analyze + generate run.

Every /api/analyze call starts a fresh trace and every /api/generate call fills
in (or replaces) the generate half, so ``backend/debug/last_run.json`` always
holds exactly one run — the most recent — end to end:

  analyze:  request info (garment type, image sizes, force-contours flag), the
            exact system + user prompts sent to the vision model, the raw LLM
            response text, and the parsed/backfilled features that came out.
  generate: the request (features + measurements + shape_mode), a chronological
            event log of every AI decision made along the way (learned-template
            hits, each LLM fallback attempt with its prompt problems and raw
            response, composition plans, vision-contour accept/skip), the final
            .psnap output, and a piece summary.

The file is a dev/analysis aid: it is overwritten on every run, ignored by git,
and tracing failures are swallowed (a broken trace must never break the API).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/debug/last_run.json (backend/ is this file's parent's parent)
TRACE_PATH = Path(__file__).resolve().parent.parent / "debug" / "last_run.json"

# In-progress event buffer for the current generate call. Guarded by _lock;
# capped so a runaway loop cannot balloon the file.
_MAX_EVENTS = 500
_lock = threading.Lock()
_events: list[dict] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> dict:
    try:
        return json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(data: dict) -> None:
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


def _piece_summary(psnap: dict | None) -> dict | None:
    if not isinstance(psnap, dict):
        return None
    pieces = psnap.get("pieces", [])
    return {
        "piece_count": len(pieces),
        "element_count": len(psnap.get("elements", [])),
        "connection_count": len(psnap.get("connections", [])),
        "notice": psnap.get("notice"),
        "pieces": [
            {
                "name": p.get("name"),
                "source": p.get("source", "engine"),
                "detail": p.get("detail"),
                "cutQty": p.get("cutQty"),
                "onFold": p.get("onFold"),
            }
            for p in pieces
        ],
    }


# ── Public API ────────────────────────────────────────────────────────────────

def trace_analyze(
    request: dict,
    system_prompt: str,
    user_prompt: str,
    raw_response: str | None,
    features: dict | None,
    error: str | None = None,
) -> None:
    """Start a new run: record the analyze call and clear any previous generate."""
    try:
        with _lock:
            _write({
                "analyze": {
                    "timestamp": _now(),
                    "request": request,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": raw_response,
                    "features": features,
                    "error": error,
                },
                "generate": None,
            })
    except Exception:
        logger.debug("debug_trace.trace_analyze failed", exc_info=True)


def begin_generate() -> None:
    """Reset the event buffer at the start of a generate call."""
    try:
        with _lock:
            _events.clear()
    except Exception:
        logger.debug("debug_trace.begin_generate failed", exc_info=True)


def add_event(stage: str, **payload) -> None:
    """Record one AI decision inside the current generate call (cheap, in-memory)."""
    try:
        with _lock:
            if len(_events) < _MAX_EVENTS:
                _events.append({"timestamp": _now(), "stage": stage, **payload})
    except Exception:
        logger.debug("debug_trace.add_event failed", exc_info=True)


def trace_generate(request: dict, psnap: dict | None, error: str | None = None) -> None:
    """Attach the generate half (request, buffered events, output) to the trace.

    Keeps the analyze half already in the file, so an analyze → generate flow
    lands as one complete run; regenerating replaces only the generate half."""
    try:
        with _lock:
            data = _read()
            data.setdefault("analyze", None)
            data["generate"] = {
                "timestamp": _now(),
                "request": request,
                "events": list(_events),
                "summary": _piece_summary(psnap),
                "output": psnap,
                "error": error,
            }
            _write(data)
            _events.clear()
    except Exception:
        logger.debug("debug_trace.trace_generate failed", exc_info=True)
