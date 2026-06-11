# Banger Factor v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-source (Last.fm popularity) banger score with a 3-group composite — popularity 0.45 / sonic 0.35 / replay 0.20 — built entirely from data the stack already holds.

**Architecture:** Extract all scoring math into a new pure module `service/app/enrichment/banger_scoring.py` (no I/O, mirrors `version_classifier.py`), unit-tested in isolation. `banger_detector.py` keeps its DB role: it queries `lastfm_stats` + `track_audio_features` + genre tags, calls the pure functions, and persists to `track_banger_flags`. Output contract (`banger_score` 0–1 in `track_banger_flags`) is unchanged, so `candidates.py` curation scoring is untouched.

**Tech Stack:** Python 3.12, psycopg2, pytest. Spec: `docs/superpowers/specs/2026-06-11-banger-factor-v2-design.md`.

**Branch:** `feat/banger-factor-v2` (already created).

**Setup for all test steps:**
```bash
cd service && source .venv/bin/activate
```

---

### Task 1: Pure scoring primitives (tempo, energy, dark-genre)

**Files:**
- Create: `service/app/enrichment/banger_scoring.py`
- Test: `service/app/tests/test_banger_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# service/app/tests/test_banger_scoring.py
from app.enrichment.banger_scoring import (
    tempo_score, energy_proxy, is_dark_genre,
)


def test_tempo_peak_zone():
    assert tempo_score(90) == 1.0
    assert tempo_score(110) == 1.0
    assert tempo_score(130) == 1.0


def test_tempo_falloff_low():
    assert tempo_score(70) == 0.0
    assert tempo_score(80) == 0.5      # halfway between 70 and 90
    assert tempo_score(None) == 0.0
    assert tempo_score(0) == 0.0


def test_tempo_falloff_high():
    assert tempo_score(180) == 0.0
    assert tempo_score(155) == 0.5     # halfway between 130 and 180
    assert tempo_score(200) == 0.0


def test_energy_proxy_blend():
    # 0.5*ln + 0.3*orn + 0.2*pc
    assert energy_proxy(1.0, 1.0, 1.0) == 1.0
    assert energy_proxy(0.0, 0.0, 0.0) == 0.0
    assert round(energy_proxy(1.0, 0.0, 0.0), 3) == 0.5
    # None inputs treated as 0
    assert round(energy_proxy(1.0, None, None), 3) == 0.5


def test_is_dark_genre():
    assert is_dark_genre(["Doom Metal", "Sludge"]) is True
    assert is_dark_genre(["Industrial"]) is True
    assert is_dark_genre(["Darkwave"]) is True
    assert is_dark_genre(["Synthpop", "Dream Pop"]) is False
    assert is_dark_genre([]) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest app/tests/test_banger_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.enrichment.banger_scoring'`

- [ ] **Step 3: Write minimal implementation**

```python
# service/app/enrichment/banger_scoring.py
"""Pure scoring math for banger-factor v2. No I/O, no DB — unit-testable.

See docs/superpowers/specs/2026-06-11-banger-factor-v2-design.md.
"""
import bisect

# Genres for which valence must NOT penalize the sonic score.
DARK_GENRES = ("metal", "doom", "industrial", "darkwave", "goth", "noise")


def _clamp01(x) -> float:
    if x is None:
        return 0.0
    return max(0.0, min(1.0, float(x)))


def tempo_score(bpm) -> float:
    """1.0 across the 90-130 BPM banger zone; linear falloff to 0 at 70 and 180."""
    if not bpm or bpm <= 0:
        return 0.0
    if 90 <= bpm <= 130:
        return 1.0
    if bpm < 90:
        if bpm <= 70:
            return 0.0
        return (bpm - 70) / 20.0          # 70..90 -> 0..1
    if bpm >= 180:
        return 0.0
    return (180 - bpm) / 50.0             # 130..180 -> 1..0


def energy_proxy(loudness_norm, onset_rate_norm, pulse_clarity) -> float:
    """No literal energy column — derive from loudness/onset/pulse."""
    return _clamp01(
        0.5 * _clamp01(loudness_norm)
        + 0.3 * _clamp01(onset_rate_norm)
        + 0.2 * _clamp01(pulse_clarity)
    )


def is_dark_genre(tags) -> bool:
    """True if any tag substring-matches a DARK_GENRES entry (case-insensitive)."""
    for t in tags or ():
        tl = str(t).lower()
        if any(g in tl for g in DARK_GENRES):
            return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest app/tests/test_banger_scoring.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add service/app/enrichment/banger_scoring.py service/app/tests/test_banger_scoring.py
git commit -m "feat(banger): pure tempo/energy/dark-genre scoring primitives"
```

---

### Task 2: Sonic score with valence genre-correction

**Files:**
- Modify: `service/app/enrichment/banger_scoring.py`
- Test: `service/app/tests/test_banger_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# append to service/app/tests/test_banger_scoring.py
from app.enrichment.banger_scoring import sonic_score


def test_sonic_all_max():
    # energy=dance=loud=tempo(110)=valence=1.0 -> 1.0
    s = sonic_score(energy=1.0, danceability=1.0, loudness_norm=1.0,
                    bpm=110, valence=1.0, dark=False)
    assert round(s, 4) == 1.0


def test_sonic_weights_sum_correctly():
    # only energy=1.0, everything else 0, valence=0 -> 0.30
    s = sonic_score(energy=1.0, danceability=0.0, loudness_norm=0.0,
                    bpm=0, valence=0.0, dark=False)
    assert round(s, 3) == 0.30


def test_sonic_dark_drops_valence_no_penalty():
    # Dark track, low valence: valence term removed, other 4 reweighted to sum 1.
    # energy=1, dance=1, loud=1, tempo(110)=1, valence=0
    light = sonic_score(1.0, 1.0, 1.0, 110, valence=0.0, dark=False)
    dark = sonic_score(1.0, 1.0, 1.0, 110, valence=0.0, dark=True)
    # Light track loses the 0.10 valence contribution (valence=0) -> 0.90
    assert round(light, 3) == 0.90
    # Dark track redistributes -> the four maxed terms give full 1.0
    assert round(dark, 3) == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest app/tests/test_banger_scoring.py -v`
Expected: FAIL — `ImportError: cannot import name 'sonic_score'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to service/app/enrichment/banger_scoring.py

_SONIC_WEIGHTS = {
    "energy": 0.30,
    "dance": 0.30,
    "loud": 0.15,
    "tempo": 0.15,
    "valence": 0.10,
}


def sonic_score(energy, danceability, loudness_norm, bpm, valence, dark) -> float:
    """Weighted sonic composite. For dark genres the valence term is dropped and
    its weight redistributed proportionally across the remaining four terms."""
    terms = {
        "energy": _clamp01(energy),
        "dance": _clamp01(danceability),
        "loud": _clamp01(loudness_norm),
        "tempo": tempo_score(bpm),
        "valence": _clamp01(valence),
    }
    weights = dict(_SONIC_WEIGHTS)
    if dark:
        del terms["valence"]
        del weights["valence"]
        total = sum(weights.values())
        weights = {k: w / total for k, w in weights.items()}
    return _clamp01(sum(terms[k] * weights[k] for k in terms))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest app/tests/test_banger_scoring.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add service/app/enrichment/banger_scoring.py service/app/tests/test_banger_scoring.py
git commit -m "feat(banger): sonic score with dark-genre valence correction"
```

---

### Task 3: Replay percentile, composite degradation, confidence

**Files:**
- Modify: `service/app/enrichment/banger_scoring.py`
- Test: `service/app/tests/test_banger_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# append to service/app/tests/test_banger_scoring.py
from app.enrichment.banger_scoring import (
    percentile_of, composite_banger_score, confidence_score,
)


def test_percentile_of():
    vals = [0.0, 1.0, 2.0, 3.0, 4.0]   # must be pre-sorted
    assert percentile_of(4.0, vals) == 1.0
    assert percentile_of(2.0, vals) == 0.6   # 3 of 5 are <= 2.0
    assert percentile_of(-1.0, vals) == 0.0
    assert percentile_of(1.0, []) == 0.0


def test_composite_all_groups():
    # 0.45*1 + 0.35*0 + 0.20*0 = 0.45
    s = composite_banger_score(popularity=1.0, sonic=0.0, replay=0.0)
    assert round(s, 4) == 0.45


def test_composite_renormalizes_missing_sonic():
    # popularity+replay only -> weights 0.45/0.20 renormalize to 0.692/0.308
    s = composite_banger_score(popularity=1.0, sonic=None, replay=0.0)
    assert round(s, 3) == 0.692


def test_composite_sonic_only():
    s = composite_banger_score(popularity=None, sonic=0.8, replay=None)
    assert round(s, 3) == 0.8


def test_composite_empty():
    assert composite_banger_score() == 0.0


def test_confidence_tiers():
    assert confidence_score(n_groups=3, strong_signals=2, score=1.0) == 1.0
    assert confidence_score(n_groups=2, strong_signals=1, score=0.0) == 0.55
    assert confidence_score(n_groups=1, strong_signals=0, score=0.4) > 0.25
    assert confidence_score(n_groups=1, strong_signals=0, score=0.1) == 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest app/tests/test_banger_scoring.py -v`
Expected: FAIL — `ImportError: cannot import name 'percentile_of'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to service/app/enrichment/banger_scoring.py

GROUP_WEIGHTS = {"popularity": 0.45, "sonic": 0.35, "replay": 0.20}


def percentile_of(value, sorted_values) -> float:
    """Fraction of sorted_values <= value. sorted_values MUST be pre-sorted asc."""
    if not sorted_values:
        return 0.0
    return bisect.bisect_right(sorted_values, value) / len(sorted_values)


def composite_banger_score(popularity=None, sonic=None, replay=None) -> float:
    """Blend present groups; renormalize weights over whichever are not None."""
    parts = {}
    if popularity is not None:
        parts["popularity"] = popularity
    if sonic is not None:
        parts["sonic"] = sonic
    if replay is not None:
        parts["replay"] = replay
    if not parts:
        return 0.0
    wsum = sum(GROUP_WEIGHTS[k] for k in parts)
    score = sum(parts[k] * GROUP_WEIGHTS[k] for k in parts) / wsum
    return _clamp01(score)


def confidence_score(n_groups, strong_signals, score) -> float:
    """Confidence from group coverage + signal agreement (preserves v1 shape)."""
    if strong_signals >= 2:
        return round(min(1.0, 0.85 + min(0.15, score * 0.15)), 4)
    if strong_signals == 1 or n_groups >= 2:
        return round(0.55 + min(0.25, score * 0.25), 4)
    if score > 0.3:
        return round(0.25 + min(0.25, score * 0.25), 4)
    return round(max(0.05, score * 0.5), 4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest app/tests/test_banger_scoring.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add service/app/enrichment/banger_scoring.py service/app/tests/test_banger_scoring.py
git commit -m "feat(banger): replay percentile, group composite, confidence"
```

---

### Task 4: Wire pure module into `banger_detector.py`

**Files:**
- Modify: `service/app/enrichment/banger_detector.py:27-162` (`_compute_banger_scores`)

This task is DB orchestration — covered by the eval run in Task 6 plus an import smoke test here, not new unit tests (the math is fully tested in Tasks 1-3).

- [ ] **Step 1: Extend the SQL to also pull audio features + genre tags**

Replace the `cur.execute(...)` query inside `_compute_banger_scores` (currently `service/app/enrichment/banger_detector.py:35-42`) with one that LEFT JOINs audio features and aggregates genre tags. Keep the existing columns and column order; append the new ones:

```python
cur.execute("""
    SELECT ls.track_id, ls.playcount, ls.listeners,
           ta.artist_id, a.name as artist_name,
           af.bpm, af.loudness_norm, af.onset_rate_norm, af.pulse_clarity,
           af.danceability, af.valence,
           COALESCE(
               array_agg(DISTINCT lft.name) FILTER (WHERE lft.name IS NOT NULL),
               ARRAY[]::text[]
           ) AS tags
    FROM lastfm_stats ls
    JOIN track_artists ta ON ls.track_id = ta.track_id AND ta.role = 'primary'
    JOIN artists a ON ta.artist_id = a.id
    LEFT JOIN track_audio_features af ON ls.track_id = af.track_id
    LEFT JOIN track_lastfm_tags tlt ON ls.track_id = tlt.track_id
    LEFT JOIN lastfm_tags lft ON tlt.tag_id = lft.id
    WHERE ls.playcount > 0 OR ls.listeners > 0
    GROUP BY ls.track_id, ls.playcount, ls.listeners, ta.artist_id, a.name,
             af.bpm, af.loudness_norm, af.onset_rate_norm, af.pulse_clarity,
             af.danceability, af.valence
""")
rows = cur.fetchall()
```

> Tag names require a two-hop join: `track_lastfm_tags.tag_id → lastfm_tags.name`
> (verified against `database_pg.py`). The query above already does this via `tlt`/`lft`.

- [ ] **Step 2: Compute sonic + replay alongside the existing popularity pass**

In the row-unpacking loop (`service/app/enrichment/banger_detector.py:54-67`), unpack the new columns and pre-compute per-track audio dicts + the library-wide sorted list of `log1p(replay_ratio)` for percentile normalization. Then in the final scoring loop (`:100-160`), import the pure helpers and assemble the composite:

```python
from app.enrichment.banger_scoring import (
    composite_banger_score, confidence_score, energy_proxy,
    is_dark_genre, percentile_of, sonic_score,
)
```

For each track:
```python
# --- popularity (existing within_artist_score + global_listener_score) ---
popularity = within_artist_score * 0.60 + global_listener_score * 0.40 \
    if (has_artist_signal or has_global_signal or within_artist_score > 0) else None

# --- sonic (only if audio features present) ---
sonic = None
if t.get("has_audio"):
    dark = is_dark_genre(t["tags"])
    sonic = sonic_score(
        energy=energy_proxy(t["loudness_norm"], t["onset_rate_norm"], t["pulse_clarity"]),
        danceability=t["danceability"],
        loudness_norm=t["loudness_norm"],
        bpm=t["bpm"],
        valence=t["valence"],
        dark=dark,
    )

# --- replay (only if listeners > 0) ---
replay = None
if t["listeners"] and t["listeners"] > 0:
    ratio = t["playcount"] / t["listeners"]
    import math
    replay = percentile_of(math.log1p(ratio), replay_log_sorted)

banger_score = composite_banger_score(popularity=popularity, sonic=sonic, replay=replay)
n_groups = sum(x is not None for x in (popularity, sonic, replay))
confidence = confidence_score(n_groups, int(has_artist_signal) + int(has_global_signal), banger_score)
```

Append `sonic_audio` and `lastfm_replay_ratio` entries to the existing `sources` list (with `value` and the raw sub-values), matching the spec's JSON shape. Keep the existing `lastfm_artist_rank` / `lastfm_global_listeners` source entries.

> Build `replay_log_sorted` once before the loop:
> ```python
> import math
> replay_log_sorted = sorted(
>     math.log1p(t["playcount"] / t["listeners"])
>     for t in tracks if t["listeners"] and t["listeners"] > 0
> )
> ```

- [ ] **Step 3: Import smoke test (no DB needed — conftest stubs psycopg2)**

Run: `python -m pytest app/tests/ -q -k "banger or import" && python -c "import app.enrichment.banger_detector"`
Expected: pure tests pass; module imports without error.

- [ ] **Step 4: Full pure-test + ruff gate**

Run: `python -m pytest app/tests/test_banger_scoring.py -v && ruff check app/enrichment/banger_detector.py app/enrichment/banger_scoring.py`
Expected: 14 tests PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add service/app/enrichment/banger_detector.py
git commit -m "feat(banger): composite scoring from audio features + replay ratio"
```

---

### Task 5: Update documentation (Documentation Freshness Policy)

**Files:**
- Modify: `AGENTS.md` (Banger Detection step in pipeline list + curation scoring section)
- Modify: `README.md` (banger description lines)
- Modify: `service/app/enrichment/banger_detector.py:1-8` (module docstring)

- [ ] **Step 1: Update the module docstring**

Replace the v1 docstring at the top of `banger_detector.py` to describe the three groups (popularity / sonic / replay), their weights (0.45/0.35/0.20), and graceful degradation. Reference the spec path.

- [ ] **Step 2: Update AGENTS.md**

Update the "Banger Detection" pipeline description (around `AGENTS.md:451`) from "Last.fm playcount/listeners → within-artist rank + global percentile" to the 3-group composite, and note it now also reads `track_audio_features` + genre tags.

- [ ] **Step 3: Update README.md**

Update the banger description lines (e.g. `README.md:87`, `:297`) to "Composite banger detection (Last.fm popularity + sonic audio profile + replay ratio)".

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md README.md service/app/enrichment/banger_detector.py
git commit -m "docs(banger): describe v2 composite scoring across docs"
```

---

### Task 6: Recompute + eval validation (Algorithm Change Policy)

**Files:** none (operational).

- [ ] **Step 1: Rebuild the container with the new code**

```bash
cd /home/tom/nas/webapps/jellyfin-playlist-generator
docker compose --profile unified up -d --build app
```

- [ ] **Step 2: Recompute banger flags**

```bash
docker exec playlist-generator curl -fsS -X POST http://localhost:8080/enrich/banger-flags
```
Expected: success JSON; non-zero rows written.

- [ ] **Step 3: Sanity-check the distribution**

```bash
docker exec playlist-generator-db psql -U postgres -d playlist \
  -c "SELECT count(*) FILTER (WHERE banger_score>0) AS scored,
             round(avg(banger_score)::numeric,3) AS avg,
             round(max(banger_score)::numeric,3) AS max
      FROM track_banger_flags;"
```
Expected: scored count comparable to the v1 run; avg/max in a plausible 0–1 range.

- [ ] **Step 4: Eval run vs baseline**

```bash
BACKEND_URL=http://localhost:8080 ./eval_loop.py --multi --max-iter 2
```
Expected: results at or above the historical baseline table. Apply the eval-changes keep/revert/iterate decision tree. Do NOT consider the change complete until this passes.

- [ ] **Step 5: Final commit / branch ready for merge**

If eval passes, the branch `feat/banger-factor-v2` is ready. Update the submodule pointer in the parent `~/nas` repo per the usual `chore: bump playlist-generator submodule` flow.

---

## Self-Review Notes

- **Spec coverage:** popularity (kept) ✓, sonic from `track_audio_features` ✓ (Task 2/4), replay ratio ✓ (Task 3/4), valence genre-correction ✓ (Task 2), graceful degradation ✓ (Task 3), unchanged output contract ✓ (Task 4 keeps `track_banger_flags` writes), confidence ✓ (Task 3), sources JSON ✓ (Task 4 Step 2), eval validation ✓ (Task 6). Dropped groups B/C are out of scope per spec.
- **Type consistency:** `tempo_score`, `energy_proxy`, `is_dark_genre`, `sonic_score`, `percentile_of`, `composite_banger_score`, `confidence_score` signatures are identical across the plan and their call site in Task 4.
- **Resolved:** tag names come via `track_lastfm_tags.tag_id → lastfm_tags.name` (two-hop join, baked into the Task 4 query).
