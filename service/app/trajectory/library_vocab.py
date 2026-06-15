"""Library vocabulary grounding + genre snapping (PARSE_AUDIT P2 / P4).

The LLM intent parser historically emitted free-text genres with no knowledge
of what actually exists in the library, so labels like "cascadian doomgaze"
matched zero tracks silently. This module supplies:

- ``build_vocabulary_prompt_block()`` — the real genre/tag vocabulary of the
  current library, formatted for injection into the system prompt (P2) so the
  model chooses labels that map to real tracks.
- ``snap_genres()`` — a post-parse safety net (P4) that maps an out-of-vocab
  label to the nearest known term by embedding similarity, logging a confidence
  score, and drops labels too far from anything real.

Both reads are cached for the process lifetime (single uvicorn worker — see
CLAUDE.md gotcha #1). The cache is naturally refreshed on restart, which is when
a library sync/rebuild lands new genres anyway. Call ``reset_cache()`` to force
a refresh in tests or after a manual backfill.
"""
from __future__ import annotations

import logging

import numpy as np

from app.database_pg import get_connection

logger = logging.getLogger(__name__)

_MAX_GENRES = 150
_MAX_TAGS = 150

# Module-level caches (process-lifetime; reset_cache() clears them).
_vocab_cache: dict[str, list[str]] | None = None
_vocab_emb_cache: tuple[list[str], np.ndarray] | None = None


def reset_cache() -> None:
    """Clear cached vocabulary + embeddings (tests / post-backfill refresh)."""
    global _vocab_cache, _vocab_emb_cache
    _vocab_cache = None
    _vocab_emb_cache = None


def get_library_vocabulary() -> dict[str, list[str]]:
    """Return {'genres': [...], 'tags': [...]} — the library's real vocabulary.

    Genres are ranked by track count; Last.fm tags by the number of artists
    carrying them (weight >= 50). Cached for the process lifetime.
    """
    global _vocab_cache
    if _vocab_cache is not None:
        return _vocab_cache

    genres: list[str] = []
    tags: list[str] = []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT g.name, COUNT(*) AS n
                    FROM genres g
                    JOIN track_genres tg ON tg.genre_id = g.id
                    GROUP BY g.name
                    ORDER BY n DESC
                    LIMIT %s
                    """,
                    (_MAX_GENRES,),
                )
                genres = [r[0] for r in cur.fetchall() if r[0]]

                cur.execute(
                    """
                    SELECT lt.name, COUNT(DISTINCT alt.artist_id) AS n
                    FROM lastfm_tags lt
                    JOIN artist_lastfm_tags alt ON alt.tag_id = lt.id
                    WHERE alt.weight >= 50
                    GROUP BY lt.name
                    ORDER BY n DESC
                    LIMIT %s
                    """,
                    (_MAX_TAGS,),
                )
                tags = [r[0] for r in cur.fetchall() if r[0]]
    except Exception as e:  # pragma: no cover - DB unavailable / not yet built
        logger.warning(f"get_library_vocabulary failed: {e}")

    _vocab_cache = {"genres": genres, "tags": tags}
    return _vocab_cache


def get_vocabulary_terms() -> list[str]:
    """Flat, deduped, lowercased list of every vocabulary term (genres + tags)."""
    v = get_library_vocabulary()
    seen: set[str] = set()
    out: list[str] = []
    for term in [*v["genres"], *v["tags"]]:
        tl = term.lower().strip()
        if tl and tl not in seen:
            seen.add(tl)
            out.append(tl)
    return out


def is_known_term(label: str) -> bool:
    """True if the label is an exact vocabulary term in the current library."""
    return label.lower().strip() in set(get_vocabulary_terms())


def build_vocabulary_prompt_block(max_genres: int = 120, max_tags: int = 100) -> str:
    """Format the library vocabulary for injection into the parse system prompt.

    Returns "" when no vocabulary is available (fresh DB) so the caller can fall
    back to the ungrounded prompt.
    """
    v = get_library_vocabulary()
    genres = v["genres"][:max_genres]
    genre_lc = {g.lower() for g in genres}
    tags = [t for t in v["tags"] if t.lower() not in genre_lc][:max_tags]
    if not genres and not tags:
        return ""

    lines = [
        "## Library vocabulary",
        "These are the ACTUAL genres/tags present in this user's library. "
        "Choose `genre_hints` ONLY from this list (case-insensitive). Pick the "
        "closest terms if the user's wording differs; do not invent labels that "
        "are absent here.",
    ]
    if genres:
        lines.append("Genres: " + ", ".join(genres))
    if tags:
        lines.append("Tags: " + ", ".join(tags))
    return "\n".join(lines)


def _get_vocab_embeddings() -> tuple[list[str], np.ndarray]:
    """Lazily embed every vocabulary term once; return (terms, L2-normed matrix)."""
    global _vocab_emb_cache
    if _vocab_emb_cache is not None:
        return _vocab_emb_cache

    terms = get_vocabulary_terms()
    if not terms:
        _vocab_emb_cache = ([], np.zeros((0, 0), dtype=np.float32))
        return _vocab_emb_cache

    from app.embeddings.generator import generate_embeddings_batch

    embs = np.asarray(generate_embeddings_batch(terms), dtype=np.float32)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    _vocab_emb_cache = (terms, embs / norms)
    return _vocab_emb_cache


def snap_label(label: str, min_similarity: float) -> tuple[str, float] | None:
    """Snap a single label to the nearest vocabulary term by embedding cosine.

    Returns (term, similarity) or None if nothing clears ``min_similarity``.
    """
    terms, embs = _get_vocab_embeddings()
    if not terms:
        return None

    from app.embeddings.generator import generate_embedding

    q = np.asarray(generate_embedding(label), dtype=np.float32)
    n = float(np.linalg.norm(q))
    if n == 0:
        return None
    sims = embs @ (q / n)
    idx = int(np.argmax(sims))
    sim = float(sims[idx])
    if sim < min_similarity:
        return None
    return terms[idx], sim


def snap_genres(
    genre_hints: list[str],
    is_taxonomy_known,
    min_similarity: float = 0.55,
) -> tuple[list[str], dict[str, float]]:
    """Ground a list of genre hints against the real library vocabulary.

    A hint is kept verbatim (confidence 1.0) when it is already a taxonomy alias
    (``is_taxonomy_known``) or an exact library term. Otherwise it is snapped to
    the nearest vocabulary term above ``min_similarity`` (confidence = cosine),
    or dropped when nothing is close enough.

    Returns (cleaned_hints, confidence_by_hint). Order is preserved and the
    result is deduped.
    """
    if not genre_hints:
        return [], {}

    known_terms = set(get_vocabulary_terms())
    out: list[str] = []
    conf: dict[str, float] = {}
    seen: set[str] = set()

    def _add(term: str, score: float) -> None:
        tl = term.lower().strip()
        if not tl or tl in seen:
            # Keep the highest confidence if a term appears twice.
            if tl in conf:
                conf[tl] = max(conf[tl], score)
            return
        seen.add(tl)
        out.append(tl)
        conf[tl] = score

    for hint in genre_hints:
        hl = hint.lower().strip()
        if not hl:
            continue
        if is_taxonomy_known(hl) or hl in known_terms:
            _add(hl, 1.0)
            continue
        snapped = snap_label(hl, min_similarity)
        if snapped is None:
            logger.info(f"Genre snap: dropped out-of-vocab hint '{hl}' (no match >= {min_similarity})")
            continue
        term, sim = snapped
        logger.info(f"Genre snap: '{hl}' -> '{term}' (sim={sim:.3f})")
        _add(term, sim)

    return out, conf
