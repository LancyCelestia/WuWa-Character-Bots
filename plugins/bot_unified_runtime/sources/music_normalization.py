from __future__ import annotations

import hashlib
import re
import unicodedata

from plugins.bot_unified_runtime.contracts.music import MusicTrack

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_music_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return _WHITESPACE_RE.sub(" ", normalized)


def normalize_artist_names(track: MusicTrack) -> list[str]:
    names = {
        normalize_music_text(contributor.name)
        for contributor in track.contributors
        if "performer" in contributor.roles or "featured_artist" in contributor.roles
    }
    return sorted(name for name in names if name)


def music_fingerprint(track: MusicTrack) -> str:
    duration_bucket = "unknown"
    if track.duration_ms is not None:
        duration_bucket = str(round(track.duration_ms / 5000))
    identity = "\n".join(
        [normalize_music_text(track.title), *normalize_artist_names(track), duration_bucket]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def canonical_key(track: MusicTrack) -> str:
    isrc = str(track.isrc or "").strip().upper()
    if isrc:
        return f"isrc:{isrc}"
    return f"fp:{music_fingerprint(track)}"
