"""Gemini structured extraction of the Teams Assignments list (R40, R41).

The image bytes go inline in the request (no Files API upload), and Gemini copies the due
text exactly; dates are resolved locally (R43). Any failure raises GeminiUnavailable with a
plain reason, and the pipeline falls back to Tesseract.
"""

from __future__ import annotations

import io
import json

from autoplanner.config import GEMINI_TIMEOUT_S
from autoplanner.importers.text_parser import RawRow

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "rows": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "course": {"type": "STRING"},
                    "due_text": {"type": "STRING"},
                    "status": {"type": "STRING", "enum": ["upcoming", "past_due", "completed", "unknown"]},
                },
                "required": ["title", "due_text", "status"],
            },
        }
    },
    "required": ["rows"],
}
PROMPT = (
    "This is a screenshot of the Microsoft Teams Assignments list. Return one row per assignment "
    "shown. title: the assignment title. course: the class or team name, if shown. due_text: copy "
    "the due line exactly as written (for example 'Due tomorrow at 11:59 PM'); do not interpret or "
    "convert dates. status: completed if it is marked completed or turned in, past_due if it says "
    "past due or missing, upcoming otherwise, unknown if unclear. Ignore everything that is not an "
    "assignment."
)
MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class GeminiUnavailable(Exception):
    """Gemini could not be used for this image; the message is shown to the user."""


def image_mime(data: bytes) -> str:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
    except Exception:
        raise ValueError("This file isn't a readable image.") from None
    if fmt not in MIME:
        raise ValueError("Use a PNG, JPEG or WebP screenshot.")
    return MIME[fmt]


def make_client(api_key: str):
    from google import genai
    from google.genai import types

    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_S * 1000))


def explain(exc: Exception) -> str:
    """A plain-language reason for a Gemini failure."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None) or ""
    text = f"{status} {getattr(exc, 'message', '') or ''} {exc}"
    if code == 401 or "ACCESS_TOKEN_TYPE_UNSUPPORTED" in text:
        return (f"Gemini rejected the API key (HTTP {code} {status}). The key was sent as an API key "
                "and Google doesn't accept this key type for this request.")
    if code == 429:
        return "Gemini's free quota or rate limit was reached."
    if code == 503:
        return "Gemini's model is overloaded right now."
    if code == 404:
        return "The Gemini model in GEMINI_MODEL wasn't found."
    if code in (400, 403) and "API_KEY" in text:
        return "Gemini says the API key is invalid."
    if "timeout" in type(exc).__name__.lower() or "timed out" in text.lower():
        return f"Gemini didn't answer within {GEMINI_TIMEOUT_S} seconds."
    if code:
        return f"Gemini returned an error (HTTP {code} {status})."
    return f"Gemini couldn't be reached ({type(exc).__name__})."


def extract_rows(image: bytes, *, api_key: str | None, model: str | None, client=None) -> list[RawRow]:
    if not api_key or not model:
        raise GeminiUnavailable("Gemini isn't configured.")
    from google.genai import types

    mime = image_mime(image)
    try:
        client = client or make_client(api_key)
        response = client.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=image, mime_type=mime), PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=SCHEMA,
                                               temperature=0),
        )
        payload = json.loads(response.text)
    except json.JSONDecodeError:
        raise GeminiUnavailable("Gemini's answer wasn't valid JSON.") from None
    except Exception as exc:
        raise GeminiUnavailable(explain(exc)) from None

    rows = []
    for item in payload.get("rows", []) if isinstance(payload, dict) else []:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        course = str(item.get("course") or "").strip() or None
        due = str(item.get("due_text") or "").strip()
        status = item.get("status") if item.get("status") in ("upcoming", "past_due", "completed") else "unknown"
        rows.append(RawRow(title=title, course=course, due_text=due, status=status,
                           source_text=" / ".join(x for x in (title, course, due) if x)))
    if not rows:
        raise GeminiUnavailable("Gemini found no assignments in the image.")
    return rows
