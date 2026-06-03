# Playlist Quality Fixes — Design

**Date:** 2026-06-03
**Status:** Proposed (awaiting approval)

## Motivation

Analysis of the 8 real playlist generations in the database (the user's "4 playlists,"
several of them retried) revealed a clear quality split:

| Prompt | Arc | Verdict |
|---|---|---|
| start ambient and dreamy, then build into crushing doom | journey | **Catastrophic** — 10 tracks, all Fates Warning, one album |
| a journey from dreamy shoegaze through post-rock into heavy doom metal | journey | **Failed** — classic/hard rock, no shoegaze/post-rock |
| coolest cold wave tracks ever | steady | **Weak** — 30 tracks, 3 artists |
| The coolest coldwave (retry) | steady | **Weak** — same 3 artists |
| thrash metal workout | rise | **Good but buggy** — "Voivod – Suck Your Bone" ×3 |
| best coldwave plahylist EVER (3rd retry) | steady | **Good** — ~9 artists |
| weird new age kraut and stuff | steady | **Excellent** |
| pure evil black metal | steady | **Excellent** |

Retried prompts (coldwave ×3, journey ×2) are the strongest dissatisfaction signal.

Steady single-genre prompts on well-represented genres work well. The failures cluster
around four mechanisms, all confirmed in code against the live library
(12,787 tracks, 350 artists; Ambient=328, Dark Ambient=361, Doom Metal=435 — so the
"ambient → doom" journey was buildable, the algorithm just didn't build it).

## Root causes (confirmed in code)

1. **Genre-blind admissibility gate** (`candidates.py:1255-1260`). The secondary genre
   pool (`:1055`) and artist-tag pool (`:1087`) assign candidates `semantic_score=0.15`,
   but the gate hard-requires `semantic_score >= semantic_floor` (0.16–0.22). So
   genre-matched tracks that semantic search didn't already surface are **always dropped**.
   The secondary pools are effectively dead weight, and the pool collapses onto the few
   artists the prompt embedding favors → 3-artist coldwave.

2. **Journey/arc prompts ignore per-segment genre** (`candidates.py:745-785, 940-1366`).
   Phase queries append generic words ("intro beginning", "peak intense climax") to the
   *whole* prompt, so "...crushing doom" dominates every phase query → all segments retrieve
   metal. Genre is scored once globally; no position favors ambient early or doom late.

3. **Artist/album cap relaxes to unbounded** (`sequencer.py:384-429`). `max_artist_count=4`
   is real, but the relaxation ladder escalates to `999` on dead-ends, and there is **no
   album cap** at all → 10× one Fates Warning album; 30/3-artist coldwave.

4. **Dedup is track-id only** (`sequencer.py:120-122`). Re-imports and (live)/(demo)/(remix)
   variants are distinct IDs → "Suck Your Bone" ×3.

## Design

A new shared module plus targeted edits to four existing files. Each change is independently
testable and keeps existing behavior on the paths it doesn't touch.

### Fix 0 — `app/trajectory/textnorm.py` (new, structural)
Two pure functions, no deps, unit-testable in isolation:
- `normalize_artist(name)` — accent-strip + lowercase (moved from `sequencer._normalize_artist`,
  which becomes a thin delegate to preserve its `lru_cache`).
- `normalize_title(title)` — lowercase; strip trailing/standalone qualifiers
  `(live)`, `(demo)`, `(remix)`, `(remaster[ed])`, `(... session)`, `(single version)`,
  `(edit)`, `(version)`, `(mono|stereo)`, `(instrumental)`, `[untitled]`; strip `feat. …`;
  drop punctuation; collapse whitespace. Used for near-duplicate signatures.

### Fix 1 — Genre-aware admissibility (`candidates.py`)
Change the gate so a track is admissible when it clears the semantic floor **OR** is a
strong primary-genre match, still subject to `admissibility_score` and negative-constraint
gates:
```
keep if (semantic_score >= semantic_floor OR strong_primary_genre)
        and admissibility_score >= admissibility_floor
        and negative_constraint_penalty < neg_constraint_ceiling
```
`strong_primary_genre` = `hint_set` non-empty AND `genre_match_score >= 0.50`. This lets the
secondary genre/tag pools actually contribute, widening artist diversity for genre and
sparse-genre prompts (directly fixes coldwave narrowness; helps everything genre-driven).

### Fix 2 — Per-segment genre waypoints (`intent.py`, `candidates.py`)
- LLM intent schema gains `"genres"` (array) per `custom_waypoints` entry; validated/coerced
  to `list[str]` (drop silently if malformed — graceful, no behavior change when absent).
- `TrajectoryWaypoint` gains `genres: list[str] = []`, populated from `custom_waypoints`.
- `PlaylistIntent.segment_genres_at(t_norm)` → genres of the nearest waypoint (empty list when
  no per-segment genres). 
- `build_phase_queries`: when any waypoint has genres, build phase queries from the segment
  genre strings (e.g. `"ambient dreamy atmospheric"`, `"crushing doom metal"`) so each
  segment's genre is actually retrieved; also union a genre-filtered DB pool per segment genre
  (reuse the existing genre-pool query) so segment genres are guaranteed present even when
  semantically sparse. Falls back to current generic phase queries otherwise.
- `generate_position_pools`: when waypoint genres exist, score `genre_match` for each position
  against that position's segment genres instead of the global union. Recompute only when the
  active segment changes (bounded cost; journeys are short and pools already cache).

### Fix 3 — Harden artist/album caps (`sequencer.py`, `composer_v4.py`)
- `SequencerConfig`: add `max_album_count: int = 2`, `hard_max_artist_count: int | None`,
  `hard_max_album_count: int | None`.
- `BeamPath`: add `album_counts: dict[str,int]` (keyed by `album_id` or `normalize`d album name).
- `is_valid_extension`: enforce album cap; enforce `hard_max_*` as **absolute** caps the
  relaxation ladder cannot exceed.
- `_relaxed_config`: clamp `max_artist_count` to the hard ceiling at every level (no more 999);
  album cap may loosen by at most +1 at the top level, never unbounded.
- `composer_v4` (both compose fns): set, from `intent.target_size`,
  `hard_max_artist_count = max(3, round(target_size*0.25))`,
  `max_album_count = max(2, round(target_size*0.15))`,
  `hard_max_album_count = max_album_count + 1`.
- Net behavior: when diversity is genuinely exhausted, the playlist **stops short** rather than
  dumping one artist/album (per the user's stated preference).

### Fix 4 — Near-duplicate dedup (`candidates.py`, `sequencer.py`)
- `candidates.generate_position_pools`: collapse `global_candidates` by
  `(normalize_artist(artist_name), normalize_title(title))`, keeping the best version
  (prefer the one with no suffix in its raw title; tie-break on `semantic_score`). Applied
  before admissibility scoring.
- `sequencer.BeamPath`: add `signatures: set`; `is_valid_extension` rejects a candidate whose
  signature is already in the path (cheap backstop). Wire into `copy()` and the extend appliers.

## Out of scope (YAGNI)
- Cleaning dirty `year` data (one track shows `year=1`). Real, but separate from these failures
  and not chosen for this pass. Noted for a future era-prompt effort.
- Library gaps (shoegaze=11, post-rock=4) — can't be fixed by the algorithm.

## Testing & validation
- Unit tests for `textnorm` (title/artist normalization, dedup signatures) and for the
  genre-aware admissibility predicate, under `service/app/tests/` (pytest).
- Per project Algorithm Change Policy: rebuild the backend container, run
  `./eval_loop.py --multi --max-iter 2` (9-prompt batch), AND regenerate the user's 8 real
  prompts, comparing artist-diversity / dedup / per-segment-genre before vs after.
- Keep/revert per the eval baseline table.

## Docs to update (same commit)
`AGENTS.md` (V4 Scoring: admissibility predicate, sequencer constraints incl. album cap +
hard ceilings), `SKILL.md` (current weight/constraint state), `CLAUDE.md` (gotcha: code is
baked into the image — algorithm changes need a container rebuild before eval).
