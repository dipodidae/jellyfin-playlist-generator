# More Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add new audio + metadata metrics (valence, danceability/pulse-clarity/onset-rate, MFCC timbre, instrumentalness, acousticness, studio-vs-live) and wire the high-value ones into scoring and sequencing for better playlists.

**Architecture:** Phase A extends the librosa analyzer + `track_audio_features` to compute/store new metrics (no consumers → zero quality risk). Phase B adds valence as a 6th, prompt-steerable trajectory dimension. Phase C extends the sequencer's acoustic-continuity transition term with rhythmic + timbre/vocal signals. Phase D adds a pure metadata `classify_version` → `studio_score`, applied as a prompt-aware soft penalty + dedup tie-breaker. Each scoring phase (B/C/D) is eval-gated.

**Tech Stack:** Python 3.12, librosa, numpy, psycopg2, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-06-09-more-metrics-design.md`

**Branch:** `more-metrics`

**Test runner:** Host has no Python deps. Create a venv once (see Task 0). Pure-logic tests run there; librosa-dependent analyzer code is verified by import + (where possible) synthetic-signal tests — but librosa itself is heavy and may not be in the test venv, so analyzer tests gate the librosa import and test only the pure helpers. The full analyzer runs in the deployed container.

**Heuristic note for implementers:** valence/instrumentalness/acousticness are intentional heuristic proxies. Implement the formulas in the spec exactly; do not "improve" them with un-specced cleverness — they will be eval-tuned later.

---

## Task 0: Test venv

**Files:** none (environment setup)

- [ ] **Step 1: Create the test venv with the deps the unit tests need**

Run:
```bash
cd /home/tom/nas/webapps/jellyfin-playlist-generator/service
python -m venv .venv-test
.venv-test/bin/pip -q install pytest pydantic pydantic-settings psycopg2-binary httpx numpy ruff
.venv-test/bin/python -c "import pytest, numpy, psycopg2; print('test venv ready')"
```
Expected: `test venv ready`. Do NOT `git add` `.venv-test` (it is a throwaway; only commit named source/test files in every task).

---

# PHASE A — Metric extraction (no consumers, no eval)

## Task A1: DB columns for new audio metrics

**Files:**
- Create: `service/app/migrations/013_audio_metrics_v2.sql`
- Modify: `service/app/database_pg.py` (the `track_audio_features` CREATE TABLE block, ~line 304-319)

- [ ] **Step 1: Write the migration**

Create `service/app/migrations/013_audio_metrics_v2.sql`:

```sql
-- 013_audio_metrics_v2.sql — additional audio metrics (Phase A of more-metrics)
ALTER TABLE track_audio_features ADD COLUMN IF NOT EXISTS valence REAL;
ALTER TABLE track_audio_features ADD COLUMN IF NOT EXISTS danceability REAL;
ALTER TABLE track_audio_features ADD COLUMN IF NOT EXISTS pulse_clarity REAL;
ALTER TABLE track_audio_features ADD COLUMN IF NOT EXISTS onset_rate REAL;
ALTER TABLE track_audio_features ADD COLUMN IF NOT EXISTS onset_rate_norm REAL;
ALTER TABLE track_audio_features ADD COLUMN IF NOT EXISTS instrumentalness REAL;
ALTER TABLE track_audio_features ADD COLUMN IF NOT EXISTS acousticness REAL;
ALTER TABLE track_audio_features ADD COLUMN IF NOT EXISTS mfcc REAL[];
```

- [ ] **Step 2: Mirror the columns in `init_database()` for fresh DBs**

In `service/app/database_pg.py`, locate the `CREATE TABLE IF NOT EXISTS track_audio_features (...)` block. Add the new columns to the column list (before `analyzed_at`):

```python
                    bpm_norm REAL,
                    loudness_norm REAL,
                    brightness_norm REAL,
                    flatness_norm REAL,
                    valence REAL,
                    danceability REAL,
                    pulse_clarity REAL,
                    onset_rate REAL,
                    onset_rate_norm REAL,
                    instrumentalness REAL,
                    acousticness REAL,
                    mfcc REAL[],
                    analyzed_at TIMESTAMPTZ DEFAULT now()
```

- [ ] **Step 3: Verify Python imports**

Run: `cd service && .venv-test/bin/python -c "import ast; ast.parse(open('app/database_pg.py').read()); print('parses')"`
Expected: `parses`.

- [ ] **Step 4: Commit**

```bash
git add service/app/migrations/013_audio_metrics_v2.sql service/app/database_pg.py
git commit -m "feat(metrics): add columns for valence/danceability/timbre audio metrics"
```

## Task A2: Normalization + heuristic helpers (pure, TDD)

**Files:**
- Modify: `service/app/audio/analyzer.py` (add pure helper functions near the existing `normalize_*` helpers)
- Test: `service/app/tests/test_audio_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `service/app/tests/test_audio_metrics.py`:

```python
import numpy as np

from app.audio.analyzer import (
    normalize_onset_rate,
    majorness_from_chroma,
    valence_from_parts,
    clamp01,
)


def test_clamp01():
    assert clamp01(-0.5) == 0.0
    assert clamp01(1.7) == 1.0
    assert clamp01(0.42) == 0.42


def test_normalize_onset_rate():
    assert normalize_onset_rate(0.0) == 0.0
    assert normalize_onset_rate(8.0) == 1.0
    assert normalize_onset_rate(4.0) == 0.5
    assert normalize_onset_rate(20.0) == 1.0  # clamped


def test_valence_from_parts_blend():
    # 0.5*major + 0.3*bpm + 0.2*brightness
    v = valence_from_parts(majorness=1.0, bpm_norm=1.0, brightness_norm=1.0)
    assert abs(v - 1.0) < 1e-9
    v0 = valence_from_parts(majorness=0.0, bpm_norm=0.0, brightness_norm=0.0)
    assert abs(v0 - 0.0) < 1e-9
    vmid = valence_from_parts(majorness=1.0, bpm_norm=0.0, brightness_norm=0.0)
    assert abs(vmid - 0.5) < 1e-9


def test_majorness_from_chroma_major_vs_minor():
    # A clearly C-major-ish chroma (strong C,E,G) should score higher than a minor-ish one (C,Eb,G)
    major = np.zeros(12); major[[0, 4, 7]] = 1.0          # C E G
    minor = np.zeros(12); minor[[0, 3, 7]] = 1.0          # C Eb G
    assert majorness_from_chroma(major) > majorness_from_chroma(minor)
    # output is in [0,1]
    assert 0.0 <= majorness_from_chroma(major) <= 1.0
    assert 0.0 <= majorness_from_chroma(minor) <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_audio_metrics.py -v`
Expected: FAIL — `ImportError` (functions not defined).

- [ ] **Step 3: Implement the pure helpers**

In `service/app/audio/analyzer.py`, add after the existing `normalize_spectral_flatness` function:

```python
def clamp01(x: float) -> float:
    """Clamp to [0, 1]."""
    return float(max(0.0, min(1.0, x)))


def normalize_onset_rate(onsets_per_sec: float, max_rate: float = 8.0) -> float:
    """Normalize onset rate (onsets/sec) to 0-1 over [0, max_rate]."""
    return clamp01(onsets_per_sec / max_rate)


# Krumhansl-Schmuckler key profiles (major and minor), normalized.
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def majorness_from_chroma(chroma_mean: np.ndarray) -> float:
    """Estimate major-vs-minor 'majorness' in [0,1] from a 12-bin mean chroma vector.

    Correlates the (best-rotation) chroma against the major and minor KS profiles
    and returns a softmaxed major share. Heuristic — not a key/mode classifier.
    """
    c = np.asarray(chroma_mean, dtype=float)
    if c.shape[0] != 12 or float(np.sum(np.abs(c))) == 0.0:
        return 0.5
    c = c - c.mean()
    best_major = max(
        float(np.corrcoef(np.roll(c, -k), _KS_MAJOR - _KS_MAJOR.mean())[0, 1]) for k in range(12)
    )
    best_minor = max(
        float(np.corrcoef(np.roll(c, -k), _KS_MINOR - _KS_MINOR.mean())[0, 1]) for k in range(12)
    )
    gap = best_major - best_minor
    if not np.isfinite(gap):  # near-uniform/atonal chroma → corrcoef nan
        return 0.5
    # Map the (major - minor) correlation gap from [-1,1] to [0,1]
    return clamp01(0.5 + 0.5 * gap)


def valence_from_parts(majorness: float, bpm_norm: float, brightness_norm: float) -> float:
    """Heuristic valence (0-1): 0.5*majorness + 0.3*bpm + 0.2*brightness."""
    return clamp01(0.5 * majorness + 0.3 * bpm_norm + 0.2 * brightness_norm)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_audio_metrics.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add service/app/audio/analyzer.py service/app/tests/test_audio_metrics.py
git commit -m "feat(metrics): pure helpers for onset-rate norm, majorness, valence blend"
```

## Task A3: Extend AudioFeatures + extraction + save + load

**Files:**
- Modify: `service/app/audio/analyzer.py` (`AudioFeatures` dataclass, `analyze_audio_file`, `save_audio_features`, `get_audio_features`)

- [ ] **Step 1: Add the new fields to the `AudioFeatures` dataclass**

In `AudioFeatures` (after `flatness_norm: float | None = None`), add:

```python
    # Phase-A metrics (more-metrics)
    valence: float | None = None
    danceability: float | None = None
    pulse_clarity: float | None = None
    onset_rate: float | None = None
    onset_rate_norm: float | None = None
    instrumentalness: float | None = None
    acousticness: float | None = None
    mfcc: list | None = None  # 12 floats
```

- [ ] **Step 2: Compute the new metrics in `analyze_audio_file`**

In `analyze_audio_file`, after the existing `key_estimate` block and before `features = AudioFeatures(`, insert:

```python
        # --- Phase-A metrics (heuristic proxies; see spec) ---
        bpm_n = normalize_bpm(bpm)
        brightness_n = normalize_spectral_centroid(avg_centroid)
        flatness_n = normalize_spectral_flatness(avg_flatness)

        # Onset envelope → rhythmic feel
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
        duration_sec = float(len(y) / sr) if sr else 0.0
        onset_rate = float(len(onsets) / duration_sec) if duration_sec > 0 else 0.0
        onset_rate_n = normalize_onset_rate(onset_rate)

        # Pulse clarity: prominence of the dominant autocorrelation lag of the onset envelope
        if onset_env.size > 1 and float(np.max(onset_env)) > 0:
            ac = librosa.autocorrelate(onset_env)
            ac = ac / (ac[0] + 1e-9)
            pulse_clarity = clamp01(float(np.max(ac[1:])) if ac.size > 1 else 0.0)
        else:
            pulse_clarity = 0.0
        beat_strength = clamp01(float(np.mean(onset_env)) / (float(np.max(onset_env)) + 1e-9)) if onset_env.size else 0.0
        danceability = clamp01(0.6 * pulse_clarity + 0.4 * beat_strength)

        # HPSS → instrumentalness / acousticness proxies
        try:
            y_harm, y_perc = librosa.effects.hpss(y)
            harm_energy = float(np.sum(y_harm ** 2))
            perc_energy = float(np.sum(y_perc ** 2))
            harmonic_ratio = clamp01(harm_energy / (harm_energy + perc_energy + 1e-9))
            S = np.abs(librosa.stft(y_harm))
            freqs = librosa.fft_frequencies(sr=sr)
            vocal_band = (freqs >= 200) & (freqs <= 4000)
            band_energy = float(np.sum(S[vocal_band, :]))
            total_energy = float(np.sum(S)) + 1e-9
            vocal_band_ratio = clamp01(band_energy / total_energy)
            instrumentalness = clamp01(1.0 - vocal_band_ratio)
            acousticness = clamp01(0.5 * harmonic_ratio + 0.3 * (1 - brightness_n) + 0.2 * (1 - flatness_n))
        except Exception:
            instrumentalness = None
            acousticness = None

        # MFCC timbre vector (coeffs 1..12, drop coeff 0 = energy)
        try:
            mfcc_full = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            mfcc_vec = [float(x) for x in np.mean(mfcc_full, axis=1)[1:13]]
        except Exception:
            mfcc_vec = None

        # Valence (heuristic): majorness + tempo + brightness
        try:
            chroma_mean = np.mean(chroma, axis=1)  # `chroma` computed in the key block above
            majorness = majorness_from_chroma(chroma_mean)
        except Exception:
            majorness = 0.5
        valence = valence_from_parts(majorness, bpm_n, brightness_n)
```

NOTE: the existing key block assigns `chroma = librosa.feature.chroma_cqt(...)` inside a `try`. Move the `chroma = ...` assignment so `chroma` is available here even if key naming fails (assign `chroma` before the `key_idx` line; keep it inside the try but reference it defensively as above with its own try/except).

- [ ] **Step 3: Pass the new values into the `AudioFeatures(...)` constructor**

Extend the `features = AudioFeatures(` call with:

```python
            valence=valence,
            danceability=danceability,
            pulse_clarity=pulse_clarity,
            onset_rate=onset_rate,
            onset_rate_norm=onset_rate_n,
            instrumentalness=instrumentalness,
            acousticness=acousticness,
            mfcc=mfcc_vec,
```

- [ ] **Step 4: Persist them in `save_audio_features`**

Add the new columns to both the INSERT column list/placeholders and the `DO UPDATE SET` clause, and add the values to the params tuple (in matching order). Columns to add: `valence, danceability, pulse_clarity, onset_rate, onset_rate_norm, instrumentalness, acousticness, mfcc`. For all except `mfcc` wrap in `to_python_float(...)`; pass `features.mfcc` directly (psycopg2 adapts a Python list to `REAL[]`). Example params additions:

```python
                to_python_float(features.valence),
                to_python_float(features.danceability),
                to_python_float(features.pulse_clarity),
                to_python_float(features.onset_rate),
                to_python_float(features.onset_rate_norm),
                to_python_float(features.instrumentalness),
                to_python_float(features.acousticness),
                features.mfcc,
```

- [ ] **Step 5: Load them in `get_audio_features`**

Add the new columns to the SELECT and map them onto the returned `AudioFeatures(...)` (append in SELECT order after `flatness_norm`).

- [ ] **Step 6: Verify imports + existing tests**

Run: `cd service && .venv-test/bin/python -c "import ast; ast.parse(open('app/audio/analyzer.py').read()); print('parses')" && .venv-test/bin/python -m pytest app/tests/test_audio_metrics.py -v`
Expected: `parses`; tests PASS. (Full `import app.audio.analyzer` needs librosa, which the test venv lacks — `ast.parse` is the gate here. The deployed container import-checks at startup.)

- [ ] **Step 7: Commit**

```bash
git add service/app/audio/analyzer.py
git commit -m "feat(metrics): extract+persist valence/danceability/onset/timbre/instrumentalness"
```

## Task A4: Re-analyze tracks missing the new metrics

**Files:**
- Modify: `service/app/audio/analyzer.py` (`analyze_library` track-selection query)

- [ ] **Step 1: Select tracks lacking the new metrics, not just never-analyzed ones**

In `analyze_library`, change the track-selection SQL so it also re-processes rows where the new metrics are NULL. Replace the `WHERE taf.track_id IS NULL ...` query with:

```python
            cur.execute("""
                SELECT t.id, tf.path
                FROM tracks t
                JOIN track_files tf ON t.id = tf.track_id
                LEFT JOIN track_audio_features taf ON t.id = taf.track_id
                WHERE (taf.track_id IS NULL OR taf.valence IS NULL OR taf.mfcc IS NULL)
                AND tf.path IS NOT NULL
                AND tf.missing_since IS NULL
            """)
```

This makes the audio step backfill the new metrics over the existing ~12.7k analyzed tracks (re-analysis). `save_audio_features` already upserts.

- [ ] **Step 2: Verify it parses**

Run: `cd service && .venv-test/bin/python -c "import ast; ast.parse(open('app/audio/analyzer.py').read()); print('parses')"`
Expected: `parses`.

- [ ] **Step 3: Commit**

```bash
git add service/app/audio/analyzer.py
git commit -m "feat(metrics): re-analyze tracks missing the new audio metrics"
```

---

# PHASE B — Valence as the 6th trajectory dimension (eval-gated)

> Implementer: read `service/app/trajectory/intent.py`, `curves.py`, and `candidates.py` first. Follow the EXACT pattern the existing `darkness` dimension uses — valence is added everywhere `darkness` appears, with the parsing/semantics below. Where a step says "mirror darkness," produce the analogous code for valence.

## Task B1: Valence on the trajectory waypoint + weights + parsing

**Files:**
- Modify: `service/app/trajectory/intent.py`
- Test: `service/app/tests/test_valence_intent.py`

- [ ] **Step 1: Write failing tests for valence prompt parsing**

Create `service/app/tests/test_valence_intent.py`:

```python
from app.trajectory.intent import parse_valence_target


def test_uplifting_is_high():
    assert parse_valence_target("uplifting euphoric summer anthems") >= 0.75


def test_melancholic_is_low():
    assert parse_valence_target("bleak melancholic doom") <= 0.25


def test_neutral_default():
    assert parse_valence_target("instrumental focus music") == 0.5
```

- [ ] **Step 2: Run to verify fail**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_valence_intent.py -v`
Expected: FAIL (`parse_valence_target` undefined).

- [ ] **Step 3: Implement `parse_valence_target` + add `valence` to the waypoint and DimensionWeights**

In `intent.py`:
1. Add a module-level helper:

```python
_VALENCE_HIGH = ("uplifting", "euphoric", "joyful", "happy", "triumphant", "anthemic",
                 "feel good", "feel-good", "sunny", "celebratory", "ecstatic")
_VALENCE_LOW = ("melancholic", "melancholy", "bleak", "sad", "depressive", "somber",
                "mournful", "gloomy", "desolate", "miserable", "dark and sad")


def parse_valence_target(prompt: str) -> float:
    """Map mood words in the prompt to a valence target in [0,1]; 0.5 = neutral."""
    p = prompt.lower()
    high = any(w in p for w in _VALENCE_HIGH)
    low = any(w in p for w in _VALENCE_LOW)
    if high and not low:
        return 0.85
    if low and not high:
        return 0.15
    return 0.5
```

2. Add `valence: float = 0.5` to the trajectory waypoint dataclass (mirror the `darkness` field).
3. Add a `valence` weight to `DimensionWeights` (mirror `darkness`), include it in the normalization/clamp logic exactly as the other core dims, and set its default to 0.0 (no influence unless a mood word was detected — see B2).

- [ ] **Step 4: Run tests to pass**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_valence_intent.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add service/app/trajectory/intent.py service/app/tests/test_valence_intent.py
git commit -m "feat(valence): parse mood→valence target; valence on waypoint + weights"
```

## Task B2: Wire valence target into intent construction + curve

**Files:**
- Modify: `service/app/trajectory/intent.py` (where the prompt is parsed into waypoints/weights)
- Modify: `service/app/trajectory/curves.py` (per-position curve eval)

- [ ] **Step 1: Set the valence waypoint + weight from the prompt**

Where intent parsing builds the waypoint(s) and `DimensionWeights`, call `parse_valence_target(prompt)`. If the result != 0.5, set the waypoint `valence` to it and give the valence weight a modest share (set valence weight to `0.10`, then renormalize the weight set as the existing code already does for the core dims). If the result == 0.5, leave valence weight at 0.0 (valence does not influence selection when no mood was expressed). Mirror exactly how `darkness` target+weight are set.

- [ ] **Step 2: Add valence to the per-position curve**

In `curves.py`, wherever the curve produces a per-position target tuple/struct containing energy/tempo/darkness/texture(/era), add `valence` alongside, evaluated the same way (mirror `darkness`). If a single steady target is used, propagate the waypoint valence to every position; if arcs are supported per-dimension, support a valence arc identically to darkness.

- [ ] **Step 3: Verify parse**

Run: `cd service && .venv-test/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ['app/trajectory/intent.py','app/trajectory/curves.py']]; print('parses')"`
Expected: `parses`.

- [ ] **Step 4: Commit**

```bash
git add service/app/trajectory/intent.py service/app/trajectory/curves.py
git commit -m "feat(valence): drive valence waypoint+weight and per-position curve"
```

## Task B3: Score valence in candidates + carry it from audio

**Files:**
- Modify: `service/app/trajectory/candidates.py`

- [ ] **Step 1: Add `valence` to `CandidateTrack`**

In the `CandidateTrack` dataclass, in the "Profile (4D)" block, add:

```python
    valence: float = 0.5  # audio-derived mood (track_audio_features.valence), 0.5 = neutral
```

- [ ] **Step 2: Load valence from `track_audio_features` in the candidate SQL**

In the candidate-building SQL (the `semantic_search`/`keyword_search` queries that LEFT JOIN `track_audio_features` and read `bpm_norm, loudness_norm, brightness_norm`), add `taf.valence` to the SELECT and populate `CandidateTrack.valence` with `COALESCE(taf.valence, 0.5)`. Follow the exact pattern used for `bpm_norm`.

- [ ] **Step 3: Add a valence distance term to `trajectory_score`**

Wherever `trajectory_score` is computed from the per-position target vs the track's energy/tempo/darkness/texture (the distance computation), include `valence` using the per-position valence target and `track.valence`, weighted by the valence dimension weight — mirror the existing `darkness` term EXACTLY (same distance form, same weight source). If no valence weight is set (0.0), the term contributes nothing.

- [ ] **Step 4: Add valence to `get_adaptive_weights`**

In `get_adaptive_weights`, add a valence entry to each prompt-type weight set, defaulting to a small share consistent with the others (the per-prompt valence influence is governed by the dimension weight from B2; keep the candidate-scoring `_w_*` set summing as before by giving valence a modest weight and renormalizing). Read the function first and keep the existing sums balanced.

- [ ] **Step 5: Verify parse + existing tests**

Run: `cd service && .venv-test/bin/python -c "import ast; ast.parse(open('app/trajectory/candidates.py').read()); print('parses')" && .venv-test/bin/python -m pytest app/tests -q`
Expected: `parses`; existing tests PASS.

- [ ] **Step 6: Commit**

```bash
git add service/app/trajectory/candidates.py
git commit -m "feat(valence): score valence distance; carry valence from audio features"
```

## Task B4: Valence continuity in the sequencer

**Files:**
- Modify: `service/app/trajectory/sequencer.py` (`score_transition`, and `CandidateTrack` is shared so `valence` is available)

- [ ] **Step 1: Add a valence continuity term**

In `score_transition` (sequencer.py), after the darkness-continuity block (~line 262), add a valence continuity term mirroring darkness (arc-unaware is fine — use the tempo-style form):

```python
    # Valence continuity (mood smoothness)
    valence_diff = abs(getattr(prev_track, "valence", 0.5) - getattr(curr_track, "valence", 0.5))
    scores.append(max(0.0, 1.0 - min(valence_diff * 1.8, 1.0)))
```

- [ ] **Step 2: Verify parse**

Run: `cd service && .venv-test/bin/python -c "import ast; ast.parse(open('app/trajectory/sequencer.py').read()); print('parses')"`
Expected: `parses`.

- [ ] **Step 3: Commit**

```bash
git add service/app/trajectory/sequencer.py
git commit -m "feat(valence): mood-continuity term in transition scoring"
```

## Task B5: EVAL GATE — Phase B

**This is a manual checkpoint, run by the controller after re-analysis has populated valence.** Not a code task.

- [ ] Rebuild + deploy, ensure `track_audio_features.valence` is populated (Phase A re-analysis done), then run `./eval_loop.py --multi --max-iter 2` (per the `eval-changes` skill) against the running app. Compare to the historical baseline. Keep if neutral-or-better (especially on mood/arc prompts); revert B commits if it regresses. Record the result in the eval log.

---

# PHASE C — Rhythmic + timbre/vocal continuity (eval-gated)

## Task C1: Carry the rhythmic/timbre fields onto candidates

**Files:**
- Modify: `service/app/trajectory/candidates.py`

- [ ] **Step 1: Add fields to `CandidateTrack`**

In the "Acoustic features" block of `CandidateTrack` (next to `bpm_norm`), add:

```python
    danceability: float | None = None
    pulse_clarity: float | None = None
    instrumentalness: float | None = None
    acousticness: float | None = None
    mfcc: list | None = None  # 12 floats
```

- [ ] **Step 2: Load them from `track_audio_features`**

In the candidate-building SQL that already reads `taf.bpm_norm, taf.loudness_norm, taf.brightness_norm`, add `taf.danceability, taf.pulse_clarity, taf.instrumentalness, taf.acousticness, taf.mfcc` and populate the new `CandidateTrack` fields (raw values; leave NULL as None). Mirror the `bpm_norm` wiring exactly.

- [ ] **Step 3: Verify parse + tests**

Run: `cd service && .venv-test/bin/python -c "import ast; ast.parse(open('app/trajectory/candidates.py').read()); print('parses')" && .venv-test/bin/python -m pytest app/tests -q`
Expected: `parses`; tests PASS.

- [ ] **Step 4: Commit**

```bash
git add service/app/trajectory/candidates.py
git commit -m "feat(continuity): carry danceability/pulse/timbre/instrumentalness onto candidates"
```

## Task C2: Rhythmic + timbre + vocal terms in the sequencer (pure fn, TDD)

**Files:**
- Modify: `service/app/trajectory/sequencer.py`
- Test: `service/app/tests/test_continuity_terms.py`

- [ ] **Step 1: Write failing tests for the pure continuity helper**

Create `service/app/tests/test_continuity_terms.py`:

```python
from app.trajectory.sequencer import mfcc_continuity, vocal_jump_score


def test_mfcc_continuity_identical_is_high():
    v = [1.0, 2.0, 3.0] + [0.0] * 9
    assert mfcc_continuity(v, v) > 0.95


def test_mfcc_continuity_far_is_low():
    a = [0.0] * 12
    b = [50.0] * 12
    assert mfcc_continuity(a, b) < 0.2


def test_mfcc_continuity_missing_returns_none():
    assert mfcc_continuity(None, [0.0] * 12) is None


def test_vocal_jump_score():
    # same instrumentalness → smooth (high)
    assert vocal_jump_score(0.9, 0.9) > 0.95
    # vocal↔instrumental whiplash → low
    assert vocal_jump_score(0.05, 0.95) < 0.3
    assert vocal_jump_score(None, 0.5) is None
```

- [ ] **Step 2: Run to verify fail**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_continuity_terms.py -v`
Expected: FAIL (functions undefined).

- [ ] **Step 3: Implement the pure helpers + wire into `score_transition`**

In `sequencer.py`, add module-level pure helpers (near `cosine_similarity`):

```python
def mfcc_continuity(prev_mfcc, curr_mfcc, scale: float = 60.0):
    """0-1 timbre continuity from euclidean distance between 12-d MFCC means.
    Returns None when either vector is missing."""
    if not prev_mfcc or not curr_mfcc:
        return None
    import numpy as _np
    d = float(_np.linalg.norm(_np.asarray(prev_mfcc, float) - _np.asarray(curr_mfcc, float)))
    return max(0.0, 1.0 - min(d / scale, 1.0))


def vocal_jump_score(prev_instr, curr_instr):
    """0-1 score penalizing vocal↔instrumental whiplash. None if data missing."""
    if prev_instr is None or curr_instr is None:
        return None
    return max(0.0, 1.0 - min(abs(prev_instr - curr_instr) * 1.5, 1.0))
```

Then, inside `score_transition`, extend the acoustic-continuity block. Replace the existing acoustic block (~lines 324-334) so it also folds in the new terms when present:

```python
    # Acoustic continuity (only when both tracks have core audio features)
    if (
        prev_track.bpm_norm is not None and curr_track.bpm_norm is not None
        and prev_track.loudness_norm is not None and curr_track.loudness_norm is not None
        and prev_track.brightness_norm is not None and curr_track.brightness_norm is not None
    ):
        bpm_score = 1.0 - min(abs(prev_track.bpm_norm - curr_track.bpm_norm) * 2, 1.0)
        loudness_score = 1.0 - min(abs(prev_track.loudness_norm - curr_track.loudness_norm) * 2, 1.0)
        brightness_score = 1.0 - min(abs(prev_track.brightness_norm - curr_track.brightness_norm) * 2, 1.0)
        acoustic_parts = [(bpm_score, 0.35), (loudness_score, 0.30), (brightness_score, 0.15)]

        dprev, dcurr = getattr(prev_track, "danceability", None), getattr(curr_track, "danceability", None)
        if dprev is not None and dcurr is not None:
            acoustic_parts.append((1.0 - min(abs(dprev - dcurr) * 2, 1.0), 0.10))
        pprev, pcurr = getattr(prev_track, "pulse_clarity", None), getattr(curr_track, "pulse_clarity", None)
        if pprev is not None and pcurr is not None:
            acoustic_parts.append((1.0 - min(abs(pprev - pcurr) * 2, 1.0), 0.05))
        mc = mfcc_continuity(getattr(prev_track, "mfcc", None), getattr(curr_track, "mfcc", None))
        if mc is not None:
            acoustic_parts.append((mc, 0.10))
        vj = vocal_jump_score(getattr(prev_track, "instrumentalness", None), getattr(curr_track, "instrumentalness", None))
        if vj is not None:
            acoustic_parts.append((vj, 0.10))

        wsum = sum(w for _, w in acoustic_parts)
        acoustic_score = sum(s * w for s, w in acoustic_parts) / wsum
        scores.append(acoustic_score)
```

- [ ] **Step 4: Run tests to pass**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_continuity_terms.py -v && .venv-test/bin/python -c "import ast; ast.parse(open('app/trajectory/sequencer.py').read()); print('parses')"`
Expected: tests PASS; `parses`.

- [ ] **Step 5: Commit**

```bash
git add service/app/trajectory/sequencer.py service/app/tests/test_continuity_terms.py
git commit -m "feat(continuity): rhythmic + MFCC timbre + vocal-jump terms in transitions"
```

## Task C3: EVAL GATE — Phase C

**Manual checkpoint (controller), after re-analysis populated the metrics.** Not a code task.

- [ ] Rebuild/deploy, confirm `danceability/mfcc/instrumentalness` populated, run `./eval_loop.py --multi --max-iter 2`. Keep if neutral-or-better on transition smoothness / overall; revert C commits if it regresses. Record result.

---

# PHASE D — Studio preference (metadata-only, prompt-aware, eval-gated)

## Task D1: Pure version classifier (TDD)

**Files:**
- Create: `service/app/ingestion/version_classifier.py`
- Test: `service/app/tests/test_version_classifier.py`

- [ ] **Step 1: Write failing tests**

Create `service/app/tests/test_version_classifier.py`:

```python
from app.ingestion.version_classifier import classify_version


def test_plain_studio():
    vt, score = classify_version("Paranoid", "Paranoid", [])
    assert vt == "studio"
    assert score == 1.0


def test_live_in_title():
    vt, score = classify_version("War Pigs (Live)", "Paranoid", [])
    assert vt == "live"
    assert score < 0.5


def test_live_at():
    vt, _ = classify_version("Children of the Grave - Live at Last", "Live at Last", [])
    assert vt == "live"


def test_demo():
    vt, score = classify_version("Snowblind (Demo)", "The Vol 4 Sessions", [])
    assert vt == "demo"
    assert score < 0.6


def test_bonus_and_alternate():
    assert classify_version("Track X (Bonus Track)", "Album", [])[0] == "bonus"
    assert classify_version("Track X (Alternate Take)", "Album", [])[0] == "alternate"


def test_acoustic_and_remix():
    assert classify_version("Track (Acoustic Version)", "Album", [])[0] == "acoustic"
    assert classify_version("Track (Club Remix)", "Album", [])[0] == "remix"


def test_mb_secondary_type_live():
    vt, score = classify_version("Some Song", "Some Album", ["Live"])
    assert vt == "live"


def test_clean_title_with_parenthetical_non_version():
    # parentheticals that are not version markers stay studio
    vt, score = classify_version("Hello (feat. Friend)", "Album", [])
    assert vt == "studio"
    assert score == 1.0
```

- [ ] **Step 2: Run to verify fail**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_version_classifier.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the classifier**

Create `service/app/ingestion/version_classifier.py`:

```python
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


def classify_version(track_title: str, album_title: str, mb_secondary_types: list[str] | None = None):
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
```

- [ ] **Step 4: Run tests to pass**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_version_classifier.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add service/app/ingestion/version_classifier.py service/app/tests/test_version_classifier.py
git commit -m "feat(studio): pure version classifier (studio/live/demo/bonus/...)"
```

## Task D2: Storage table + backfill

**Files:**
- Create: `service/app/migrations/014_track_studio_scores.sql`
- Modify: `service/app/database_pg.py` (`init_database`)
- Create: `service/app/ingestion/studio_scores.py` (backfill routine)

- [ ] **Step 1: Migration + init_database table**

Create `service/app/migrations/014_track_studio_scores.sql`:

```sql
-- 014_track_studio_scores.sql — studio-vs-live version scoring (Phase D)
CREATE TABLE IF NOT EXISTS track_studio_scores (
    track_id     UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    version_type TEXT,
    studio_score REAL,
    computed_at  TIMESTAMPTZ DEFAULT now()
);
```

Add the identical `CREATE TABLE IF NOT EXISTS track_studio_scores (...)` to `init_database()` (after the `track_audio_features` block).

- [ ] **Step 2: Backfill routine**

Create `service/app/ingestion/studio_scores.py`:

```python
"""Populate track_studio_scores from track + album titles using the pure classifier."""

import logging

from app.database_pg import get_connection
from app.ingestion.version_classifier import classify_version

logger = logging.getLogger(__name__)


def backfill_studio_scores() -> dict[str, int]:
    """Classify every track's version and upsert into track_studio_scores."""
    stats = {"processed": 0}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t.id, t.title, COALESCE(al.title, '')
                FROM tracks t
                LEFT JOIN track_albums ta ON ta.track_id = t.id
                LEFT JOIN albums al ON al.id = ta.album_id
            """)
            rows = cur.fetchall()
            for track_id, title, album_title in rows:
                vtype, score = classify_version(title or "", album_title or "", [])
                cur.execute("""
                    INSERT INTO track_studio_scores (track_id, version_type, studio_score, computed_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (track_id) DO UPDATE
                        SET version_type = EXCLUDED.version_type,
                            studio_score = EXCLUDED.studio_score,
                            computed_at = now()
                """, (track_id, vtype, score))
                stats["processed"] += 1
        conn.commit()
    logger.info("Studio-score backfill complete: %s", stats)
    return stats
```

Verify the join table/column names against `database_pg.py` (`track_albums`, `albums`) before finalizing; adjust to the real schema if they differ.

- [ ] **Step 3: Verify parse + tests**

Run: `cd service && .venv-test/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ['app/database_pg.py','app/ingestion/studio_scores.py']]; print('parses')" && .venv-test/bin/python -m pytest app/tests/test_version_classifier.py -q`
Expected: `parses`; tests PASS.

- [ ] **Step 4: Commit**

```bash
git add service/app/migrations/014_track_studio_scores.sql service/app/database_pg.py service/app/ingestion/studio_scores.py
git commit -m "feat(studio): track_studio_scores table + backfill routine"
```

## Task D3: Apply studio preference in scoring + dedup + prompt-awareness

**Files:**
- Modify: `service/app/trajectory/intent.py` (prefer_live flag)
- Modify: `service/app/trajectory/candidates.py` (load studio_score, penalty, dedup tie-breaker)

- [ ] **Step 1: prefer_live prompt flag (TDD)**

Add to `service/app/tests/test_valence_intent.py` (same file, new tests):

```python
from app.trajectory.intent import detect_prefer_live


def test_prefer_live_detected():
    assert detect_prefer_live("the best live concert recordings") is True
    assert detect_prefer_live("acoustic unplugged sessions") is True


def test_prefer_live_default_false():
    assert detect_prefer_live("dark ambient studio focus") is False
```

In `intent.py` add:

```python
_PREFER_LIVE = ("live", "concert", "unplugged", "acoustic session", "in concert", "live album")


def detect_prefer_live(prompt: str) -> bool:
    p = prompt.lower()
    return any(w in p for w in _PREFER_LIVE)
```

Expose the result on the parsed intent object (mirror an existing boolean flag on the intent). Run the test to fail→pass.

- [ ] **Step 2: Load studio_score onto candidates**

Add `studio_score: float = 1.0` and `version_type: str = "studio"` to `CandidateTrack`. In the candidate SQL, `LEFT JOIN track_studio_scores tss ON tss.track_id = t.id` and select `COALESCE(tss.studio_score, 1.0)`, `COALESCE(tss.version_type, 'studio')`. Mirror the existing optional-join pattern.

- [ ] **Step 3: Apply the soft penalty (prompt-aware)**

Add `_w_studio: float = 0.08` to `CandidateTrack`'s adaptive weights and to `get_adaptive_weights`. In the total-score computation, subtract `(1.0 - track.studio_score) * track._w_studio` — UNLESS `intent.prefer_live` is set, in which case invert: subtract `track.studio_score * track._w_studio` (penalize studio so live/acoustic float up). Follow the exact subtraction style of the existing penalties (e.g. `usage_penalty`).

- [ ] **Step 4: Dedup tie-breaker**

In the near-duplicate collapse (the existing live/demo/remix dedup in the candidate pool — locate by searching candidates.py for the dedup/`near`/collapse logic), when choosing which of several same-song versions to keep, prefer the one with the highest `studio_score` (unless `intent.prefer_live`, then lowest). If the dedup currently keeps "first" or "highest semantic," add `studio_score` as the primary/secondary key per that comparison.

- [ ] **Step 5: Verify parse + tests**

Run: `cd service && .venv-test/bin/python -c "import ast; ast.parse(open('app/trajectory/candidates.py').read()); print('parses')" && .venv-test/bin/python -m pytest app/tests -q`
Expected: `parses`; tests PASS.

- [ ] **Step 6: Commit**

```bash
git add service/app/trajectory/intent.py service/app/trajectory/candidates.py service/app/tests/test_valence_intent.py
git commit -m "feat(studio): prompt-aware studio penalty + dedup tie-breaker"
```

## Task D4: EVAL GATE — Phase D

**Manual checkpoint (controller). No re-analysis dependency (metadata only) — just the studio-score backfill.** Not a code task.

- [ ] Rebuild/deploy, run the studio-score backfill, then `./eval_loop.py --multi --max-iter 2`. Confirm studio tracks are favored and live/acoustic prompts still surface live cuts. Keep if neutral-or-better; revert D commits if it regresses. Record result.

---

# Finalization

## Task Z1: Docs

**Files:** `AGENTS.md`, `README.md`, `CLAUDE.md`

- [ ] **Step 1:** Update `AGENTS.md` (V4 Scoring: valence 6th dimension, new continuity terms, studio weight; new tables `track_studio_scores` + new `track_audio_features` columns; new cli/backfill steps), `README.md` (metrics/dimensions list), `CLAUDE.md` (Important Files: `version_classifier.py`, `studio_scores.py`; gotcha that valence/instrumentalness/acousticness are heuristic proxies and that adding audio metrics requires a full re-analysis). Then:

```bash
git add AGENTS.md README.md CLAUDE.md
git commit -m "docs(metrics): document valence dimension, continuity terms, studio preference"
```

## Task Z2: Full verification

- [ ] **Step 1:** `cd service && .venv-test/bin/python -m pytest app/tests -q` → all pass.
- [ ] **Step 2:** `cd service && .venv-test/bin/ruff check app/audio/analyzer.py app/ingestion/version_classifier.py app/ingestion/studio_scores.py app/trajectory/sequencer.py app/trajectory/candidates.py app/trajectory/intent.py app/trajectory/curves.py` → clean (fix any lint in the files this plan created/modified; ignore pre-existing issues in untouched code).
- [ ] **Step 3 (controller):** Rebuild + deploy, apply migrations 013 + 014, kick off audio re-analysis (`analyze_library`) + studio-score backfill as background jobs. Run the B/C/D eval gates once data is populated.
- [ ] **Step 4:** Remove the throwaway venv: `rm -rf service/.venv-test`.

---

## Cross-phase notes

- **Re-analysis is the long pole.** B and C are inert until `track_audio_features` is repopulated with the new metrics (hours). D works as soon as its backfill runs (minutes).
- **Graceful degradation everywhere:** every new scoring/continuity term must no-op when its data is NULL (None checks shown). A track with no audio metrics scores exactly as it does today.
- **Eval discipline:** B/C/D are independent commits ranges; if one phase regresses in eval, revert just that phase's commits without touching the others.
