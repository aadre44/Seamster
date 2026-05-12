import asyncio
import base64
import json
import logging
import os

import anthropic

from app.models.features import SkirtFeatures
from app.vision.prompts import SYSTEM_PROMPT, USER_PROMPT

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _build_content(front_bytes: bytes, back_bytes: bytes | None) -> list:
    images = [front_bytes] if back_bytes is None else [front_bytes, back_bytes]
    content: list = []
    for img_bytes in images:
        b64 = base64.standard_b64encode(img_bytes).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })
    content.append({"type": "text", "text": USER_PROMPT})
    return content


async def _call_claude(front_bytes: bytes, back_bytes: bytes | None) -> str:
    client = _get_client()
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_content(front_bytes, back_bytes)}],
    )
    return response.content[0].text


async def analyze_skirt(front_bytes: bytes, back_bytes: bytes | None = None) -> SkirtFeatures:
    """Call Claude vision API and parse the structured garment features response."""
    raw_text = ""
    for attempt in range(2):
        try:
            raw_text = await _call_claude(front_bytes, back_bytes)
            break
        except anthropic.RateLimitError:
            if attempt == 0:
                await asyncio.sleep(2)
                continue
            raise
        except anthropic.APIError:
            if attempt == 0:
                await asyncio.sleep(2)
                continue
            raise

    logger.debug("Claude raw response: %s", raw_text[:500])

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Claude returned invalid JSON: {raw_text[:200]}") from exc

    # Check for explicit no-skirt signal in notes
    notes: str = data.get("notes", "")
    if "no skirt" in notes.lower() or "cannot identify" in notes.lower():
        raise ValueError(
            "We couldn't identify a skirt in this photo. "
            "Please upload a clear front-view photo of a skirt."
        )

    return SkirtFeatures.model_validate(data)
