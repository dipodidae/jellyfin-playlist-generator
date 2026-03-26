---
description: Evaluate playlist generation quality after code changes. Runs multi-prompt batch eval, aggregates scores, diagnoses systemic weaknesses, and proposes improvements.
---

## Validate backend changes with eval loop

Use this after modifying anything in `service/app/trajectory/`, `service/app/genre/`, or scoring logic.

### 1. Restart the backend to load code changes
// turbo
Run `systemctl --user restart playlist-generator-backend`

### 2. Wait for the backend to become healthy
// turbo
Run `sleep 30 && curl -s http://localhost:8000/health`

### 3. Run the multi-prompt evaluation (9 prompts × 2 iterations each, ~25 min)
Run `./eval_loop.py --multi --max-iter 2 2>&1 | tee /tmp/eval_latest.log` in the `/home/tom/projects/playlist-generator` directory.

This generates a timestamped run directory under `eval_runs/YYYYMMDD_HHMMSS_multi/` containing:
- `aggregated.json` — per-prompt scores and dimension breakdown
- `diagnosis.json` — structured systemic weakness list with severities
- `system_report.md` — full markdown report with proposed improvements

### 4. Read the batch summary from the log
// turbo
Run `grep -A 20 'BATCH RESULTS' /tmp/eval_latest.log | tail -20`

### 5. Read the system diagnosis
// turbo
Run `grep -A 30 'SYSTEM DIAGNOSIS' /tmp/eval_latest.log | tail -30`

### 6. Read the full system report for improvement proposals
Find the most recent multi-run directory and read its system_report.md:
// turbo
Run `cat $(ls -dt /home/tom/projects/playlist-generator/eval_runs/*_multi/ 2>/dev/null | head -1)system_report.md`

### 7. Compare against baseline / previous run

The historical reference scores are:
| Prompt            | Baseline | Best achieved |
|-------------------|----------|---------------|
| ambient_doom_arc  | 4.50     | 6.95          |
| thrash_energy     | 5.55     | 7.30          |
| darkwave_steady   | 5.80     | 6.30          |
| doom_journey      | 5.50     | 6.30          |
| black_metal_raw   | 7.30     | 7.30          |
| industrial_ritual | 6.30     | 7.10          |
| post_punk_goth    | 5.80     | 5.80          |
| jazz_nocturnal    | 4.50     | 4.80          |
| shoegaze_dreampop | 4.35     | 6.30          |
| **Overall**       | **5.41** | **5.99**      |

A change is an improvement if the new overall score exceeds the previous run's overall score.
Evaluation has inherent OpenAI variance of ±0.5 per prompt — a Δ < 0.3 overall is within noise.

### 8. Decide: keep, revert, or iterate

- **Keep** the change if overall score ≥ previous run − 0.3 and no prompt regresses by > 1.5 vs its best.
- **Revert** (`git diff service/app/` to identify changed files) if a clear regression is confirmed.
- **Iterate** by applying one targeted fix from `diagnosis.json` and re-running from step 1.

## Run a quick single-prompt sanity check (faster, ~3 min)

Use this for a fast smoke test after a focused change.

Run `./eval_loop.py --prompt "YOUR PROMPT HERE" --max-iter 1` in the `/home/tom/projects/playlist-generator` directory.

Interpret: weighted score ≥ 7.0 = good, 5–7 = acceptable, < 5 = investigate.

## Key files for scoring changes

| File | What it controls |
|------|-----------------|
| `service/app/trajectory/candidates.py` | `get_adaptive_weights()` — per-PromptType scoring weights; `compute_tourist_match_penalty()` — genre drift penalty |
| `service/app/trajectory/sequencer.py` | `SequencerConfig` — beam search constraints incl. `max_artist_count`; `_extend_single_path()` — extension scoring formula |
| `service/app/genre/manifold.py` | GMS — probabilistic genre identity; `compute_genre_probability_score()`, `compute_genre_drift_penalty()` |
| `service/app/trajectory/intent.py` | Prompt parsing, `PromptType`, `GenreMode`, waypoint generation |
