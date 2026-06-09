# More Metrics for Goated Playlists — Design

**Date:** 2026-06-09
**Status:** Approved (design); pending implementation plan
**Branch:** `more-metrics`

## Problem

Playlist quality is limited by how few signals describe each track. The audio analyzer extracts only bpm, loudness(RMS), spectral centroid, spectral flatness, dynamic range, and key — and only 4 of those feed scoring (`as_vector()` = bpm/loudness/brightness/flatness); key is computed and discarded. The 4 trajectory dimensions (energy/tempo/darkness/texture) come from genre-keyword heuristics, there is no mood axis, transitions ignore rhythmic feel and timbre, and there is no preference for studio recordings over live/demo/bonus versions. This spec adds more metrics and wires the high-value ones into scoring and sequencing.

## Scope (4 phases, built in order, one continuous effort)

- **A. Metric extraction** — compute & store new audio metrics. No consumer changes → zero quality risk, no eval.
- **B. Valence as the 6th trajectory dimension** — prompt-steerable mood. Eval-gated.
- **C. Rhythmic + timbre/vocal continuity** — richer transition smoothing. Eval-gated.
- **D. Studio preference** — favor studio cuts over live/demo/bonus (metadata-only, prompt-aware). Eval-gated.

## Non-Goals

- Harmonic mixing (musical key/Camelot) — explicitly deferred by the owner.
- Spotify-grade accuracy for valence/instrumentalness/acousticness — these are **documented heuristic proxies**, not ground-truth labels.
- Hard-excluding live/demo tracks — D is a soft, prompt-aware preference, never a hard filter.

## Decisions (from brainstorming)

- Metrics to add: mood/valence, rhythmic feel, timbre & vocals (NOT harmonic mixing).
- Valence depth: **full 6th trajectory dimension** (prompt-controllable + continuity), not continuity-only.
- Studio preference: **soft penalty + dedup tie-breaker, prompt-aware** (inverts on live/acoustic prompts); never a hard filter.
- Order A→B→C→D; each scoring phase (B/C/D) gets its own `eval_loop.py --multi` keep/revert gate.

## Time-cost reality (acknowledged)

- Phase A re-analysis over ~12.7k tracks is **hours** of librosa CPU (background job in-container).
- Eval runs are ~25 min each and only meaningful **after** re-analysis populates the data, and require an image rebuild to test the algorithm changes.
- Therefore: code for A/B/C/D is built, unit-tested, committed, and deployed in one go, and the re-analysis is kicked off; the **eval keep/revert decisions for B/C run after re-analysis completes**. D's eval does not depend on re-analysis (metadata-only).

---

## Phase A — Metric extraction

### New metrics (all via librosa, in `audio/analyzer.py`)

Added to the `AudioFeatures` dataclass, computed in `analyze_audio_file()`, persisted in `save_audio_features()`:

| Field | Range | Derivation (heuristic where noted) |
|---|---|---|
| `valence` | 0–1 | **Heuristic.** `0.5*mode_majorness + 0.3*bpm_norm + 0.2*brightness_norm`, where `mode_majorness` = correlation of the chroma profile against the Krumhansl–Schmuckler major template minus the minor template, rescaled to 0–1. |
| `danceability` | 0–1 | **Heuristic.** `0.6*pulse_clarity + 0.4*beat_strength`, beat_strength = mean onset-envelope value at detected beats, normalized. |
| `pulse_clarity` | 0–1 | Normalized prominence of the dominant lag in the onset-envelope autocorrelation (beat steadiness). |
| `onset_rate` | onsets/sec | `len(librosa.onset.onset_detect(...)) / duration_sec`. |
| `onset_rate_norm` | 0–1 | `onset_rate` clamped/scaled over [0, 8] onsets/sec. |
| `mfcc` | 12 floats | Mean over time of `librosa.feature.mfcc(n_mfcc=13)` coeffs 1–12 (drop coeff 0 = energy). Stored raw as Postgres `REAL[]`. |
| `instrumentalness` | 0–1 | **Heuristic.** `1 - vocal_band_ratio`, vocal_band_ratio = harmonic energy in 200–4000 Hz / total harmonic energy (HPSS harmonic component). |
| `acousticness` | 0–1 | **Heuristic.** `clamp(0.5*harmonic_ratio + 0.3*(1-brightness_norm) + 0.2*(1-flatness_norm))`, harmonic_ratio from HPSS. |

`valence_norm` is unnecessary (valence already 0–1). Existing `loudness_lufs` column stays as-is (out of scope to populate now).

### Data layer

- Migration `service/app/migrations/013_audio_metrics_v2.sql`: `ALTER TABLE track_audio_features ADD COLUMN IF NOT EXISTS …` for each new column (`valence REAL, danceability REAL, pulse_clarity REAL, onset_rate REAL, onset_rate_norm REAL, instrumentalness REAL, acousticness REAL, mfcc REAL[]`).
- `database_pg.py` `init_database()`: add the same columns to the `track_audio_features` CREATE TABLE (so fresh DBs include them).

### Consumption

**None in Phase A.** `as_vector()` is left unchanged; the new columns are written but not yet read by scoring/sequencing. A new accessor (`AudioFeatures.continuity_vector()` / explicit field reads) is introduced in Phase C, not A.

### Re-analysis

`cli_v3` audio step / `analyze_library()` re-processes the library to populate the new columns. `analyze_library()` must re-analyze tracks whose new columns are NULL (add a `--force`/`--missing-metrics` selection) rather than only never-analyzed tracks. Long-running background job.

---

## Phase B — Valence as the 6th trajectory dimension

- `trajectory/intent.py`: add `valence: float = 0.5` to the trajectory waypoint; add a valence entry to `DimensionWeights` with its normalization clamp (treat like a core dim). Prompt parsing maps mood words → valence target/movement: euphoric/uplifting/joyful/triumphant → high (~0.85); melancholic/bleak/sad/depressive/somber → low (~0.15); bittersweet/wistful → mid (~0.5) with movement (e.g. a FALL or WAVE). Default 0.5 (no preference) when no mood words present.
- `trajectory/curves.py`: evaluate a valence curve per position alongside energy/tempo/darkness/texture (supports arcs like "bittersweet journey").
- `trajectory/candidates.py`: `trajectory_score` gains a valence-distance term. Valence per track is read from `track_audio_features.valence` (audio-derived — **not** `track_profiles`), fallback 0.5 when no audio row. Add valence to `get_adaptive_weights()` and rebalance (renormalize existing weights so the sum is preserved; valence weight modest, e.g. 0.08–0.12, scaled by whether the prompt expressed mood).
- `trajectory/sequencer.py`: add a valence continuity term to `score_transition()` (diff-based, arc-aware like darkness).
- **Eval gate:** `eval_loop.py --multi`; keep/revert per baseline.

---

## Phase C — Rhythmic + timbre/vocal continuity

- `trajectory/sequencer.py` `score_transition()`: extend the "acoustic continuity" block (currently bpm/loudness/brightness, gated on those three present) to also include, when available:
  - **danceability** + **pulse_clarity** continuity (diff-based, `1 - min(diff*k, 1)`).
  - **MFCC timbre distance** — euclidean distance between the two 12-d mfcc vectors, scaled to a 0–1 continuity score.
  - **instrumental↔vocal jump penalty** — large `|instrumentalness_prev - instrumentalness_curr|` lowers the score (avoid vocal→instrumental whiplash).
  - **acousticness** continuity.
  Rebalance the acoustic-continuity sub-weights so the block stays in [0,1] and no single term dominates; keep graceful degradation when fields are NULL.
- `trajectory/candidates.py`: add the new columns to the `track_audio_features` SELECT/JOIN in `semantic_search()`/`keyword_search()` so candidates carry `danceability, pulse_clarity, mfcc, instrumentalness, acousticness` into the sequencer.
- **Eval gate:** `eval_loop.py --multi`; keep/revert per baseline.

---

## Phase D — Studio preference (metadata-only, prompt-aware)

- Pure classifier `classify_version(track_title, album_title, mb_secondary_types)` → `(version_type, studio_score)`:
  - `version_type ∈ {studio, live, demo, bonus, alternate, remix, acoustic, session}`; `studio_score ∈ [0,1]` (1.0 = clean studio).
  - Title regex cues: `\blive\b`, `live at|live in`, `\bdemo\b`, `bonus track`, `alternate (take|version|mix)`, `rehearsal`, `\bsession(s)?\b`, `acoustic version|unplugged`, `\bremix\b`, `radio edit`. MB release-group secondary types (Live/Demo/Compilation/Remix) enhance the score when present (currently sparse, so title is primary). Reuse the existing reissue/version regex patterns where sensible.
- Storage: new table `track_studio_scores(track_id UUID PK, version_type TEXT, studio_score REAL)` + migration `014_track_studio_scores.sql`; populated by a new ingestion/backfill step (`cli_v3` step `studio_scores`) and at scan time. Pure classifier → unit-testable independent of DB.
- `trajectory/intent.py`: detect prompt cues (live/acoustic/unplugged/demo/session) → a `prefer_live: bool` flag.
- `trajectory/candidates.py`: subtract `(1 - studio_score) * _w_studio` from `total_score` (a new small weight). When `intent.prefer_live` is set, invert (penalize studio / reward the requested version type instead). Read `studio_score` via JOIN on `track_studio_scores`, default 1.0 when absent.
- Near-duplicate dedup (the existing live/demo/remix collapse): when collapsing versions of the same song, prefer the candidate with the higher `studio_score` (tie-breaker), unless `prefer_live`.
- **Eval gate:** `eval_loop.py --multi`; keep/revert per baseline.

---

## Error handling

- Analyzer: any per-metric librosa failure logs a warning and leaves that field NULL; the track still saves its other features. Missing metrics degrade gracefully everywhere (continuity terms skip NULL fields; trajectory/studio terms fall back to neutral defaults).
- Migrations use `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` — safe to re-run.
- Scoring terms must never raise on partial data; absence of a signal means "no opinion," not a penalty.

## Testing

- **pytest (pure logic):** valence/danceability/acousticness normalization & assembly; `classify_version` (table of titles → expected type/score); intent valence parsing + `prefer_live` detection; curve valence evaluation; transition continuity term math (synthetic feature dicts). Synthetic-signal sanity for `onset_rate`/`mfcc` shape.
- **Eval (`eval_loop.py --multi`):** one run after each of B, C, D; interpret against the historical baseline; keep/revert/iterate per the eval-changes decision tree. B and C require re-analysis to have populated the audio metrics first.

## Documentation (same commits)

Per repo Documentation Freshness Policy: `AGENTS.md` (V4 Scoring section: new dimension, continuity terms, studio weight; new tables; new cli step), `README.md` (metrics/dimensions), `CLAUDE.md` (Important Files + a gotcha on the heuristic nature + re-analysis requirement), and the migration list.

## Rollout

1. Apply migrations `013` + `014` to the live DB.
2. Deploy A/B/C/D code (`docker compose up -d --build playlist-generator`).
3. Kick off re-analysis (`cli_v3` audio --missing-metrics) + studio_scores backfill — background, hours for audio.
4. After re-analysis: run `eval_loop.py --multi` to validate B and C; run D's eval (no re-analysis dependency). Keep or revert each phase per its eval result.
