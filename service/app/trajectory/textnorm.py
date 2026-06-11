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
    "orchestral", "anniversary", "deluxe", "expanded",
    "re-recording", "rerecording",
)

_GROUP_RE = re.compile(r"\s*[\(\[]([^()\[\]]*)[\)\]]\s*$")
_FEAT_RE = re.compile(r"\s*(?:\(?\s*(?:feat|ft|featuring)\.?\s+[^)]*\)?)\s*$",
                      re.IGNORECASE)
# Trailing " - <segment>" / ": <segment>" (em/en-dash too). Requires a space
# after the separator so hyphenated words ("Spider-Man") are left intact.
_TRAIL_DASH_RE = re.compile(r"\s*[-–—:]\s+([^-–—:]+)$")
# A 4-digit year anywhere in a segment (e.g. "2017 Remaster", "2017").
_YEAR_RE = re.compile(r"\b\d{4}\b")
# Trailing apostrophe-year tag ("Tormentor '88"); needs leading whitespace so
# mid-word apostrophes ("Rock 'n' Roll") are untouched.
_APOS_YEAR_RE = re.compile(r"\s+['’]\d{2}\b.*$")
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

    # Repeatedly strip trailing version markers — parenthetical/bracket groups,
    # " - "/": " dash-delimited segments, and apostrophe-year tags — until the
    # title stabilizes (handles e.g. "X (Live) - 2017 Remaster"). A strip is
    # skipped if it would empty the title (e.g. "[untitled]").
    def _is_version_segment(seg: str) -> bool:
        return any(kw in seg for kw in _VERSION_KEYWORDS) or bool(_YEAR_RE.search(seg))

    while True:
        prev = text

        m = _GROUP_RE.search(text)
        if m and any(kw in m.group(1).strip() for kw in _VERSION_KEYWORDS):
            stripped = text[: m.start()].strip()
            if stripped:
                text = stripped
                continue

        d = _TRAIL_DASH_RE.search(text)
        if d and _is_version_segment(d.group(1).strip().lower()):
            stripped = text[: d.start()].strip()
            if stripped:
                text = stripped
                continue

        a = _APOS_YEAR_RE.search(text)
        if a:
            stripped = text[: a.start()].strip()
            if stripped:
                text = stripped
                continue

        if text == prev:
            break

    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text or _strip_accents(title).lower().strip()
