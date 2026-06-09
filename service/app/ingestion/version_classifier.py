"""Pure studio-vs-live/demo/bonus version classifier (metadata only)."""

import re

# (regex, version_type, studio_score) — first match wins; order = priority.
_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"\blive\b|live at|live in|\(live", re.I), "live", 0.35),
    (re.compile(r"\bdemo\b", re.I), "demo", 0.50),
    (re.compile(r"rehearsal|\bsession(s)?\b", re.I), "session", 0.55),
    (re.compile(r"alternate (take|version|mix)|alt\.? take", re.I), "alternate", 0.60),
    (re.compile(r"acoustic version|\bunplugged\b|acoustic\)", re.I), "acoustic", 0.65),
    (re.compile(r"\bremix\b|club mix|radio edit", re.I), "remix", 0.70),
    (re.compile(r"bonus track|\(bonus", re.I), "bonus", 0.75),
]

_MB_TYPE_MAP = {
    "live": ("live", 0.35),
    "demo": ("demo", 0.50),
    "remix": ("remix", 0.70),
    "compilation": ("bonus", 0.80),
}


def classify_version(
    track_title: str, album_title: str, mb_secondary_types: list[str] | None = None
):
    """Return (version_type, studio_score in [0,1]); 1.0 = clean studio.

    Title cues take priority, then MusicBrainz release-group secondary types.
    """
    hay = f"{track_title or ''}  ||  {album_title or ''}"
    for rx, vtype, score in _PATTERNS:
        if rx.search(hay):
            return vtype, score
    for t in (mb_secondary_types or []):
        key = t.strip().lower()
        if key in _MB_TYPE_MAP:
            return _MB_TYPE_MAP[key]
    return "studio", 1.0
