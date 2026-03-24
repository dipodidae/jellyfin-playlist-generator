---
name: eval-changes
description: Evaluate playlist generation quality after code changes to the scoring pipeline, trajectory engine, or genre manifold. Use when asked to validate, test, or benchmark changes to service/app/trajectory/ or service/app/genre/. Provides full eval loop, result interpretation, diagnosis mapping, and concrete improvement patterns.
---

# Playlist Generator — Eval & Improve Skill

## When to use this skill

Invoke when:
- Code has changed in `service/app/trajectory/` (candidates, sequencer, composer, intent, curves, gravity)
- Code has changed in `service/app/genre/` (manifold, GMS)
- The user asks to "evaluate", "benchmark", "validate", or "test" a change
- A new system improvement loop iteration is needed
- Scores need comparing across runs

## System context

The eval tool is `eval_loop.py` at the project root. It uses OpenAI GPT-4o to score generated playlists across 5 dimensions (0–10 each):

| Dimension | Weight | Measures |
|-----------|--------|----------|
| `arc` | 0.20 | Energy/mood arc follows requested shape |
| `genre` | 0.25 | Tracks match requested genre(s) |
| `transition` | 0.20 | Smooth, intentional track-to-track flow |
| `fidelity` | 0.20 | Respects explicit constraints (avoid X, length, era) |
| `curation` | 0.15 | Depth, intentionality, not obvious safe picks |

**Weighted overall** = `arc*0.20 + genre*0.25 + transition*0.20 + fidelity*0.20 + curation*0.15`

## Evaluation procedure

### Step 1 — Restart backend
```bash
systemctl --user restart playlist-generator-backend
sleep 30 && curl -s http://localhost:8000/health
```
Health response must be `{"status":"ok",...}`. If not, wait another 20s and retry once.

### Step 2 — Run multi-prompt batch eval
```bash
cd /home/tom/projects/playlist-generator
./eval_loop.py --multi --max-iter 2 2>&1 | tee /tmp/eval_latest.log
```
Runs 9 diverse prompts × 2 refinement iterations ≈ 25 minutes.

For a **quick smoke test** on a single prompt (3 min):
```bash
./eval_loop.py --prompt "YOUR PROMPT" --max-iter 1
```

### Step 3 — Read results
```bash
# Batch summary table
grep -A 20 'BATCH RESULTS' /tmp/eval_latest.log | tail -20

# System diagnosis
grep -A 30 'SYSTEM DIAGNOSIS' /tmp/eval_latest.log | tail -30

# Full report with proposed improvements
cat $(ls -dt eval_runs/*_multi/ | head -1)system_report.md
```

Output files in `eval_runs/YYYYMMDD_HHMMSS_multi/`:
- `aggregated.json` — per-prompt scores + dimension breakdown
- `diagnosis.json` — structured weaknesses with severity
- `system_report.md` — full report + proposed diffs

## Interpreting results

### Score thresholds
| Score | Meaning |
|-------|---------|
| ≥ 7.5 | Passes threshold — good |
| 6.0–7.5 | Acceptable, room to improve |
| 4.5–6.0 | Weak — investigate |
| < 4.5 | Failing — likely a regression or library coverage gap |

### Variance awareness
OpenAI evaluation has **±0.3–0.5 variance per prompt** across identical runs. Rules:
- A change is a **confirmed improvement** if overall Δ ≥ +0.3
- A change is a **confirmed regression** if overall Δ ≤ −0.5 AND at least 2 prompts drop by > 1.0
- Changes of ±0.2 overall are **within noise** — run again before concluding

### Historical baselines (do not regress below)
| Prompt | Baseline | Best achieved |
|--------|----------|--------------|
| ambient_doom_arc | 4.50 | 6.95 |
| thrash_energy | 5.55 | 7.30 |
| darkwave_steady | 5.80 | 6.30 |
| doom_journey | 5.50 | 6.30 |
| black_metal_raw | 7.30 | 7.30 |
| industrial_ritual | 6.30 | 6.80 |
| post_punk_goth | 5.80 | 5.80 |
| jazz_nocturnal | 4.50 | 4.80 |
| shoegaze_dreampop | 4.35 | 5.05 |
| **Overall** | **5.41** | **5.99** |

**Library coverage note:** `jazz_nocturnal` and `shoegaze_dreampop` are soft-capped around 4.5–5.5 due to sparse library coverage (library is ~95% metal/goth). Do not chase those scores with weight changes — they need more library tracks.

## Decision tree after seeing results

```
Overall Δ ≥ +0.3 vs previous run?
  YES → Keep change. Any single prompt drop > 1.5 vs its personal best?
          YES → That prompt likely hit noise or library gap. Verify with single-prompt run.
          NO  → Change confirmed. Commit.
  NO, Δ in [-0.3, +0.3] → Within noise. Apply one more targeted fix and re-run.
  NO, Δ < -0.3 → Likely regression.
        Check: did only arc-type prompts drop?
          YES → Revert trajectory weight changes for ARC/MIXED type.
          Check: did only genre-type prompts drop?
          YES → Revert tourist_penalty or genre weight changes.
          ALL prompts dropped → Revert last diff entirely.
```

## Diagnosis → fix mapping

When `diagnosis.json` flags these issues, apply these targeted changes:

### `ARC_FAILURE` (HIGH)
**Symptom:** `arc` dimension weak (< 6) across JOURNEY/PEAK/RISE arc prompts.
**Fix:** Increase `trajectory` weight for `ARC` type in `get_adaptive_weights()`:
```python
# candidates.py — get_adaptive_weights()
elif prompt_type == PromptType.ARC:
    return {
        "semantic": 0.15,   # keep low — arc follows shape, not vibe
        "trajectory": 0.42, # raise toward 0.45 if still failing
        "genre": 0.18,
        "gravity": 0.15,
        "duration": 0.10,
    }
```
Also check `direction_penalty` multiplier in `sequencer.py → _extend_single_path()`. Currently `abs(actual_delta) * 1.0` — raise to `1.2` for stronger arc enforcement.

### `GENRE_DRIFT` (HIGH/MEDIUM)
**Symptom:** `genre` dimension weak (< 6). Evaluator mentions wrong-genre tracks ("industrial in a jazz playlist").
**Fix A — Weights:** Increase `genre` weight for `GENRE` type:
```python
# candidates.py — get_adaptive_weights()
if prompt_type == PromptType.GENRE:
    return {
        "semantic": 0.33,
        "trajectory": 0.15,
        "genre": 0.27,  # raise toward 0.30 if drifting
        "gravity": 0.15,
        "duration": 0.10,
    }
```
**Fix B — Tourist penalty:** Increase zero genre-match penalty in `compute_tourist_match_penalty()`:
```python
if has_genre_hints and genre_match_score <= 0.0:
    return 0.40  # raise toward 0.50 for severe drift
```
**Fix C — GMS strict filter:** If `genre_probs` data exists for ≥20% of candidates, the STRICT mode filter in `generate_position_pools()` uses a probability threshold of `0.28` — raise toward `0.35` for stricter filtering.

### `TRANSITION_WEAKNESS` (MEDIUM)
**Symptom:** `transition` score weak (< 5.5) across most prompts.
**Root cause check first:** Is genre drift causing the transitions to seem jarring? Fix genre drift first — transitions often improve automatically.
**If genre is fine but transitions are still weak:** The `trans_score` weight in `_extend_single_path()` is currently `0.35`. Do NOT simply reduce it — that lowers transition quality further. Instead, check that `score_transition()` is not over-penalizing intentional directional changes.

### `CURATION_FLATNESS` (LOW)
**Symptom:** `curation` < 5 consistently. Evaluator says "safe/obvious picks".
**Fix:** Reduce `impact_score` weight (currently folded into semantic) to de-prioritise high-playcount tracks. Or increase `diversity_threshold` in `SequencerConfig` from `0.8` toward `0.9`.

### `CONSTRAINT_VIOLATION` (LOW)
**Symptom:** `fidelity` < 5. Evaluator says excluded genres/artists still appear.
**Fix:** Check `compute_negative_constraint_penalty()` in `candidates.py`. The ceiling `neg_constraint_ceiling` in `generate_position_pools()` controls hard exclusion. Currently drops candidates with penalty ≥ 0.5 — lower to 0.4 for stricter exclusion.

## Key scoring files

| File | Function | What it controls |
|------|----------|-----------------|
| `service/app/trajectory/candidates.py` | `get_adaptive_weights()` | Per-PromptType scoring weights (semantic, trajectory, genre, gravity, duration) |
| `service/app/trajectory/candidates.py` | `compute_tourist_match_penalty()` | Genre drift penalty for zero-match tracks |
| `service/app/trajectory/candidates.py` | `generate_position_pools()` | STRICT mode GMS filter, admissibility gate, tourist penalty application |
| `service/app/trajectory/sequencer.py` | `SequencerConfig` | `max_artist_count` (hard cap, default 4), `min_artist_distance` (default 4), beam width |
| `service/app/trajectory/sequencer.py` | `_extend_single_path()` | Extension score formula: `total_score + trans_score*0.35 + lookahead*0.3 + bridge_bonus*0.05 - direction_penalty - genre_drift_penalty` |
| `service/app/genre/manifold.py` | `compute_genre_probability_score()` | GMS-based genre score replacing Jaccard when `genre_probs` available |
| `service/app/genre/manifold.py` | `compute_genre_drift_penalty()` | Beam-level genre drift penalty using running distribution |
| `service/app/trajectory/intent.py` | `classify_prompt_type()` | `PromptType.GENRE / ARC / MIXED` — determines which weight set is used |

## Current scoring weight state (applied changes vs original baseline)

```python
# GENRE prompts (thrash, darkwave, black metal, post-punk, jazz, shoegaze)
{"semantic": 0.33, "trajectory": 0.15, "genre": 0.27, "gravity": 0.15, "duration": 0.10}

# ARC prompts (ambient_doom_arc with journey/rise/fall arc type)
{"semantic": 0.15, "trajectory": 0.42, "genre": 0.18, "gravity": 0.15, "duration": 0.10}

# MIXED prompts (doom_journey, industrial_ritual — genre + arc combined)
{"semantic": 0.33, "trajectory": 0.26, "genre": 0.18, "gravity": 0.15, "duration": 0.10}

# SequencerConfig defaults
max_artist_count = 4      # hard cap per artist per playlist
min_artist_distance = 4   # tracks between same-artist appearances

# Tourist penalty (zero genre-match tracks when genre hints present)
return 0.40
```

## Improvement loop discipline

- Make **one targeted change at a time** — don't adjust multiple weight dimensions simultaneously
- Changes < 0.05 on a single weight are usually noise; make changes ≥ 0.05 to see signal
- Jazz/shoegaze scores below 5.0 are expected given library coverage — don't chase them
- If stuck at a plateau (3 runs with Δ < 0.2), move on — further gains need structural changes, not weight tuning
