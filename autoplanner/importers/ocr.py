"""Tesseract OCR fallback (R41). Images are processed in memory only (R42)."""

from __future__ import annotations

import io


def tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_text(image: bytes) -> str:
    """Grayscale, invert dark themes, upscale 2x and stretch the contrast, then read the text."""
    import pytesseract
    from PIL import Image, ImageOps, ImageStat

    with Image.open(io.BytesIO(image)) as original:
        gray = original.convert("L")
    if ImageStat.Stat(gray).mean[0] < 110:  # dark theme: light text on a dark background
        gray = ImageOps.invert(gray)
    gray = gray.resize((gray.width * 2, gray.height * 2), Image.Resampling.LANCZOS)
    gray = ImageOps.autocontrast(gray)
    return pytesseract.image_to_string(gray, config="--psm 4")
