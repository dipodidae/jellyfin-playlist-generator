# Playlist Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four confirmed playlist-quality bugs — genre-blind candidate admission, journey prompts ignoring per-segment genre, unbounded artist/album repetition, and near-duplicate tracks.

**Architecture:** A new pure-Python module (`textnorm`, `admission`) holds logic that is unit-tested in isolation. Targeted edits to `candidates.py`, `sequencer.py`, `composer_v4.py`, and `intent.py` wire that logic into the pipeline. Pure logic is TDD'd; integration wiring is validated by the eval harness + regenerating the user's 8 real prompts.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL+pgvector, numpy. Tests via pytest. App runs in Docker (`playlist-generator` container, port 8080); source is baked into the image so algorithm changes require a container rebuild before eval.

---

## Conventions for this plan

- **Branch:** all work on `playlist-quality-fixes`.
- **Unit tests** run on the host against pure modules only (stdlib-only imports), via a throwaway venv:
  `python3 -m venv /tmp/plq-venv && /tmp/plq-venv/bin/pip -q install pytest`
  then `/tmp/plq-venv/bin/python -m pytest service/app/tests/<file> -v`.
- Tests live in `service/app/tests/` (new dir). The two modules under test (`textnorm.py`, `admission.py`) import **only** the stdlib so the host venv needs no app deps.
- Integration changes (candidates/sequencer/intent/composer) are verified in **Task 8** (rebuild + eval + real-prompt regeneration), not by unit tests — consistent with the project's Algorithm Change Policy.

---

## Task 1: Branch + test scaffold

**Files:**
- Create: `service/app/tests/__init__.py` (empty)

- [ ] **Step 1: Create branch**

```bash
cd /home/tom/nas/webapps/jellyfin-playlist-generator
git checkout -b playlist-quality-fixes
```

- [ ] **Step 2: Create test package + host venv**

```bash
mkdir -p service/app/tests
touch service/app/tests/__init__.py
python3 -m venv /tmp/plq-venv
/tmp/plq-venv/bin/pip -q install pytest
```

- [ ] **Step 3: Commit**

```bash
git add service/app/tests/__init__.py
git commit -m "test: add tests package for trajectory unit tests"
```

---

## Task 2: `textnorm` module (artist + title normalization)

**Files:**
- Create: `service/app/trajectory/textnorm.py`
- Test: `service/app/tests/test_textnorm.py`

- [ ] **Step 1: Write the failing tests**

```python
# service/app/tests/test_textnorm.py
from app.trajectory.textnorm import normalize_artist, normalize_title


def test_normalize_artist_strips_accents_and_case():
    assert normalize_artist("Voïvod") == normalize_artist("Voivod")
    assert normalize_artist("Motörhead") == "motorhead"
    assert normalize_artist(None) is None


def test_normalize_title_strips_version_qualifiers():
    base = normalize_title("Suck Your Bone")
    assert normalize_title("Suck Your Bone (live)") == base
    assert normalize_title("Suck Your Bone (Radio 1 session)") == base
    assert normalize_title("Stranger (remix)") == normalize_title("Stranger")
    assert normalize_title("Hollow Eyes (single version)") == normalize_title("Hollow Eyes")
    assert normalize_title("A Day (Tibet mix)") == normalize_title("A Day")
    assert normalize_title("Guardian (demo)") == normalize_title("Guardian")
    assert normalize_title("Bela Lugosi's Dead (2008 remaster)") == normalize_title("Bela Lugosi's Dead")


def test_normalize_title_keeps_distinct_songs_distinct():
    assert normalize_title("Guardian") != normalize_title("The Sorceress")


def test_normalize_title_strips_featuring():
    assert normalize_title("Song (feat. Someone)") == normalize_title("Song")
    assert normalize_title("Song feat. Someone") == normalize_title("Song")


def test_normalize_title_untitled_does_not_collapse_to_empty():
    assert normalize_title("[untitled]") != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/tmp/plq-venv/bin/python -m pytest service/app/tests/test_textnorm.py -v` (from `service/` so `app` is importable: `cd service && /tmp/plq-venv/bin/python -m pytest app/tests/test_textnorm.py -v`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.trajectory.textnorm'`

- [ ] **Step 3: Write the module**

```python
# service/app/trajectory/textnorm.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd service && /tmp/plq-venv/bin/python -m pytest app/tests/test_textnorm.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add service/app/trajectory/textnorm.py service/app/tests/test_textnorm.py
git commit -m "feat: add textnorm module for artist/title normalization"
```

---

## Task 3: Genre-aware admissibility predicate

**Files:**
- Create: `service/app/trajectory/admission.py`
- Test: `service/app/tests/test_admission.py`
- Modify: `service/app/trajectory/candidates.py:1255-1260`

- [ ] **Step 1: Write the failing tests**

```python
# service/app/tests/test_admission.py
from app.trajectory.admission import is_admissible


def _kw(**over):
    base = dict(
        semantic_score=0.5, semantic_floor=0.2,
        genre_match_score=0.0, admissibility_score=0.5,
        admissibility_floor=0.35, negative_constraint_penalty=0.0,
        neg_constraint_ceiling=0.45, has_genre_hints=True,
    )
    base.update(over)
    return base


def test_clears_semantic_floor():
    assert is_admissible(**_kw(semantic_score=0.5)) is True


def test_below_floor_but_strong_genre_is_admitted():
    # This is the coldwave fix: genre-pool tracks carry semantic_score=0.15.
    assert is_admissible(**_kw(semantic_score=0.15, genre_match_score=0.6)) is True


def test_below_floor_weak_genre_rejected():
    assert is_admissible(**_kw(semantic_score=0.15, genre_match_score=0.2)) is False


def test_strong_genre_ignored_when_no_hints():
    assert is_admissible(**_kw(semantic_score=0.15, genre_match_score=0.9,
                               has_genre_hints=False)) is False


def test_admissibility_floor_gates_everything():
    assert is_admissible(**_kw(admissibility_score=0.1)) is False


def test_negative_constraint_ceiling_gates_everything():
    assert is_admissible(**_kw(negative_constraint_penalty=0.5)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd service && /tmp/plq-venv/bin/python -m pytest app/tests/test_admission.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.trajectory.admission'`

- [ ] **Step 3: Write the module**

```python
# service/app/trajectory/admission.py
"""Pure admissibility predicate for the candidate gate.

Stdlib-only so it is unit-testable without app dependencies.
"""
from __future__ import annotations

# A track below the semantic floor is still admitted if it is a strong
# match for a primary genre hint — this lets the genre/tag secondary pools
# (which carry a low baseline semantic_score) actually contribute.
STRONG_GENRE_THRESHOLD = 0.50


def is_admissible(
    *,
    semantic_score: float,
    semantic_floor: float,
    genre_match_score: float,
    admissibility_score: float,
    admissibility_floor: float,
    negative_constraint_penalty: float,
    neg_constraint_ceiling: float,
    has_genre_hints: bool,
    strong_genre_threshold: float = STRONG_GENRE_THRESHOLD,
) -> bool:
    """Return True if a candidate passes the admissibility gate."""
    if admissibility_score < admissibility_floor:
        return False
    if negative_constraint_penalty >= neg_constraint_ceiling:
        return False
    if semantic_score >= semantic_floor:
        return True
    if has_genre_hints and genre_match_score >= strong_genre_threshold:
        return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd service && /tmp/plq-venv/bin/python -m pytest app/tests/test_admission.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Wire the predicate into the candidate gate**

In `service/app/trajectory/candidates.py`, add the import near the other trajectory imports at the top of the file:

```python
from app.trajectory.admission import is_admissible
```

Replace the gate at `candidates.py:1255-1260`:

```python
    admissible_candidates = [
        track for track in staged_candidates
        if track.semantic_score >= semantic_floor
        and track.admissibility_score >= admissibility_floor
        and track.negative_constraint_penalty < neg_constraint_ceiling
    ]
```

with:

```python
    has_hints = bool(hint_set)
    admissible_candidates = [
        track for track in staged_candidates
        if is_admissible(
            semantic_score=track.semantic_score,
            semantic_floor=semantic_floor,
            genre_match_score=track.genre_match_score,
            admissibility_score=track.admissibility_score,
            admissibility_floor=admissibility_floor,
            negative_constraint_penalty=track.negative_constraint_penalty,
            neg_constraint_ceiling=neg_constraint_ceiling,
            has_genre_hints=has_hints,
        )
    ]
```

- [ ] **Step 6: Syntax-check the edited file**

Run: `cd service && /tmp/plq-venv/bin/python -c "import ast; ast.parse(open('app/trajectory/candidates.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add service/app/trajectory/admission.py service/app/tests/test_admission.py service/app/trajectory/candidates.py
git commit -m "feat: genre-aware admissibility gate (admit strong genre matches below semantic floor)"
```

---

## Task 4: Near-duplicate dedup in the candidate pool

**Files:**
- Modify: `service/app/trajectory/candidates.py` (in `generate_position_pools`, right after `global_candidates = list(pool_map.values())` at `:1142`)

- [ ] **Step 1: Add import**

In `service/app/trajectory/candidates.py` top imports, add:

```python
from app.trajectory.textnorm import normalize_artist, normalize_title
```

- [ ] **Step 2: Add the dedup helper function**

Add this module-level function in `candidates.py` (place it just above `def generate_position_pools(`):

```python
def _dedupe_near_duplicates(
    candidates: list["CandidateTrack"],
) -> list["CandidateTrack"]:
    """Collapse (artist, normalized-title) duplicates, keeping one version.

    Prefers the version whose raw title has no parenthetical/bracket
    qualifier (i.e. the studio cut over a (live)/(demo)/(remix)); ties are
    broken by higher semantic_score.
    """
    best: dict[tuple[str | None, str], "CandidateTrack"] = {}
    for c in candidates:
        sig = (normalize_artist(c.artist_name), normalize_title(c.title))
        incumbent = best.get(sig)
        if incumbent is None:
            best[sig] = c
            continue
        c_clean = "(" not in c.title and "[" not in c.title
        inc_clean = "(" not in incumbent.title and "[" not in incumbent.title
        if (c_clean, c.semantic_score) > (inc_clean, incumbent.semantic_score):
            best[sig] = c
    return list(best.values())
```

- [ ] **Step 3: Call it after the pool is assembled**

In `generate_position_pools`, find (`candidates.py:1142`):

```python
    global_candidates = list(pool_map.values())

    if not global_candidates:
        logger.warning("No candidates found across all pool sources")
        return []
```

Replace with:

```python
    global_candidates = list(pool_map.values())

    if not global_candidates:
        logger.warning("No candidates found across all pool sources")
        return []

    _pre_dedup = len(global_candidates)
    global_candidates = _dedupe_near_duplicates(global_candidates)
    if len(global_candidates) != _pre_dedup:
        logger.info(
            f"Near-duplicate dedup: {_pre_dedup} → {len(global_candidates)} candidates"
        )
```

- [ ] **Step 4: Syntax-check**

Run: `cd service && /tmp/plq-venv/bin/python -c "import ast; ast.parse(open('app/trajectory/candidates.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add service/app/trajectory/candidates.py
git commit -m "feat: collapse near-duplicate tracks (live/demo/remix/reimport) in candidate pool"
```

---

## Task 5: Hard artist/album caps + dedup backstop in the sequencer

**Files:**
- Modify: `service/app/trajectory/sequencer.py` (config, BeamPath, normalizer delegate, `is_valid_extension`, `_relaxed_config`, both extenders)
- Modify: `service/app/trajectory/composer_v4.py` (set caps from `target_size` in both compose functions)

- [ ] **Step 1: Delegate `_normalize_artist` to textnorm and import title normalizer**

In `sequencer.py`, replace the body of `_normalize_artist` (`:28-41`) so it delegates (keep the function + its `lru_cache` so call sites are unchanged):

```python
from app.trajectory.textnorm import normalize_artist as _norm_artist_impl
from app.trajectory.textnorm import normalize_title


@lru_cache(maxsize=4096)
def _normalize_artist(name: str | None) -> str | None:
    """Normalize artist name for comparison (delegates to textnorm)."""
    return _norm_artist_impl(name)
```

(Leave the existing `import unicodedata` if still referenced elsewhere; if not, remove it.)

- [ ] **Step 2: Extend `SequencerConfig`**

Replace `SequencerConfig` (`sequencer.py:44-55`) field block to add three fields:

```python
@dataclass
class SequencerConfig:
    """Configuration for beam search sequencer."""
    beam_width: int = 12
    min_artist_distance: int = 4
    max_artist_count: int = 4
    max_album_count: int = 2
    # Absolute ceilings the relaxation ladder may never exceed (None = no cap).
    hard_max_artist_count: int | None = None
    hard_max_album_count: int | None = None
    max_cluster_per_window: int = 8
    cluster_window_size: int = 10
    max_duration_ratio: float = 3.0
    lookahead_weight: float = 0.30
    bridge_bonus_weight: float = 0.05
    diversity_threshold: float = 0.8
```

- [ ] **Step 3: Extend `BeamPath` (fields + copy)**

In `BeamPath` (`sequencer.py:58-83`), add two fields and copy them. Add after `track_ids` (`:68`):

```python
    album_counts: dict[str, int] = field(default_factory=dict)  # album key -> count
    signatures: set = field(default_factory=set)  # (norm_artist, norm_title) dedup keys
```

And in `copy()` add to the constructor call:

```python
            album_counts=self.album_counts.copy(),
            signatures=self.signatures.copy(),
```

- [ ] **Step 4: Add album-key + record helpers**

Add these module-level helpers in `sequencer.py` (just above `is_valid_extension`):

```python
def _album_key(candidate: CandidateTrack) -> str | None:
    """Stable per-album key: album_id when present, else normalized name."""
    if candidate.album_id:
        return str(candidate.album_id)
    if candidate.album_name:
        return "name:" + (normalize_title(candidate.album_name) or "")
    return None


def _record_track(
    new_path: BeamPath,
    candidate: CandidateTrack,
    norm_artist: str | None,
    position: int,
) -> None:
    """Append a track to a path and update all constraint-tracking state."""
    new_path.tracks.append(candidate)
    new_path.track_ids.add(candidate.id)
    new_path.signatures.add((norm_artist, normalize_title(candidate.title)))
    if norm_artist:
        new_path.artist_positions[norm_artist] = position
        new_path.artist_counts[norm_artist] = \
            new_path.artist_counts.get(norm_artist, 0) + 1
    album_key = _album_key(candidate)
    if album_key:
        new_path.album_counts[album_key] = \
            new_path.album_counts.get(album_key, 0) + 1
    if candidate.cluster_id is not None:
        new_path.cluster_counts[candidate.cluster_id] = \
            new_path.cluster_counts.get(candidate.cluster_id, 0) + 1
```

- [ ] **Step 5: Enforce new constraints in `is_valid_extension`**

In `is_valid_extension`, after the duplicate-track check (`sequencer.py:120-122`), add the signature backstop:

```python
    # Near-duplicate backstop: reject another version of an already-used song.
    norm_title = normalize_title(candidate.title)
    norm_artist_sig = _normalize_artist(candidate.artist_name)
    if (norm_artist_sig, norm_title) in path.signatures:
        return False
```

Then, after the artist total-count cap (`sequencer.py:131-133`), add album + hard caps:

```python
    # Album total count cap — prevents one album dominating the playlist.
    album_key = _album_key(candidate)
    if album_key and path.album_counts.get(album_key, 0) >= config.max_album_count:
        return False

    # Absolute hard ceilings (never relaxed by the fallback ladder).
    if (config.hard_max_artist_count is not None and norm_artist
            and path.artist_counts.get(norm_artist, 0) >= config.hard_max_artist_count):
        return False
    if (config.hard_max_album_count is not None and album_key
            and path.album_counts.get(album_key, 0) >= config.hard_max_album_count):
        return False
```

(`norm_artist` is already computed at `:125` as `_normalize_artist(candidate.artist_name)`; reuse it rather than re-deriving.)

- [ ] **Step 6: Clamp the relaxation ladder (no more 999)**

Replace `_relaxed_config` (`sequencer.py:384-429`) so every level carries the new fields and clamps to the hard ceilings:

```python
def _relaxed_config(base: SequencerConfig, level: int) -> SequencerConfig:
    """Return a progressively relaxed copy of *base* for constraint fallback.

    Artist/album caps are clamped to the absolute hard ceilings at every
    level, so relaxation can loosen distance/cluster constraints but can
    never dump one artist or album.
    """
    if level <= 0:
        return base

    def _clamp_artist(val: int) -> int:
        if base.hard_max_artist_count is not None:
            return min(val, base.hard_max_artist_count)
        return val

    def _clamp_album(val: int) -> int:
        if base.hard_max_album_count is not None:
            return min(val, base.hard_max_album_count)
        return val

    common = dict(
        beam_width=base.beam_width,
        hard_max_artist_count=base.hard_max_artist_count,
        hard_max_album_count=base.hard_max_album_count,
        cluster_window_size=base.cluster_window_size,
        lookahead_weight=base.lookahead_weight,
        bridge_bonus_weight=base.bridge_bonus_weight,
    )

    if level == 1:
        return SequencerConfig(
            min_artist_distance=max(2, base.min_artist_distance // 2),
            max_artist_count=_clamp_artist(max(4, base.max_artist_count + 1)),
            max_album_count=_clamp_album(base.max_album_count),
            max_cluster_per_window=base.cluster_window_size - 1,
            max_duration_ratio=5.0,
            diversity_threshold=base.diversity_threshold,
            **common,
        )
    if level == 2:
        return SequencerConfig(
            min_artist_distance=1,
            max_artist_count=_clamp_artist(max(5, base.max_artist_count + 2)),
            max_album_count=_clamp_album(base.max_album_count + 1),
            max_cluster_per_window=base.cluster_window_size,
            max_duration_ratio=10.0,
            diversity_threshold=1.0,
            **common,
        )
    # level >= 3: emergency — drop distance/cluster/duration limits, but keep
    # artist/album ceilings (hard cap if set, else the prior relaxed value).
    return SequencerConfig(
        min_artist_distance=0,
        max_artist_count=_clamp_artist(max(6, base.max_artist_count + 2)),
        max_album_count=_clamp_album(base.max_album_count + 1),
        max_cluster_per_window=999,
        max_duration_ratio=999.0,
        diversity_threshold=1.0,
        **common,
    )
```

- [ ] **Step 7: Use `_record_track` in both extenders**

In `_extend_single_path`, replace the manual update block (`sequencer.py:621-636`):

```python
        new_path = path.copy()
        new_path.tracks.append(candidate)
        new_path.track_ids.add(candidate.id)
        new_path.cumulative_score = path.cumulative_score + extension_score

        if norm_artist:
            new_path.artist_positions[norm_artist] = position
            new_path.artist_counts[norm_artist] = \
                new_path.artist_counts.get(norm_artist, 0) + 1
        if candidate.cluster_id is not None:
            new_path.cluster_counts[candidate.cluster_id] = \
                new_path.cluster_counts.get(candidate.cluster_id, 0) + 1
        if candidate.genre_probs:
            new_path.cumulative_genre_dist = _update_cumulative_genre_dist(
                path.cumulative_genre_dist, candidate.genre_probs, len(path.tracks)
            )
```

with:

```python
        new_path = path.copy()
        if candidate.genre_probs:
            new_path.cumulative_genre_dist = _update_cumulative_genre_dist(
                path.cumulative_genre_dist, candidate.genre_probs, len(path.tracks)
            )
        _record_track(new_path, candidate, norm_artist, position)
        new_path.cumulative_score = path.cumulative_score + extension_score
```

(Note: `_update_cumulative_genre_dist` uses `len(path.tracks)` — call it BEFORE `_record_track` appends, as shown.)

In `_greedy_extend_path`, replace its update block (`sequencer.py:678-689`):

```python
    new_path = path.copy()
    new_path.tracks.append(best_candidate)
    new_path.track_ids.add(best_candidate.id)
    new_path.cumulative_score = path.cumulative_score + best_score

    if best_norm_artist:
        new_path.artist_positions[best_norm_artist] = position
        new_path.artist_counts[best_norm_artist] = \
            new_path.artist_counts.get(best_norm_artist, 0) + 1
    if best_candidate.cluster_id is not None:
        new_path.cluster_counts[best_candidate.cluster_id] = \
            new_path.cluster_counts.get(best_candidate.cluster_id, 0) + 1

    return new_path
```

with:

```python
    new_path = path.copy()
    _record_track(new_path, best_candidate, best_norm_artist, position)
    new_path.cumulative_score = path.cumulative_score + best_score

    return new_path
```

- [ ] **Step 8: Set caps from target_size in the composer**

In `service/app/trajectory/composer_v4.py`, in BOTH `compose_playlist_v4` and `compose_playlist_v4_streaming`, find the block:

```python
    if config is None:
        config = SequencerConfig()
```

Replace (in both functions) with:

```python
    if config is None:
        config = SequencerConfig()
    # Derive absolute artist/album ceilings from playlist size so no single
    # artist/album can dominate; relaxation can never exceed these.
    ts = max(1, intent.target_size)
    config = dc_replace(
        config,
        hard_max_artist_count=max(3, round(ts * 0.25)),
        max_album_count=max(2, round(ts * 0.15)),
        hard_max_album_count=max(2, round(ts * 0.15)) + 1,
    )
```

(`dc_replace` is already imported at `composer_v4.py:14`.)

- [ ] **Step 9: Syntax-check both files**

Run:
```bash
cd service && /tmp/plq-venv/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ['app/trajectory/sequencer.py','app/trajectory/composer_v4.py']]; print('ok')"
```
Expected: `ok`

- [ ] **Step 10: Commit**

```bash
git add service/app/trajectory/sequencer.py service/app/trajectory/composer_v4.py
git commit -m "feat: hard artist/album caps (no 999 relaxation) + album cap + dedup backstop"
```

---

## Task 6: Per-segment genre waypoints

**Files:**
- Modify: `service/app/trajectory/intent.py` (LLM schema text, waypoint validation, `TrajectoryWaypoint`, waypoint population, `segment_genres_at`)
- Modify: `service/app/trajectory/candidates.py` (`build_phase_queries`, per-segment DB pool, per-position genre scoring)

- [ ] **Step 1: Add `genres` to the LLM custom_waypoints schema text**

In `intent.py`, in `_LLM_INTENT_SYSTEM_PROMPT`, find the custom_waypoints bullet (`:1046-1055`) and add a `genres` sub-field. Replace:

```
  - "description": Short label for this phase
  If null, the system will generate waypoints from arc_type and base dimensions.
```

with:

```
  - "description": Short label for this phase
  - "genres": Array of genre strings dominant in THIS phase (e.g. ["ambient","drone"] \
for an opening, ["doom metal","sludge"] for a finale). Critical for multi-genre journeys: \
set per-phase genres whenever the user names different styles for different stages.
  If null, the system will generate waypoints from arc_type and base dimensions.
```

- [ ] **Step 2: Add `genres` to `TrajectoryWaypoint`**

In `intent.py`, in `TrajectoryWaypoint` (`:56`), add after `description: str = ""`:

```python
    genres: list[str] = field(default_factory=list)  # per-phase genre hints
```

(`field` is already imported — it is used elsewhere in the file.)

- [ ] **Step 3: Validate per-waypoint genres**

In `intent.py` `_validate_llm_intent`, the custom_waypoints loop (`:1186-1199`) builds a NEW dict via `validated.append({...})`. Add a `"genres"` key to that dict literal. Change:

```python
                    validated.append({
                        "position": max(0.0, min(1.0, float(wp.get("position", 0.5)))),
                        "energy": max(0.0, min(1.0, float(wp.get("energy", 0.5)))),
                        "darkness": max(0.0, min(1.0, float(wp.get("darkness", 0.5)))),
                        "tempo": max(0.0, min(1.0, float(wp.get("tempo", 0.5)))),
                        "texture": max(0.0, min(1.0, float(wp.get("texture", 0.5)))),
                        "era": max(0.0, min(1.0, float(wp.get("era", 0.5)))),
                        "description": str(wp.get("description", "")),
                    })
```

to:

```python
                    _wp_genres = wp.get("genres")
                    validated.append({
                        "position": max(0.0, min(1.0, float(wp.get("position", 0.5)))),
                        "energy": max(0.0, min(1.0, float(wp.get("energy", 0.5)))),
                        "darkness": max(0.0, min(1.0, float(wp.get("darkness", 0.5)))),
                        "tempo": max(0.0, min(1.0, float(wp.get("tempo", 0.5)))),
                        "texture": max(0.0, min(1.0, float(wp.get("texture", 0.5)))),
                        "era": max(0.0, min(1.0, float(wp.get("era", 0.5)))),
                        "description": str(wp.get("description", "")),
                        "genres": [str(g).lower() for g in _wp_genres if g]
                                  if isinstance(_wp_genres, list) else [],
                    })
```

- [ ] **Step 4: Populate waypoint.genres when building from custom_waypoints**

In `intent.py`, where custom waypoints become `TrajectoryWaypoint` objects (`:1285-1297`), add `genres=` to the constructor. The block currently is:

```python
        waypoints = [
            TrajectoryWaypoint(
                position=wp["position"],
                energy=wp["energy"],
                darkness=wp["darkness"],
                tempo=wp["tempo"],
                texture=wp["texture"],
                era=wp.get("era", 0.5),
                phase_label=wp.get("description", ""),
                description=wp.get("description", ""),
            )
            for wp in custom_wps
        ]
```

Add one line before the closing `)`:

```python
                phase_label=wp.get("description", ""),
                description=wp.get("description", ""),
                genres=wp.get("genres", []),
```

- [ ] **Step 5: Add `segment_genres_at` to `PlaylistIntent`**

In `intent.py`, add a method to `PlaylistIntent` (after the dataclass fields, before the next top-level def):

```python
    def segment_genres_at(self, t_norm: float) -> list[str]:
        """Genres of the waypoint nearest to normalized position t_norm.

        Returns [] when no waypoint carries per-segment genres (callers then
        fall back to the global genre_hints).
        """
        wps = [w for w in self.waypoints if getattr(w, "genres", None)]
        if not wps:
            return []
        nearest = min(wps, key=lambda w: abs(w.position - t_norm))
        return list(nearest.genres)

    def has_segment_genres(self) -> bool:
        return any(getattr(w, "genres", None) for w in self.waypoints)
```

- [ ] **Step 6: Build phase queries from segment genres**

In `candidates.py`, replace `build_phase_queries` (`:745-785`) so segment genres drive retrieval when present:

```python
def build_phase_queries(intent: PlaylistIntent) -> list[str]:
    """Build phase-specific text queries for multi-query semantic retrieval.

    When the intent carries per-segment genres (a multi-genre journey), each
    phase query is built from that segment's genres so the pool actually
    contains the early- and late-segment styles. Otherwise falls back to the
    generic arc phase descriptions.
    """
    prompt = intent.raw_prompt
    arc = intent.arc_type

    if intent.has_segment_genres():
        seg_queries: list[str] = [prompt]
        for wp in intent.waypoints:
            genres = getattr(wp, "genres", None)
            if genres:
                label = wp.description or ""
                seg_queries.append(f"{' '.join(genres)} {label}".strip())
        # De-duplicate while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for q in seg_queries:
            if q not in seen:
                seen.add(q)
                out.append(q)
        return out

    phase_map: dict[ArcType, list[str]] = {
        ArcType.RISE: [
            f"{prompt} quiet gentle intro",
            f"{prompt} energetic intense climax",
        ],
        ArcType.FALL: [
            f"{prompt} high energy opening",
            f"{prompt} gentle quiet fade outro",
        ],
        ArcType.PEAK: [
            f"{prompt} calm subdued intro",
            f"{prompt} intense explosive peak climax",
            f"{prompt} resolve mellow denouement",
        ],
        ArcType.VALLEY: [
            f"{prompt} high energy opening",
            f"{prompt} subdued quiet center",
        ],
        ArcType.WAVE: [
            f"{prompt} build energy rise",
            f"{prompt} peak intense climax",
            f"{prompt} resolve calm",
        ],
        ArcType.JOURNEY: [
            f"{prompt} intro beginning",
            f"{prompt} peak intense climax",
            f"{prompt} resolve ending denouement",
        ],
    }

    return phase_map.get(arc, [prompt])
```

- [ ] **Step 7: Guarantee segment genres via a DB pool**

In `candidates.py` `generate_position_pools`, the genre secondary pool at `:1055-1085` filters by `intent.genre_hints`. Extend the `specific_genre_hints` set with all per-segment genres so segment styles are pulled from the DB even when semantically sparse. Find (`:1058-1059`):

```python
    specific_genre_hints = [g for g in intent.genre_hints
                           if g.lower() not in _BROAD_GENRES]
```

Replace with:

```python
    _all_hints = list(intent.genre_hints)
    if intent.has_segment_genres():
        for wp in intent.waypoints:
            _all_hints.extend(getattr(wp, "genres", []) or [])
    specific_genre_hints = [g for g in dict.fromkeys(h.lower() for h in _all_hints)
                           if g not in _BROAD_GENRES]
```

- [ ] **Step 8: Per-position genre scoring against the segment**

In `candidates.py` `generate_position_pools`, the per-position scoring loop (`:1302-1350`) currently scores trajectory only; `genre_match_score` was set once globally in the staging loop. Make genre match position-aware when segment genres exist.

First, just before the `for position in range(intent.target_size):` loop (`:1302`), add:

```python
    seg_genres_active = intent.has_segment_genres()
    # Map each candidate id to its staged (global) genre match for fallback.
    _global_genre = {t.id: t.genre_match_score for t in admissible_candidates}
```

Then inside the loop, after computing `t_norm` (`:1304`) and before scoring candidates, compute the segment hint set for this position:

```python
        if seg_genres_active:
            seg_hints = {g.lower() for g in intent.segment_genres_at(t_norm)}
            for g in list(seg_hints):
                fam = _ALIAS_TO_FAMILY.get(g)
                if fam:
                    seg_hints.add(fam)
        else:
            seg_hints = None
```

Then, inside `for track in admissible_candidates:` (`:1317`), before building `scored_track`, recompute genre match for the segment:

```python
            if seg_hints is not None:
                seg_genre_match = compute_genre_match_score(track, seg_hints, seg_hints)
            else:
                seg_genre_match = track.genre_match_score
```

And in the `replace(track, ...)` call that builds `scored_track` (`:1331-1342`), add the field:

```python
                genre_match_score=seg_genre_match,
```

(`compute_genre_match_score` and `_ALIAS_TO_FAMILY` are already imported/used in this module.)

- [ ] **Step 9: Syntax-check both files**

Run:
```bash
cd service && /tmp/plq-venv/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ['app/trajectory/intent.py','app/trajectory/candidates.py']]; print('ok')"
```
Expected: `ok`

- [ ] **Step 10: Commit**

```bash
git add service/app/trajectory/intent.py service/app/trajectory/candidates.py
git commit -m "feat: per-segment genre waypoints for multi-genre journey prompts"
```

---

## Task 7: Documentation updates

**Files:**
- Modify: `AGENTS.md` (V4 Scoring section: admissibility predicate, sequencer constraints incl. album cap + hard ceilings, per-segment genre)
- Modify: `.windsurf/skills/eval-changes/SKILL.md` (current constraint/weight state)
- Modify: `webapps/jellyfin-playlist-generator/CLAUDE.md` (gotcha: source baked into image → rebuild before eval)

- [ ] **Step 1: Update AGENTS.md**

In `AGENTS.md`, in the V4 Scoring / sequencing section, document: (a) the admissibility gate now admits below-floor tracks that are strong primary-genre matches (`genre_match_score >= 0.50`); (b) sequencer enforces `max_album_count` and absolute `hard_max_artist_count`/`hard_max_album_count` (derived from `target_size`: artist ≈25%, album ≈15%) that relaxation never exceeds; (c) near-duplicate dedup by `(normalized artist, normalized title)`; (d) per-segment genre waypoints drive phase queries and per-position genre scoring for multi-genre journeys. (Edit the existing prose to match; do not invent a new section if one exists.)

- [ ] **Step 2: Update eval-changes SKILL.md**

In `.windsurf/skills/eval-changes/SKILL.md`, update the "current weight state" / constraints summary to reflect the new caps and the genre-aware admissibility predicate.

- [ ] **Step 3: Update CLAUDE.md gotcha**

In `webapps/jellyfin-playlist-generator/CLAUDE.md`, add a gotcha under the Gotchas list:

```markdown
6. **Docker image bakes the source.** The running stack (`docker-compose.yml`, `unified` profile) builds `service/` into the `playlist-generator` image; only `/music` and `/playlists` are mounted. Algorithm changes are NOT live until you rebuild: `docker compose --profile unified up -d --build app`. The DB (`playlist-generator-db`) is published on `127.0.0.1:5432`.
```

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md .windsurf/skills/eval-changes/SKILL.md webapps/jellyfin-playlist-generator/CLAUDE.md
git commit -m "docs: document genre-aware admission, hard caps, dedup, per-segment genre"
```

---

## Task 8: Build + eval validation

**Files:** none (validation only)

- [ ] **Step 1: Run all unit tests**

Run: `cd service && /tmp/plq-venv/bin/python -m pytest app/tests -v`
Expected: all PASS.

- [ ] **Step 2: Rebuild the app container with the new code**

```bash
cd /home/tom/nas/webapps/jellyfin-playlist-generator
docker compose --profile unified up -d --build app
```
Wait for health (model load ~60-90s):
```bash
until curl -sf http://localhost:8080/health >/dev/null; do sleep 5; done; echo "healthy"
```

- [ ] **Step 3: Provision an eval venv**

```bash
/tmp/plq-venv/bin/pip -q install "httpx>=0.28.0" "openai>=1.58.0"
```

- [ ] **Step 4: Regenerate the user's worst real prompts and inspect diversity/dedup/segment-genre**

For each of: `"start ambient and dreamy, then build into crushing doom"` (size 10),
`"a journey from dreamy shoegaze through post-rock into heavy doom metal"` (size 12),
`"coolest cold wave tracks ever"` (size 30), `"thrash metal workout"` (size 30):

```bash
curl -s -X POST http://localhost:8080/generate-playlist/stream \
  -H "Content-Type: application/json" \
  -d '{"prompt":"<PROMPT>","size":<N>,"save":false}' | tail -5
```
(Adjust to the actual streaming response shape; the goal is to capture the tracklist.)

Then assert by inspection:
- ambient→doom: early tracks are ambient/dark-ambient, late tracks are doom; **>1 artist**.
- coldwave: **≥6 distinct artists** across 30 tracks.
- thrash workout: **no repeated (artist, normalized title)**.

- [ ] **Step 5: Run the eval batch**

```bash
cd /home/tom/nas/webapps/jellyfin-playlist-generator
BACKEND_URL=http://localhost:8080 /tmp/plq-venv/bin/python eval_loop.py --multi --max-iter 2
```
Expected: completes; per-prompt scores produced. Compare arc-coherence / genre-accuracy / curation against the historical baseline in the eval report.

- [ ] **Step 6: Decision**

Apply the eval-changes keep/revert/iterate tree. If a metric regresses materially vs baseline, iterate on the responsible task before finishing. Record the eval summary in the PR/branch description.

- [ ] **Step 7: Finalize**

Use `superpowers:finishing-a-development-branch` to decide merge/PR. Do not commit algorithm changes without a passing eval run (project policy).

---

## Self-review notes
- Spec Fix 0 → Task 2; Fix 1 → Task 3; Fix 2 → Task 6; Fix 3 → Task 5; Fix 4 → Tasks 4 (+ backstop in 5). All covered.
- `normalize_title`/`normalize_artist` names consistent across Tasks 2/4/5.
- `is_admissible` signature in Task 3 matches its call site.
- `_record_track`/`_album_key` defined in Task 5 before use; genre-dist update ordering preserved.
- `segment_genres_at`/`has_segment_genres` defined in Task 6 Step 5 before use in Steps 6-8.
