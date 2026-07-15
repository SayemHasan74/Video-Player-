"""Embedded and adjacent cover-art extraction for Music Mode."""

from __future__ import annotations

from pathlib import Path


def extract_cover_art(source: str) -> bytes | None:
    """Return image bytes without trusting the tag's declared image codec.

    Some otherwise playable MP3 files declare an APIC payload as PNG while the
    payload is actually JPEG.  Mutagen exposes the original bytes, allowing Qt
    to detect the real image format from its signature.
    """
    path = Path(source)
    if not path.is_file():
        return None

    def from_tags(tags: object) -> bytes | None:
        values = tags.values() if hasattr(tags, "values") else ()
        for value in values:
            data = getattr(value, "data", None)
            if data:
                return bytes(data)
        covers = tags.get("covr") if hasattr(tags, "get") else None
        if covers:
            data = bytes(covers[0])
            if data:
                return data
        return None

    try:
        from mutagen import File as MutagenFile

        media = MutagenFile(path)
        pictures = getattr(media, "pictures", None) or ()
        for picture in pictures:
            data = bytes(getattr(picture, "data", b""))
            if data:
                return data

        tags = getattr(media, "tags", None)
        if tags is not None:
            data = from_tags(tags)
            if data:
                return data
    except Exception:
        # A tag-only or partly damaged MP3 may not have parseable MPEG frames.
        # ID3 can still recover its APIC payload safely.
        try:
            from mutagen.id3 import ID3

            data = from_tags(ID3(path))
            if data:
                return data
        except Exception:
            # A damaged tag must never take down playback.
            pass

    for name in (
        "cover.jpg", "cover.jpeg", "cover.png",
        "folder.jpg", "folder.jpeg", "folder.png",
        "front.jpg", "front.jpeg", "front.png",
    ):
        candidate = path.parent / name
        try:
            if candidate.is_file():
                return candidate.read_bytes()
        except OSError:
            continue
    return None
