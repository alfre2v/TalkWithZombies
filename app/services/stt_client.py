"""STT client — talks to an OpenAI-compatible STT server.

Sends raw audio as a multipart form POST to /v1/audio/transcriptions.
The STT server is optional. If it's down or misconfigured, the app logs
a warning and returns None to the caller.
"""

import logging
import mimetypes
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_EXTENSION_OVERRIDES = {"audio/webm": "webm"}


def _mime_to_extension(mime_type: str) -> str:
    """Derive a file extension from a MIME type, falling back to 'bin'."""
    base = (mime_type or "").split(";", 1)[0].strip()
    if "/" not in base:
        return "bin"
    if base in _EXTENSION_OVERRIDES:
        return _EXTENSION_OVERRIDES[base]
    ext = mimetypes.guess_extension(base)
    if ext and ext.startswith("."):
        return ext[1:]  # strip leading dot
    # Fallback: use the subtype (e.g. "audio/webm" -> "webm")
    subtype = base.split("/", 1)[1]
    return subtype or "bin"


async def check_stt_health() -> bool:
    """Return True if the STT server is reachable.

    Accepts both 200 (endpoint exists) and 404 (server is up but lacks /health).
    Any other outcome — connection error, timeout, 5xx — means the server is down.
    """
    settings = get_settings()
    if not settings.stt.is_active:
        return False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.stt.base_url}/health")
            return resp.status_code in (200, 404)
    except Exception:
        return False


async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> Optional[dict]:
    """Call the STT server's /v1/audio/transcriptions endpoint.

    Sends raw audio as multipart form data with response_format=json.
    Returns dict with keys: text, language, language_probability.
    Returns None on any failure.
    """
    settings = get_settings()
    if not settings.stt.is_active:
        logger.warning("STT transcribe skipped: feature not active (no base_url or disabled)")
        return None
    if not audio_bytes:
        logger.warning("STT transcribe skipped: no audio data provided")
        return None
    url = f"{settings.stt.base_url}/v1/audio/transcriptions"

    # Derive a sensible filename from the MIME type so the STT server
    # can identify the format. E.g. "audio/ogg" -> "audio.ogg"
    mime_type = (mime_type or "audio/webm").split(";", 1)[0].strip() or "audio/webm"
    ext = _mime_to_extension(mime_type)
    files = {
        "file": (f"audio.{ext}", audio_bytes, mime_type),
    }
    data = {
        "response_format": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.stt.timeout) as client:
            resp = await client.post(url, files=files, data=data)
            resp.raise_for_status()
            json_response = resp.json()
            text = json_response.get("text") or "No response received from STT server"
            return {
                "text": text,
                # "language" is optional in the response; default to "en" if absent
                "language": json_response.get("language") or "en",
                # "language_probability" is optional; None if the server doesn't provide it
                "language_probability": json_response.get("language_probability"),
            }
    except httpx.ConnectError as exc:
        logger.error("STT connect error (server unreachable at %s): %s", url, exc)
    except httpx.TimeoutException as exc:
        logger.error("STT timeout after %.0fs: %s", settings.stt.timeout, exc)
    except httpx.HTTPStatusError as exc:
        logger.error("STT HTTP %d from %s: %s", exc.response.status_code, url, exc)
    except Exception as exc:
        logger.warning("STT transcribe failed: %s", exc)
    return None


async def transcribe_for_show(audio_bytes: bytes, mime_type: str = "audio/webm", *, prompt: Optional[str] = None,
                              language: Optional[str] = None) -> Optional[dict]:
    """Transcribe a show listener's recording, with Whisper's confidence in what it heard.

    Asks for json: the Whisper server we deploy (whisper-fastapi) puts the
    per-segment confidence in its json reply and rejects verbose_json
    ("Invailed response_format", checked 2026-09-24). Sends the show's hints:
    `prompt` (the cast's names), `language`, and vad_filter, which cuts
    silence before decoding. Returns {"text",
    "no_speech_prob", "avg_logprob"}: the text empty when nothing was heard
    (never a placeholder), no_speech_prob the highest across segments,
    avg_logprob their average (both None without segments). Returns None on
    any failure. Upstream's transcribe_audio stays as it is for the chat.
    """
    settings = get_settings()
    if not settings.stt.is_active or not audio_bytes:
        logger.warning("Show STT skipped: %s", "no audio data" if settings.stt.is_active else "feature not active")
        return None
    url = f"{settings.stt.base_url}/v1/audio/transcriptions"
    mime_type = (mime_type or "audio/webm").split(";", 1)[0].strip() or "audio/webm"
    files = {"file": (f"audio.{_mime_to_extension(mime_type)}", audio_bytes, mime_type)}
    data = {"response_format": "json", "vad_filter": "true"}
    if prompt:
        data["prompt"] = prompt
    if language:
        data["language"] = language
    try:
        async with httpx.AsyncClient(timeout=settings.stt.timeout) as client:
            resp = await client.post(url, files=files, data=data)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Show STT transcribe failed (%s): HTTP %s: %s", url, exc.response.status_code,
                       exc.response.text[:200])
        return None
    except Exception as exc:
        logger.warning("Show STT transcribe failed (%s): %s", url, exc)
        return None
    segments = body.get("segments") or []
    no_speech = [s["no_speech_prob"] for s in segments if isinstance(s.get("no_speech_prob"), (int, float))]
    logprobs = [s["avg_logprob"] for s in segments if isinstance(s.get("avg_logprob"), (int, float))]
    return {
        "text": (body.get("text") or "").strip(),
        "no_speech_prob": max(no_speech) if no_speech else None,
        "avg_logprob": sum(logprobs) / len(logprobs) if logprobs else None,
    }
