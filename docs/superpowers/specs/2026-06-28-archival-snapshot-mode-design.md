# Archival Snapshot Mode — Design

**Date:** 2026-06-28
**Status:** Approved (brainstorming complete)

## Problem

The playlist generator only knows how to build **trajectories**. Every path
through `compose_playlist_v4` parses an arc (steady/rise/fall/peak/journey…),
builds position-indexed candidate pools (one per waypoint), and runs beam-search
sequencing to walk a 6D energy/mood curve. Ordering and progression are the whole
point.

One genuinely different user intent is unserved: the **archival snapshot**. The
user names a niche descriptor ("evil 80s thrash") and wants a *representative
cross-section of what they own in that niche* — the bangers and the great deep
cuts, spread across the artists in their collection — assembled into one chonky
shuffle. This is **not** an arc or a journey. It cares about **coverage and
quality**, not progression. Sequencing is, deliberately, just a shuffle.

## Decisions (from brainstorming)

| Dimension | Decision |
|---|---|
| Core objective | **Breadth across artists** — a tour of *who* you own in the niche |
| Per-artist depth | **2–4 tracks** each: the banger + strong deep cuts |
| Size | **Big soft cap (~120, configurable)**; if the niche is thinner, you get everything that qualifies |
| Ordering | **True shuffle**, no two same-artist tracks adjacent; trajectory engine not invoked |
| Trigger | **Explicit UI toggle** (Arc · Snapshot); prompt is purely the descriptor |
| Relevance floor | **Strict** — quality over fullness; never pad with marginal tracks. Always report the qualifying count so a short list reads as a library limit, not a bug |
| Architecture | **Parallel composer** — reuse intent parse + flat candidate scoring, replace only sequencing |

## Architecture

New module `service/app/snapshot/composer.py`, deliberately *outside*
`trajectory/`. It shares scoring helpers from `trajectory/candidates.py` but is
not a trajectory: it never calls `generate_position_pools` or `sequence_playlist`.

```
generate_playlist (routes_v3)
        │  mode == "snapshot"?
        ├── "arc"      → compose_playlist_v4        (unchanged)
        └── "snapshot" → compose_snapshot           (new)
                              │
                              ├── parse_prompt()                    (reused)
                              ├── gather_candidates()  flat pool    (reused helpers)
                              ├── score + gate (relevance R, curation C)
                              ├── select_by_artist()   2–4 per artist, breadth-first
                              ├── apply_soft_cap()      ~120
                              └── shuffle_no_adjacent_artist()
```

### 1. API surface

- `GeneratePlaylistRequest` gains `mode: Literal["arc", "snapshot"] = "arc"`.
  Default `"arc"` preserves all existing behavior and tests.
- `generate_playlist` and `generate_playlist/stream` branch on `mode`.
- Frontend `frontend/app/pages/index.vue`: a segmented **Arc · Snapshot** toggle
  above the prompt. In Snapshot mode, arc-only affordances are hidden; the
  prompt is purely the descriptor. The Nuxt server proxy forwards `mode`.

### 2. Candidate gathering (reused, flattened)

`compose_snapshot(prompt, soft_cap=120)`:

1. `intent = parse_prompt(prompt)` — but snapshot **uses only**: `genre_hints`,
   `genre_hints_raw`, `year_range`, `base_darkness` + mood keywords, and
   `hard_avoid_keywords`. `arc_type`, `waypoints`, `trajectory_curve`, and
   `dimension_weights` are **ignored**.
2. Build **one flat candidate pool** (not position pools) via
   `multi_query_semantic_search` + `keyword_search` at a large limit sized to
   cover the niche (target several × the soft cap so artist breadth has room).
   Dedupe via the existing near-duplicate logic.
3. Per-candidate gating:
   - **Hard cuts** (track dropped): `compute_genre_exclusion(track, hard_avoids)`
     and `year_range` filter when a range was parsed.
   - **Relevance `R` ∈ [0,1]**: `compute_genre_match_score(...)` in its niche
     regime (the existing P-NICHE discrimination is exactly what keeps "evil 80s
     thrash" from collapsing into "all thrash") blended with mood proximity —
     e.g. "evil" → prefer high `base_darkness` tracks.
   - **Strict relevance floor**: tracks below `R_floor` are dropped, never
     padded. The floor is a tunable constant.

### 3. Banger / deep-cut definition (the crux)

Each surviving track carries two existing signals:

- **Relevance `R`** — niche fit (above).
- **Curation `C`** — `CandidateTrack.curation_score` (banger detection + album
  legitimacy + studio score), already computed; no new scoring infrastructure.

Within an artist's qualifying tracks:

- A **banger** = high banger/popularity component (top of *that artist's* track
  popularity distribution).
- A **banging deep cut** = lower popularity but high on the *non-popularity*
  quality signals (album legitimacy + studio score + strong `R`).

Snapshot deliberately does **not** apply a single `impact_preference` lean — it
wants both ends of the popularity range, gated by quality.

### 4. Per-artist selection (breadth-first)

- Bucket qualifying tracks by `artist_id`.
- Rank each artist's tracks by `snapshot_score = 0.5·R + 0.5·C`.
- Pick **2–4** per artist:
  1. Always include their top **banger** if one clears the popularity bar.
  2. Fill remaining slots with the highest-quality **deep cuts**.
  3. **Album cap** (≤2 tracks per album) so one record can't fill an artist's
     whole quota.
- An artist whose *best* track is below the relevance floor is dropped entirely
  — breadth must not pad with junk (strict-floor decision).

### 5. Soft cap (~120)

- Rank artists by their best-track `snapshot_score`.
- Walk the ranked artist list, accumulating each artist's 2–4 picks until the cap
  is reached. Partial inclusion of the final artist is allowed.
- If the whole niche yields fewer tracks than the cap, return everything that
  qualified — the list *is* the snapshot. `soft_cap` is configurable
  (request param, default 120).

### 6. Ordering — constraint shuffle

- Random order (fresh each run; re-roll by re-generating), then a greedy pass
  enforcing **no two same-artist tracks adjacent** (and softly, same album).
- No 6D smoothing, no arc, no energy targets. `sequence_playlist` is **not**
  called.

### 7. Metrics, title, persistence (reused)

- Reuse `log_generation`, `update_track_usage`, the OpenAI title generator, and
  Jellyfin/m3u export unchanged.
- Snapshot-specific metrics (always reported, satisfying the count decision):
  `qualifying_tracks`, `distinct_artists`, `banger_count`, `deep_cut_count`,
  `soft_cap`, `niche_floor`. A short list is then legible as a library limit.

## Module boundaries

- `service/app/snapshot/composer.py` — `compose_snapshot()` + streaming variant;
  the only orchestration entry point. Returns the existing `PlaylistResult`
  shape so downstream (export, title, metrics) is untouched.
- `service/app/snapshot/selection.py` — pure functions: `score_candidate`,
  `select_by_artist`, `apply_soft_cap`, `shuffle_no_adjacent_artist`. No I/O →
  unit-testable in isolation against synthetic `CandidateTrack` lists.
- Reused from `trajectory/candidates.py`: search helpers, `CandidateTrack`,
  `compute_genre_match_score`, `compute_genre_exclusion`, `derive_niche_hints`,
  near-duplicate dedupe.

Each unit answers cleanly: *what it does* (score / select / cap / shuffle), *how
you use it* (pure list-in, list-out), *what it depends on* (only the
`CandidateTrack` dataclass and scalar config).

## Testing

- **Unit** (`service/tests/` mirroring existing layout): `selection.py` functions
  against synthetic candidate lists — artist breadth, 2–4 quota, album cap,
  soft-cap truncation keeps strongest artists, shuffle never places same artist
  adjacent, strict floor drops weak artists.
- **Integration**: `compose_snapshot("evil 80s thrash")` against the live DB
  asserts distinct-artist count ≫ track count / 4, year filter honored, no arc
  metrics present.
- **Eval**: per the repo's Algorithm Change Policy, snapshot is a *new path* that
  does not touch the trajectory scoring the eval baseline measures. Confirm the
  existing 9-prompt arc eval is unchanged (regression guard), and add a small
  manual snapshot smoke check rather than forcing snapshot into the arc eval
  harness.

## Out of scope (YAGNI)

- Auto-detecting snapshot intent from prompt phrasing (explicit toggle only).
- Duration-based sizing (track-count soft cap only).
- Proportional per-artist depth (fixed 2–4).
- Any change to the trajectory engine, beam search, or arc eval baseline.
