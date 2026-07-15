"""Language-code normalization shared by mpv preferences and track UI."""

from __future__ import annotations

import re


# ISO 639-2/T values seen most often in media containers.  mpv accepts
# ISO 639-1 directly, so normalize known three-letter forms back to the
# compact two-letter spelling and preserve other valid three-letter codes.
ISO_639_2_TO_1: dict[str, str] = {
    "ara": "ar", "ces": "cs", "chi": "zh", "zho": "zh",
    "dan": "da", "deu": "de", "dut": "nl", "nld": "nl",
    "eng": "en", "fin": "fi", "fra": "fr", "fre": "fr",
    "gre": "el", "ell": "el", "heb": "he", "hin": "hi",
    "hun": "hu", "ind": "id", "ita": "it", "jpn": "ja",
    "kor": "ko", "msa": "ms", "may": "ms", "nor": "no",
    "pol": "pl", "por": "pt", "ron": "ro", "rum": "ro",
    "rus": "ru", "spa": "es", "swe": "sv", "tha": "th",
    "tur": "tr", "ukr": "uk", "vie": "vi",
}


def normalize_language_code(value: object) -> str:
    """Return a canonical lower-case ISO code, or an empty unknown value."""
    text = str(value or "").strip().casefold().replace("_", "-")
    if not text:
        return ""
    # Container tags sometimes include a regional suffix.  mpv's language
    # preference matching is most reliable with the base ISO identifier.
    base = text.split("-", 1)[0]
    if base in {"und", "unk", "unknown", "none"}:
        return ""
    if base == "jp":  # common but non-standard tag
        return "ja"
    if re.fullmatch(r"[a-z]{2}", base):
        return base
    if re.fullmatch(r"[a-z]{3}", base):
        return ISO_639_2_TO_1.get(base, base)
    return ""


def normalize_language_preferences(value: object) -> str:
    """Normalize a comma/space-separated mpv language preference list."""
    parts = re.split(r"[,;\s]+", str(value or ""))
    normalized: list[str] = []
    for part in parts:
        code = normalize_language_code(part)
        if code and code not in normalized:
            normalized.append(code)
    return ",".join(normalized)
