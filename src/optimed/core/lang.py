from __future__ import annotations

from typing import Tuple

try:
    from langdetect import detect  # type: ignore
except Exception:  # pragma: no cover
    detect = None  # Fallback if not installed


_CODE_TO_NAME = {
    "en": "English",
    "sv": "Swedish",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "no": "Norwegian",
    "da": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "ru": "Russian",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
}


def detect_language_code(text: str, default: str = "en") -> str:
    """Detect BCP-47-like language code from free text, defaulting to English.

    Uses langdetect if available; otherwise returns default.
    """
    if not text or not text.strip():
        return default
    if detect is None:
        return default
    try:
        code = detect(text)
        # Normalize some variants
        code = code.lower()
        if code.startswith("zh"):
            return "zh-cn"
        return code
    except Exception:
        return default


def language_display_name(code: str) -> str:
    """Return human-friendly language name for a code.

    Falls back to the code itself if unknown.
    """
    return _CODE_TO_NAME.get(code.lower(), code)


def detect_language(text: str, default: str = "en") -> Tuple[str, str]:
    """Detect language and return (code, display_name)."""
    code = detect_language_code(text, default=default)
    return code, language_display_name(code)


