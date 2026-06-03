"""Pure text-normalization helpers for artist/title matching and dedup.

Stdlib-only by design so it can be unit-tested without app dependencies.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Qualifier keywords that mark a parenthetical/bracketed group as a
# *version* of a song rather than part of its title.
_VERSION_KEYWORDS = (
    "live", "demo", "remix", "mix", "remaster", "remastered", "session",
    "single version", "album version", "radio edit", "edit", "version",
    "mono", "stereo", "instrumental", "acoustic", "bonus", "reissue",
    "outtake", "take", "alt", "alternate", "rehearsal", "rerecorded",
    "re-recorded", "extended", "club mix", "tibet mix",
)

_GROUP_RE = re.compile(r"\s*[\(\[]([^()\[\]]*)[\)\]]\s*$")
_FEAT_RE = re.compile(r"\s*(?:\(?\s*(?:feat|ft|featuring)\.?\s+[^)]*\)?)\s*$",
                      re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@lru_cache(maxsize=8192)
def normalize_artist(name: str | None) -> str | None:
    """Accent-insensitive, lowercased artist key (Voïvod == Voivod)."""
    if not name:
        return name
    return _strip_accents(name).lower()


@lru_cache(maxsize=8192)
def normalize_title(title: str | None) -> str:
    """Collapse version variants of a song to one signature.

    Strips trailing (live)/(demo)/(remix)/(... session)/(remaster) etc.,
    "feat. ..." clauses, punctuation, and accents. Returns "" only if the
    title was empty; an all-qualifier title falls back to its stripped form.
    """
    if not title:
        return ""
    text = _strip_accents(title).lower().strip()

    # Strip a trailing "feat. ..." clause.
    text = _FEAT_RE.sub("", text).strip()

    # Repeatedly strip trailing (...) / [...] groups that look like versions.
    while True:
        m = _GROUP_RE.search(text)
        if not m:
            break
        inner = m.group(1).strip()
        if any(kw in inner for kw in _VERSION_KEYWORDS):
            stripped = text[: m.start()].strip()
            if not stripped:
                break  # don't collapse e.g. "[untitled]" to empty
            text = stripped
        else:
            break

    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text or _strip_accents(title).lower().strip()
