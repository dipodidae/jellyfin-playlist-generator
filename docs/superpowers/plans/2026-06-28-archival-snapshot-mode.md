# Archival Snapshot Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "snapshot" playlist mode that builds a breadth-across-artists representative cross-section of a niche descriptor (bangers + deep cuts, ~120 tracks, constraint-shuffled), bypassing the trajectory/arc engine.

**Architecture:** A parallel composer (`app/snapshot/`) reuses intent parsing and the flat candidate-scoring helpers from `app/trajectory/candidates.py`, but replaces beam-search sequencing with pure artist-bucketed selection + a constraint shuffle. The API gains a `mode` field that routes `"snapshot"` to the new composer; `"arc"` (default) preserves all existing behavior.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL + pgvector (no ORM), pytest; Nuxt 4 / Vue 3 frontend.

## Global Constraints

- Backend production runs as a **single uvicorn process**; DB-backed settings overlay the `settings` singleton at startup — no per-process cache logic needed.
- Tests live in `service/app/tests/` (mirroring existing files like `test_niche_genre.py`). Run with `. service/.venv/bin/activate && pytest -q service/app/tests`.
- Algorithm Change Policy: snapshot is a **new path** and must not alter trajectory scoring. The existing arc behavior and its eval baseline must remain byte-for-byte unchanged (regression guard in Task 7).
- Docker image bakes the source — deploy is `cd /home/tom/nas && docker compose up -d --build playlist-generator`. Production has no host port; eval via `docker exec playlist-generator curl http://127.0.0.1:8000/...`.
- Reuse, do not reimplement: `parse_prompt`, `semantic_search`, `keyword_search`, `_fetch_candidates_by_ids`, `compute_genre_match_score`, `compute_genre_exclusion`, `derive_niche_hints`, `_attach_artist_tags`, `_normalize_album_legitimacy`, `CandidateTrack`, `PlaylistResult`, `log_generation`, `update_track_usage`.
- `CandidateTrack.curation_score` already = `banger_score*0.65 + album_legitimacy_score*0.35`. Use it as the curation signal `C`; do not invent a new one.

---

### Task 1: Config defaults + `snapshot_score` field

**Files:**
- Modify: `service/app/config.py` (Settings class — add snapshot tunables)
- Modify: `service/app/trajectory/candidates.py` (CandidateTrack — add `snapshot_score`)
- Test: `service/app/tests/test_snapshot_config.py`

**Interfaces:**
- Produces: `settings.snapshot_soft_cap: int`, `settings.snapshot_relevance_floor: float`, `settings.snapshot_min_per_artist: int`, `settings.snapshot_max_per_artist: int`, `settings.snapshot_album_cap: int`, `settings.snapshot_banger_percentile: float`, `settings.snapshot_mood_weight: float`, `settings.snapshot_pool_limit: int`. New field `CandidateTrack.snapshot_score: float = 0.0`.

- [ ] **Step 1: Write the failing test**

```python
# service/app/tests/test_snapshot_config.py
from app.config import settings
from app.trajectory.candidates import CandidateTrack


def test_snapshot_settings_present_with_sane_defaults():
    assert settings.snapshot_soft_cap == 120
    assert 0.0 <= settings.snapshot_relevance_floor <= 1.0
    assert settings.snapshot_min_per_artist == 2
    assert settings.snapshot_max_per_artist == 4
    assert settings.snapshot_album_cap == 2
    assert 0.0 < settings.snapshot_banger_percentile < 1.0
    assert settings.snapshot_pool_limit >= settings.snapshot_soft_cap * 4


def test_candidate_track_has_snapshot_score_default():
    t = CandidateTrack(
        id="1", title="x", artist_name="a", artist_id="a1",
        album_name="al", album_id="al1", year=1985, duration_ms=200000,
    )
    assert t.snapshot_score == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'snapshot_soft_cap'`

- [ ] **Step 3: Add the settings fields**

In `service/app/config.py`, inside the `Settings` class (with the other tunables), add:

```python
    # --- Snapshot mode (archival breadth-across-artists cross-section) ---
    snapshot_soft_cap: int = 120          # target chonky size; thinner niche → fewer
    snapshot_relevance_floor: float = 0.35  # strict floor: drop tracks below this niche fit
    snapshot_min_per_artist: int = 2       # minimum picks per qualifying artist
    snapshot_max_per_artist: int = 4       # maximum picks per qualifying artist
    snapshot_album_cap: int = 2            # max tracks from one album within an artist
    snapshot_banger_percentile: float = 0.6  # top frac of an artist's popularity = "banger"
    snapshot_mood_weight: float = 0.3      # weight of mood(darkness) proximity in relevance
    snapshot_pool_limit: int = 1500        # candidate pool size before selection
```

- [ ] **Step 4: Add the CandidateTrack field**

In `service/app/trajectory/candidates.py`, in the "Scoring components" block of `CandidateTrack` (next to `genre_match_score`), add:

```python
    snapshot_score: float = 0.0   # snapshot mode: 0.5*relevance + 0.5*curation
```

- [ ] **Step 5: Run test to verify it passes**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add service/app/config.py service/app/trajectory/candidates.py service/app/tests/test_snapshot_config.py
git commit -m "feat(snapshot): config tunables + CandidateTrack.snapshot_score field"
```

---

### Task 2: Relevance scoring + per-artist selection (pure)

**Files:**
- Create: `service/app/snapshot/__init__.py` (empty)
- Create: `service/app/snapshot/selection.py`
- Test: `service/app/tests/test_snapshot_selection.py`

**Interfaces:**
- Consumes: `CandidateTrack` (with `genre_match_score`, `darkness`, `banger_score`, `curation_score`, `album_id`, `artist_id` populated), `settings.snapshot_*`.
- Produces:
  - `relevance(track: CandidateTrack, base_darkness: float, mood_weight: float) -> float`
  - `compute_snapshot_scores(tracks: list[CandidateTrack], base_darkness: float, mood_weight: float, floor: float) -> list[CandidateTrack]` — sets `.snapshot_score`, returns only tracks at/above `floor`.
  - `is_banger(track: CandidateTrack, artist_tracks: list[CandidateTrack], percentile: float) -> bool`
  - `select_artist_tracks(artist_tracks: list[CandidateTrack], min_n: int, max_n: int, album_cap: int, banger_percentile: float) -> list[CandidateTrack]`

- [ ] **Step 1: Write the failing tests**

```python
# service/app/tests/test_snapshot_selection.py
from app.trajectory.candidates import CandidateTrack
from app.snapshot.selection import (
    relevance, compute_snapshot_scores, is_banger, select_artist_tracks,
)


def _t(tid, artist, album, gm=0.9, dark=0.8, banger=0.5, leg=0.5):
    t = CandidateTrack(
        id=tid, title=f"t{tid}", artist_name=artist, artist_id=artist,
        album_name=album, album_id=album, year=1985, duration_ms=200000,
        darkness=dark,
    )
    t.genre_match_score = gm
    t.banger_score = banger
    t.album_legitimacy_score = leg
    return t


def test_relevance_blends_genre_and_mood():
    # genre fit 1.0, perfect dark match (target 0.8, track 0.8) → high
    t = _t("1", "a", "x", gm=1.0, dark=0.8)
    r = relevance(t, base_darkness=0.8, mood_weight=0.3)
    assert r > 0.9
    # same genre fit, mood far off → lower
    t2 = _t("2", "a", "x", gm=1.0, dark=0.1)
    assert relevance(t2, base_darkness=0.8, mood_weight=0.3) < r


def test_compute_snapshot_scores_applies_floor_and_sets_score():
    keep = _t("1", "a", "x", gm=0.9)
    drop = _t("2", "a", "x", gm=0.0, dark=0.0, banger=0.0, leg=0.0)
    out = compute_snapshot_scores([keep, drop], base_darkness=0.8,
                                  mood_weight=0.3, floor=0.35)
    assert [t.id for t in out] == ["1"]
    assert out[0].snapshot_score > 0.0


def test_is_banger_relative_to_artist_distribution():
    hi = _t("1", "a", "x", banger=0.9)
    lo = _t("2", "a", "y", banger=0.1)
    arts = [hi, lo]
    assert is_banger(hi, arts, percentile=0.6) is True
    assert is_banger(lo, arts, percentile=0.6) is False


def test_select_artist_tracks_caps_count_and_album_and_includes_banger():
    # 5 tracks, 4 from album "x" (one a banger), 1 from album "y"
    tracks = [
        _t("1", "a", "x", banger=0.95, gm=0.9, leg=0.9),  # the banger
        _t("2", "a", "x", banger=0.1, gm=0.8, leg=0.8),
        _t("3", "a", "x", banger=0.1, gm=0.8, leg=0.7),
        _t("4", "a", "x", banger=0.1, gm=0.8, leg=0.6),
        _t("5", "a", "y", banger=0.1, gm=0.85, leg=0.85),
    ]
    compute_snapshot_scores(tracks, base_darkness=0.8, mood_weight=0.3, floor=0.0)
    picked = select_artist_tracks(tracks, min_n=2, max_n=4, album_cap=2,
                                  banger_percentile=0.6)
    assert 2 <= len(picked) <= 4
    assert "1" in {t.id for t in picked}                       # banger always in
    assert sum(1 for t in picked if t.album_id == "x") <= 2    # album cap honored
    assert "5" in {t.id for t in picked}                       # other album surfaces
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_selection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.snapshot'`

- [ ] **Step 3: Create the package and selection module**

Create empty `service/app/snapshot/__init__.py`.

Create `service/app/snapshot/selection.py`:

```python
"""Pure selection primitives for snapshot mode.

No I/O. Operates on already-scored CandidateTrack lists so each function is
unit-testable in isolation. Snapshot mode wants BREADTH across artists, with a
banger + strong deep cuts per artist, not a trajectory.
"""

from __future__ import annotations

from app.trajectory.candidates import CandidateTrack


def relevance(track: CandidateTrack, base_darkness: float, mood_weight: float) -> float:
    """Niche fit in [0,1]: genre match, nudged by mood (darkness) proximity.

    mood_weight blends the two; with mood_weight=0.3 a perfect genre match with a
    far-off mood still scores ~0.7, but a closer mood lifts it toward 1.0.
    """
    gm = max(0.0, min(1.0, track.genre_match_score))
    mood_prox = 1.0 - abs(track.darkness - base_darkness)  # 1.0 = exact match
    mw = max(0.0, min(1.0, mood_weight))
    return (1.0 - mw) * gm + mw * (gm * mood_prox)


def compute_snapshot_scores(
    tracks: list[CandidateTrack],
    base_darkness: float,
    mood_weight: float,
    floor: float,
) -> list[CandidateTrack]:
    """Set .snapshot_score = 0.5*relevance + 0.5*curation; drop below floor.

    The floor is applied to RELEVANCE (niche fit), not the blended score, so a
    high-curation track that is off-niche is still excluded (strict floor).
    """
    kept: list[CandidateTrack] = []
    for t in tracks:
        r = relevance(t, base_darkness, mood_weight)
        if r < floor:
            continue
        t.snapshot_score = 0.5 * r + 0.5 * max(0.0, min(1.0, t.curation_score))
        kept.append(t)
    return kept


def is_banger(
    track: CandidateTrack,
    artist_tracks: list[CandidateTrack],
    percentile: float,
) -> bool:
    """True if track.banger_score sits in the top (1-percentile) of its artist.

    A lone track (single-element artist) with any positive banger_score counts.
    """
    scores = sorted((t.banger_score for t in artist_tracks))
    if not scores:
        return False
    if len(scores) == 1:
        return track.banger_score > 0.0
    # threshold = value at the `percentile` rank
    idx = min(len(scores) - 1, int(percentile * (len(scores) - 1)))
    threshold = scores[idx]
    return track.banger_score >= threshold and track.banger_score > 0.0


def select_artist_tracks(
    artist_tracks: list[CandidateTrack],
    min_n: int,
    max_n: int,
    album_cap: int,
    banger_percentile: float,
) -> list[CandidateTrack]:
    """Pick min_n..max_n tracks for one artist: banger + best deep cuts.

    Ranks by snapshot_score, guarantees the artist's top banger is included, and
    caps how many come from any single album. Returns fewer than min_n only when
    the artist simply has fewer qualifying tracks.
    """
    ranked = sorted(artist_tracks, key=lambda t: t.snapshot_score, reverse=True)
    picked: list[CandidateTrack] = []
    per_album: dict[str | None, int] = {}

    def _try_add(track: CandidateTrack) -> bool:
        if track in picked:
            return False
        if per_album.get(track.album_id, 0) >= album_cap:
            return False
        picked.append(track)
        per_album[track.album_id] = per_album.get(track.album_id, 0) + 1
        return True

    # 1. Guarantee the top banger (by banger_score) if one qualifies.
    bangers = sorted(
        (t for t in ranked if is_banger(t, artist_tracks, banger_percentile)),
        key=lambda t: t.banger_score, reverse=True,
    )
    if bangers:
        _try_add(bangers[0])

    # 2. Fill remaining slots with the highest snapshot_score tracks (deep cuts).
    for t in ranked:
        if len(picked) >= max_n:
            break
        _try_add(t)

    return picked[:max_n]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_selection.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add service/app/snapshot/__init__.py service/app/snapshot/selection.py service/app/tests/test_snapshot_selection.py
git commit -m "feat(snapshot): pure relevance scoring + per-artist banger/deep-cut selection"
```

---

### Task 3: Soft cap + constraint shuffle (pure)

**Files:**
- Modify: `service/app/snapshot/selection.py`
- Test: `service/app/tests/test_snapshot_ordering.py`

**Interfaces:**
- Consumes: per-artist selections (`dict[str, list[CandidateTrack]]`), `settings.snapshot_soft_cap`.
- Produces:
  - `apply_soft_cap(by_artist: dict[str, list[CandidateTrack]], cap: int) -> list[CandidateTrack]`
  - `shuffle_no_adjacent_artist(tracks: list[CandidateTrack], seed: int) -> list[CandidateTrack]`

- [ ] **Step 1: Write the failing tests**

```python
# service/app/tests/test_snapshot_ordering.py
from app.trajectory.candidates import CandidateTrack
from app.snapshot.selection import apply_soft_cap, shuffle_no_adjacent_artist


def _t(tid, artist, score):
    t = CandidateTrack(
        id=tid, title=f"t{tid}", artist_name=artist, artist_id=artist,
        album_name="al", album_id=f"al{tid}", year=1985, duration_ms=200000,
    )
    t.snapshot_score = score
    return t


def test_apply_soft_cap_keeps_strongest_artists_first():
    by_artist = {
        "a": [_t("1", "a", 0.9), _t("2", "a", 0.85)],   # best 0.9
        "b": [_t("3", "b", 0.5), _t("4", "b", 0.45)],   # best 0.5
        "c": [_t("5", "c", 0.7), _t("6", "c", 0.65)],   # best 0.7
    }
    out = apply_soft_cap(by_artist, cap=4)
    ids = {t.id for t in out}
    assert len(out) == 4
    assert {"1", "2", "5", "6"}.issubset(ids)   # a (0.9) + c (0.7) chosen over b
    assert "3" not in ids and "4" not in ids


def test_apply_soft_cap_allows_partial_last_artist():
    by_artist = {
        "a": [_t("1", "a", 0.9), _t("2", "a", 0.85)],
        "c": [_t("5", "c", 0.7), _t("6", "c", 0.65)],
    }
    out = apply_soft_cap(by_artist, cap=3)
    assert len(out) == 3  # a fully (2) + one from c


def test_apply_soft_cap_returns_all_when_under_cap():
    by_artist = {"a": [_t("1", "a", 0.9)], "b": [_t("2", "b", 0.5)]}
    out = apply_soft_cap(by_artist, cap=120)
    assert len(out) == 2


def test_shuffle_never_places_same_artist_adjacent():
    tracks = (
        [_t(str(i), "a", 0.5) for i in range(5)]
        + [_t(str(i), "b", 0.5) for i in range(5, 8)]
        + [_t(str(i), "c", 0.5) for i in range(8, 10)]
    )
    out = shuffle_no_adjacent_artist(tracks, seed=42)
    assert len(out) == len(tracks)
    assert {t.id for t in out} == {t.id for t in tracks}
    for prev, cur in zip(out, out[1:]):
        assert prev.artist_id != cur.artist_id


def test_shuffle_is_deterministic_for_a_seed():
    tracks = [_t(str(i), chr(97 + i % 3), 0.5) for i in range(9)]
    assert [t.id for t in shuffle_no_adjacent_artist(tracks, seed=7)] == \
           [t.id for t in shuffle_no_adjacent_artist(tracks, seed=7)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_ordering.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_soft_cap'`

- [ ] **Step 3: Add the two functions to `selection.py`**

Append to `service/app/snapshot/selection.py`:

```python
import random


def apply_soft_cap(
    by_artist: dict[str, list[CandidateTrack]],
    cap: int,
) -> list[CandidateTrack]:
    """Flatten per-artist picks to <= cap, strongest artists first.

    Artists are ranked by their best track's snapshot_score; we take whole
    artist blocks until the cap, allowing a partial final artist. Returns all
    picks when the total is under the cap (the list IS the snapshot).
    """
    ranked_artists = sorted(
        by_artist.items(),
        key=lambda kv: max((t.snapshot_score for t in kv[1]), default=0.0),
        reverse=True,
    )
    out: list[CandidateTrack] = []
    for _artist, picks in ranked_artists:
        if len(out) >= cap:
            break
        ordered = sorted(picks, key=lambda t: t.snapshot_score, reverse=True)
        for t in ordered:
            if len(out) >= cap:
                break
            out.append(t)
    return out


def shuffle_no_adjacent_artist(
    tracks: list[CandidateTrack],
    seed: int,
) -> list[CandidateTrack]:
    """Random order with no two same-artist tracks adjacent (seeded/deterministic).

    Greedy: repeatedly place the most-remaining artist that isn't the previous
    artist. This always succeeds when no artist holds a strict majority; snapshot
    selections (<= max_per_artist per artist over many artists) satisfy that.
    """
    rng = random.Random(seed)
    buckets: dict[str | None, list[CandidateTrack]] = {}
    for t in tracks:
        buckets.setdefault(t.artist_id, []).append(t)
    for b in buckets.values():
        rng.shuffle(b)

    out: list[CandidateTrack] = []
    prev_artist: str | None = object()  # sentinel != any artist_id
    while any(buckets.values()):
        # candidate artists with tracks left, excluding the previous one
        avail = [a for a, b in buckets.items() if b and a != prev_artist]
        if not avail:
            # only the previous artist remains — unavoidable; place it
            avail = [a for a, b in buckets.items() if b]
        # pick the artist with the most remaining (ties broken randomly)
        rng.shuffle(avail)
        artist = max(avail, key=lambda a: len(buckets[a]))
        out.append(buckets[artist].pop())
        prev_artist = artist
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_ordering.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add service/app/snapshot/selection.py service/app/tests/test_snapshot_ordering.py
git commit -m "feat(snapshot): soft-cap (strongest-artists-first) + constraint shuffle"
```

---

### Task 4: `compose_snapshot()` orchestration

**Files:**
- Create: `service/app/snapshot/composer.py`
- Test: `service/app/tests/test_snapshot_composer.py`

**Interfaces:**
- Consumes: `parse_prompt`, `semantic_search`, `keyword_search`, `_fetch_candidates_by_ids`, `_attach_artist_tags`, `_normalize_album_legitimacy`, `compute_genre_match_score`, `compute_genre_exclusion`, `derive_niche_hints` (all from `app.trajectory.candidates` / `app.trajectory.intent`); selection functions from Task 2/3; `log_generation`, `update_track_usage` from `app.observability`.
- Produces: `compose_snapshot(prompt: str, soft_cap: int | None = None) -> PlaylistResult`.

- [ ] **Step 1: Write the failing test**

```python
# service/app/tests/test_snapshot_composer.py
import app.snapshot.composer as comp
from app.trajectory.candidates import CandidateTrack
from app.trajectory.intent import PlaylistIntent


def _mk(tid, artist, album, gm, dark, banger, leg):
    t = CandidateTrack(
        id=tid, title=f"t{tid}", artist_name=artist, artist_id=artist,
        album_name=album, album_id=album, year=1985, duration_ms=200000,
        darkness=dark,
    )
    t.genres = ["thrash metal"]
    t.banger_score = banger
    t.album_legitimacy_score = leg
    return t


def test_compose_snapshot_breadth_and_no_arc(monkeypatch):
    # 6 artists, 3 tracks each, all niche-fit
    pool = []
    for ai in range(6):
        for ti in range(3):
            pool.append(_mk(f"{ai}-{ti}", f"artist{ai}", f"alb{ai}-{ti}",
                            gm=0.9, dark=0.8, banger=0.9 if ti == 0 else 0.1, leg=0.7))

    intent = PlaylistIntent(raw_prompt="evil 80s thrash", prompt_embedding=[0.0] * 8)
    intent.genre_hints = ["thrash metal"]
    intent.genre_hints_raw = ["thrash metal"]
    intent.base_darkness = 0.8
    intent.year_range = (1980, 1989)

    monkeypatch.setattr(comp, "parse_prompt", lambda *a, **k: intent)
    monkeypatch.setattr(comp, "semantic_search", lambda *a, **k: list(pool))
    monkeypatch.setattr(comp, "keyword_search", lambda *a, **k: [])
    monkeypatch.setattr(comp, "_attach_artist_tags", lambda c: None)
    monkeypatch.setattr(comp, "_normalize_album_legitimacy", lambda c: None)
    # genre match: niche fit comes straight from the synthetic genres
    monkeypatch.setattr(comp, "compute_genre_match_score", lambda t, *a, **k: 0.9)
    monkeypatch.setattr(comp, "compute_genre_exclusion", lambda t, h: False)
    monkeypatch.setattr(comp, "log_generation", lambda **k: None)
    monkeypatch.setattr(comp, "update_track_usage", lambda ids: None)

    result = comp.compose_snapshot("evil 80s thrash", soft_cap=120)

    assert result.tracks, "expected a non-empty snapshot"
    # breadth: many distinct artists (not one band dominating)
    artists = {t.artist_id for t in result.tracks}
    assert len(artists) >= 5
    # no same-artist adjacency
    for a, b in zip(result.tracks, result.tracks[1:]):
        assert a.artist_id != b.artist_id
    # snapshot-specific metrics, and NO trajectory/arc metrics
    assert result.metrics["mode"] == "snapshot"
    assert result.metrics["distinct_artists"] == len(artists)
    assert "trajectory" not in result.metrics


def test_compose_snapshot_strict_floor_drops_offniche(monkeypatch):
    good = _mk("1", "a", "x", gm=0.9, dark=0.8, banger=0.9, leg=0.8)
    bad = _mk("2", "b", "y", gm=0.0, dark=0.0, banger=0.0, leg=0.0)
    intent = PlaylistIntent(raw_prompt="evil 80s thrash", prompt_embedding=[0.0] * 8)
    intent.genre_hints = ["thrash metal"]
    intent.base_darkness = 0.8

    monkeypatch.setattr(comp, "parse_prompt", lambda *a, **k: intent)
    monkeypatch.setattr(comp, "semantic_search", lambda *a, **k: [good, bad])
    monkeypatch.setattr(comp, "keyword_search", lambda *a, **k: [])
    monkeypatch.setattr(comp, "_attach_artist_tags", lambda c: None)
    monkeypatch.setattr(comp, "_normalize_album_legitimacy", lambda c: None)
    monkeypatch.setattr(comp, "compute_genre_exclusion", lambda t, h: False)
    monkeypatch.setattr(comp, "log_generation", lambda **k: None)
    monkeypatch.setattr(comp, "update_track_usage", lambda ids: None)
    # real relevance via genre_match: good=0.9, bad=0.0
    monkeypatch.setattr(comp, "compute_genre_match_score",
                        lambda t, *a, **k: 0.9 if t.id == "1" else 0.0)

    result = comp.compose_snapshot("evil 80s thrash", soft_cap=120)
    assert {t.id for t in result.tracks} == {"1"}
    assert result.metrics["qualifying_tracks"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_composer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.snapshot.composer'`

- [ ] **Step 3: Write `compose_snapshot`**

Create `service/app/snapshot/composer.py`:

```python
"""Snapshot composer: breadth-across-artists representative cross-section.

Reuses intent parsing and the flat candidate-scoring helpers, but deliberately
bypasses the trajectory engine (no position pools, no beam search). Returns the
same PlaylistResult shape so the route's title/save/export path is unchanged.
"""

from __future__ import annotations

import logging
import time

from app.config import settings
from app.observability import log_generation, update_track_usage
from app.snapshot.selection import (
    apply_soft_cap,
    compute_snapshot_scores,
    select_artist_tracks,
    shuffle_no_adjacent_artist,
)
from app.trajectory.candidates import (
    CandidateTrack,
    _attach_artist_tags,
    _fetch_candidates_by_ids,
    _normalize_album_legitimacy,
    compute_genre_exclusion,
    compute_genre_match_score,
    derive_niche_hints,
    keyword_search,
    semantic_search,
)
from app.trajectory.composer_v4 import PlaylistResult
from app.trajectory.intent import (
    get_primary_genre_hints,
    parse_prompt,
)

logger = logging.getLogger(__name__)


def _gather_pool(intent, limit: int) -> list[CandidateTrack]:
    """Build one flat, uniformly-enriched candidate pool for the niche."""
    pool: dict[str, CandidateTrack] = {}
    for c in semantic_search(intent.prompt_embedding, limit=limit,
                             year_range=intent.year_range):
        pool[c.id] = c
    # Supplement with keyword hits; hydrate keyword-only ids for uniform fields.
    kw = keyword_search(intent.raw_prompt, limit=limit, genre_hints=intent.genre_hints)
    missing = [c.id for c in kw if c.id not in pool]
    if missing:
        for c in _fetch_candidates_by_ids(missing):
            pool[c.id] = c
    return list(pool.values())


def compose_snapshot(prompt: str, soft_cap: int | None = None) -> PlaylistResult:
    """Compose an archival snapshot playlist (breadth across artists)."""
    start = time.time()
    cap = max(20, soft_cap or settings.snapshot_soft_cap)

    intent = parse_prompt(prompt)

    pool = _gather_pool(intent, settings.snapshot_pool_limit)
    if not pool:
        return PlaylistResult(tracks=[], intent=intent,
                              metrics={"mode": "snapshot", "error": "no_candidates"},
                              generation_time_ms=int((time.time() - start) * 1000))

    # Uniform enrichment (mirrors generate_position_pools' post-assembly steps).
    _normalize_album_legitimacy(pool)
    _attach_artist_tags(pool)

    # Niche-aware genre match → relevance input.
    niche_hints, demote_families = derive_niche_hints(intent.genre_hints_raw)
    hint_set = {h.lower() for h in intent.genre_hints}
    primary = get_primary_genre_hints(intent.genre_hints)
    hard_avoids = intent.hard_avoid_keywords

    survivors: list[CandidateTrack] = []
    for t in pool:
        if hard_avoids and compute_genre_exclusion(t, hard_avoids):
            continue
        t.genre_match_score = compute_genre_match_score(
            t, hint_set, primary, niche_hints, demote_families,
        )
        survivors.append(t)

    qualifying = compute_snapshot_scores(
        survivors,
        base_darkness=intent.base_darkness,
        mood_weight=settings.snapshot_mood_weight,
        floor=settings.snapshot_relevance_floor,
    )

    # Bucket by artist; pick banger + deep cuts per artist; drop artists whose
    # best track fell below the floor (they are simply absent from `qualifying`).
    by_artist: dict[str, list[CandidateTrack]] = {}
    for t in qualifying:
        if t.artist_id:
            by_artist.setdefault(t.artist_id, []).append(t)

    selected_by_artist: dict[str, list[CandidateTrack]] = {}
    for artist_id, tracks in by_artist.items():
        picks = select_artist_tracks(
            tracks,
            min_n=settings.snapshot_min_per_artist,
            max_n=settings.snapshot_max_per_artist,
            album_cap=settings.snapshot_album_cap,
            banger_percentile=settings.snapshot_banger_percentile,
        )
        if picks:
            selected_by_artist[artist_id] = picks

    capped = apply_soft_cap(selected_by_artist, cap)

    # Deterministic-but-fresh order: seed off the prompt + count so re-running the
    # same prompt is stable, but different prompts/sizes vary (no Date/random ban).
    seed = (abs(hash(intent.raw_prompt)) % 1_000_000) + len(capped)
    ordered = shuffle_no_adjacent_artist(capped, seed=seed)

    banger_count = sum(
        1 for t in ordered if t.banger_score >= 0.5
    )
    metrics = {
        "mode": "snapshot",
        "qualifying_tracks": len(qualifying),
        "distinct_artists": len({t.artist_id for t in ordered}),
        "banger_count": banger_count,
        "deep_cut_count": len(ordered) - banger_count,
        "soft_cap": cap,
        "niche_floor": settings.snapshot_relevance_floor,
        "pool_size": len(pool),
    }
    gen_ms = int((time.time() - start) * 1000)
    metrics["generation_time_ms"] = gen_ms

    log_generation(
        prompt=prompt,
        arc_type="snapshot",
        playlist_length=len(ordered),
        generation_time_ms=gen_ms,
        metrics=metrics,
    )
    update_track_usage([t.id for t in ordered])

    logger.info(
        f"Snapshot compose: '{prompt[:40]}' → {len(ordered)} tracks, "
        f"{metrics['distinct_artists']} artists in {gen_ms}ms"
    )
    return PlaylistResult(tracks=ordered, intent=intent, metrics=metrics,
                          generation_time_ms=gen_ms)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_composer.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full snapshot test set**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_*.py -q`
Expected: PASS (all snapshot tests)

- [ ] **Step 6: Commit**

```bash
git add service/app/snapshot/composer.py service/app/tests/test_snapshot_composer.py
git commit -m "feat(snapshot): compose_snapshot orchestration (pool→score→select→cap→shuffle)"
```

---

### Task 5: API wiring (`mode` field + route branch)

**Files:**
- Modify: `service/app/api/routes_v3.py` (`GeneratePlaylistRequest` + `generate_playlist` + `generate_playlist_stream`)
- Test: `service/app/tests/test_snapshot_route.py`

**Interfaces:**
- Consumes: `compose_snapshot` (Task 4), `compose_playlist_v4` (existing).
- Produces: `GeneratePlaylistRequest.mode: str = "arc"`; route dispatches to the right composer.

- [ ] **Step 1: Write the failing test**

```python
# service/app/tests/test_snapshot_route.py
from fastapi.testclient import TestClient
import app.api.routes_v3 as r
from app.main import app
from app.trajectory.composer_v4 import PlaylistResult
from app.trajectory.intent import PlaylistIntent


def _fake_result(mode_tag):
    intent = PlaylistIntent(raw_prompt="p", prompt_embedding=[0.0] * 8)
    intent.genre_hints = ["thrash metal"]
    from app.trajectory.candidates import CandidateTrack
    t = CandidateTrack(id="1", title="x", artist_name="a", artist_id="a1",
                       album_name="al", album_id="al1", year=1985, duration_ms=200000)
    return PlaylistResult(tracks=[t], intent=intent,
                          metrics={"mode": mode_tag}, generation_time_ms=1)


def test_mode_defaults_to_arc_and_calls_v4(monkeypatch):
    called = {}
    monkeypatch.setattr(r, "compose_playlist_v4",
                        lambda prompt, size: called.setdefault("v4", True) or _fake_result("arc"))
    monkeypatch.setattr(r, "compose_snapshot",
                        lambda prompt, soft_cap=None: called.setdefault("snap", True) or _fake_result("snapshot"))
    monkeypatch.setattr(r, "generate_playlist_title", lambda *a, **k: "T")
    monkeypatch.setattr(r, "_save_playlist", lambda *a, **k: "pid")

    client = TestClient(app)
    resp = client.post("/generate-playlist", json={"prompt": "evil 80s thrash", "save": False})
    assert resp.status_code == 200
    assert called.get("v4") and not called.get("snap")


def test_mode_snapshot_calls_compose_snapshot(monkeypatch):
    called = {}
    monkeypatch.setattr(r, "compose_playlist_v4",
                        lambda prompt, size: called.setdefault("v4", True) or _fake_result("arc"))
    monkeypatch.setattr(r, "compose_snapshot",
                        lambda prompt, soft_cap=None: called.setdefault("snap", True) or _fake_result("snapshot"))
    monkeypatch.setattr(r, "generate_playlist_title", lambda *a, **k: "T")
    monkeypatch.setattr(r, "_save_playlist", lambda *a, **k: "pid")

    client = TestClient(app)
    resp = client.post("/generate-playlist",
                       json={"prompt": "evil 80s thrash", "mode": "snapshot",
                             "size": 120, "save": False})
    assert resp.status_code == 200
    assert called.get("snap") and not called.get("v4")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_route.py -v`
Expected: FAIL — snapshot branch not present, both assertions about `compose_snapshot` fail (or import of `compose_snapshot` on the route module fails).

- [ ] **Step 3: Add the `mode` field**

In `service/app/api/routes_v3.py`, extend the request model (around line 107):

```python
class GeneratePlaylistRequest(BaseModel):
    prompt: str
    size: int = 25
    save: bool = True
    mode: str = "arc"  # "arc" (trajectory) | "snapshot" (breadth cross-section)
```

- [ ] **Step 4: Import and branch in both routes**

At the top of `routes_v3.py`, alongside the `compose_playlist_v4` import, add:

```python
from app.snapshot.composer import compose_snapshot
```

In `generate_playlist` (replace the `result = await asyncio.to_thread(...)` call at ~1876):

```python
        if request.mode == "snapshot":
            result = await asyncio.to_thread(compose_snapshot, request.prompt, request.size)
        else:
            result = await asyncio.to_thread(compose_playlist_v4, request.prompt, request.size)
```

Apply the identical branch in `generate_playlist_stream`'s worker (where it calls the composer inside `generate_events`). If the stream path uses `compose_playlist_v4_streaming` with a progress callback, snapshot has no streaming variant — call `compose_snapshot` directly and emit a single "complete" progress event before the result. Keep the arc path untouched.

- [ ] **Step 5: Run test to verify it passes**

Run: `. service/.venv/bin/activate && pytest service/app/tests/test_snapshot_route.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add service/app/api/routes_v3.py service/app/tests/test_snapshot_route.py
git commit -m "feat(snapshot): mode field on generate-playlist + route dispatch"
```

---

### Task 6: Frontend Arc · Snapshot toggle

**Files:**
- Modify: `frontend/app/pages/index.vue`
- Modify: `frontend/server/api/` proxy route that posts to `/generate-playlist` (forward `mode` + snapshot size)

**Interfaces:**
- Consumes: backend `mode` field (Task 5).
- Produces: UI state `mode` ('arc' | 'snapshot'); request body includes `mode` and, in snapshot mode, `size = 120`.

- [ ] **Step 1: Add the toggle + state to `index.vue`**

In `<script setup lang="ts">`, add reactive state and default sizing:

```ts
const mode = ref<'arc' | 'snapshot'>('arc')
const SNAPSHOT_SIZE = 120
```

In the request payload builder (where the body for the generate call is assembled), include:

```ts
body: {
  prompt: prompt.value,
  mode: mode.value,
  size: mode.value === 'snapshot' ? SNAPSHOT_SIZE : size.value,
  save: true,
}
```

In the template, above the prompt input, add a Nuxt UI segmented control:

```vue
<UButtonGroup class="mb-3">
  <UButton :variant="mode === 'arc' ? 'solid' : 'outline'" @click="mode = 'arc'">Arc</UButton>
  <UButton :variant="mode === 'snapshot' ? 'solid' : 'outline'" @click="mode = 'snapshot'">Snapshot</UButton>
</UButtonGroup>
<p v-if="mode === 'snapshot'" class="text-xs text-gray-400 mb-2">
  Archival cross-section: bangers + deep cuts across every artist you own in this niche. No arc.
</p>
```

When `mode === 'snapshot'`, hide arc-only controls (size slider / arc-shape affordances) with `v-if="mode === 'arc'"`.

- [ ] **Step 2: Forward `mode` in the proxy route**

In the Nuxt server proxy that forwards to the backend `/generate-playlist`, ensure the request body passes through `mode` and `size` (read the body and forward it unchanged, or explicitly include `mode`). Confirm with a grep that the proxy forwards the full body rather than cherry-picking fields.

- [ ] **Step 3: Build the frontend to verify it compiles**

Run: `cd frontend && pnpm build`
Expected: build succeeds, no type errors on `mode`.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/pages/index.vue frontend/server/api/
git commit -m "feat(snapshot): Arc/Snapshot UI toggle + proxy forwards mode"
```

---

### Task 7: Docs + regression guard

**Files:**
- Modify: `AGENTS.md` (API Endpoints + a Snapshot mode subsection), `README.md` (API Reference), `CLAUDE.md` (Important Files: add `app/snapshot/`)
- No new test file; this task runs existing suites as a regression guard.

- [ ] **Step 1: Update the docs**

- `CLAUDE.md` → "Important Files / Backend": add
  `service/app/snapshot/composer.py` (snapshot orchestration) and
  `service/app/snapshot/selection.py` (pure breadth-selection + constraint shuffle).
- `AGENTS.md` → API Endpoints: note `/generate-playlist` accepts `mode: "arc"|"snapshot"`; add a short "Snapshot mode" paragraph describing breadth-across-artists, 2–4 per artist, ~120 soft cap, strict relevance floor, constraint shuffle, trajectory engine bypassed.
- `README.md` → API Reference: same `mode` note.

- [ ] **Step 2: Run the full backend test suite (regression)**

Run: `. service/.venv/bin/activate && pytest -q service/app/tests`
Expected: PASS — all new snapshot tests AND all pre-existing tests (arc path untouched).

- [ ] **Step 3: Lint**

Run: `. service/.venv/bin/activate && ruff check service/app/snapshot service/app/api/routes_v3.py`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md README.md CLAUDE.md
git commit -m "docs(snapshot): document mode field + app/snapshot module"
```

---

## Post-implementation: build & smoke-test on main

After all tasks pass, build production and smoke-test the new mode:

```bash
cd /home/tom/nas && docker compose up -d --build playlist-generator
# wait ~60s for model load, then:
docker exec playlist-generator curl -s -X POST http://127.0.0.1:8000/generate-playlist \
  -H "Content-Type: application/json" \
  -d '{"prompt":"evil 80s thrash","mode":"snapshot","size":120,"save":false}' \
  | python3 -m json.tool | head -40
```

Verify: many distinct artists, no same-artist adjacency, `metrics.mode == "snapshot"`,
year filter honored. Confirm an `mode:"arc"` request still behaves exactly as before.

## Self-Review notes

- **Spec coverage:** trigger/API (T5,T6), candidate gathering reused+flattened (T4 `_gather_pool`), banger/deep-cut definition (T2 `is_banger`/`select_artist_tracks` + `curation_score`), per-artist breadth (T2), soft cap (T3), constraint shuffle (T3), metrics+count (T4), strict floor (T2 `compute_snapshot_scores` + T4 drop), module boundaries (T2/T4), testing (T2–T5,T7), regression guard (T7). All spec sections map to a task.
- **Type consistency:** `compute_snapshot_scores`/`select_artist_tracks`/`apply_soft_cap`/`shuffle_no_adjacent_artist` signatures are identical across plan and tests; `compose_snapshot(prompt, soft_cap=None)` matches the route call and route test monkeypatch.
- **Placeholder scan:** no TBDs; every code step shows complete code.
