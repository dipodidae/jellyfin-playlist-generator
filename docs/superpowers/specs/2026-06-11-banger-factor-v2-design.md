# Banger Factor v2 — Composite Scoring Design

**Date:** 2026-06-11
**Status:** Approved (design)
**Surface:** `service/app/enrichment/banger_detector.py` only

## Problem

The current banger detector (`banger_detector.py`) scores tracks from a single
data source — Last.fm popularity — via two signals: within-artist log-playcount
rank (0.60) and global log-listener percentile (0.40). A richer "banger factor"
spec was drafted (sonic profile, engagement velocity, social contagion, replay
signal) but never built. This design implements the buildable subset against the
data the stack already holds.

## Scope decision

The original spec defined four signal groups. Only two are buildable on this
stack without new external dependencies; one requires data we do not yet collect;
one is impractical for a homelab. Decisions:

| Group | Spec source | Decision |
|---|---|---|
| A — Sonic | Spotify audio features API | **BUILD** from existing `track_audio_features` (librosa-derived). Spotify's API is dead for new apps; local features replace it. |
| B — Velocity | Last.fm trend slope, Spotify growth | **DROP.** Needs a time-series; `lastfm_stats` is a single snapshot. Revisit if/when weekly snapshot logging exists. |
| C — Social | TikTok/YouTube/Reddit scraping | **DROP.** Fragile, ToS-violating, needs paid APIs. Not appropriate for a homelab. |
| D — Replay | scrobbles / unique-listeners ratio | **BUILD** from existing `lastfm_stats.playcount / listeners`. |
| (existing) Popularity | within-artist rank + global percentile | **KEEP** as the anchor signal. |

## Output contract (unchanged)

`banger_score` stays a single `FLOAT` in `[0.0, 1.0]` in `track_banger_flags`
(`track_id, banger_score, confidence, sources, computed_at`). Downstream
consumers in `service/app/trajectory/candidates.py` (curation scoring) are
**untouched** — this is a drop-in replacement for how the column is computed,
not a contract change. No schema change, no new endpoint, no frontend change,
no new dependency.

## Final composite

```
banger_score = popularity_score * 0.45
             + sonic_score      * 0.35
             + replay_score     * 0.20
```

Weights are renormalized over whichever groups have data for a given track (see
Graceful Degradation). Result clamped to `[0.0, 1.0]`.

### Popularity (0.45) — unchanged

Carried over verbatim from the current detector:

- Within-artist signal (0.60): `log1p(playcount)` rank vs the same artist's
  other tracks, normalized `1.0` (artist's #1) → `0.0` (last). Requires the
  artist to have ≥ `_MIN_ARTIST_TRACKS` (5); smaller catalogs fall back to a
  global log-playcount proxy.
- Global signal (0.40): percentile of `log1p(listeners)` across the library.

### Sonic (0.35) — new, from `track_audio_features`

```
sonic = energy*0.30 + danceability*0.30 + loudness_norm*0.15
      + tempo_score*0.15 + valence*0.10
```

- **energy** — no literal column exists; derived proxy:
  `0.5*loudness_norm + 0.3*onset_rate_norm + 0.2*pulse_clarity`.
  (Chosen over the embedding-derived `track_profiles.energy` because "banger"
  is an acoustic-punch quality, not a semantic one.)
- **danceability** — `track_audio_features.danceability` (heuristic proxy;
  see CLAUDE.md gotcha #8 — not ground truth, used as a soft signal).
- **loudness_norm** — `track_audio_features.loudness_norm`.
- **tempo_score** — piecewise function of `bpm`: `1.0` across the 90–130 BPM
  peak banger zone; linear falloff to `0.0` at `bpm ≤ 70` and `bpm ≥ 180`.
- **valence** — `track_audio_features.valence` as a mild upbeat bonus, with a
  **genre correction**: for tracks whose Last.fm / RYM genre tags match
  `{metal, doom, industrial, darkwave, goth, noise}` (case-insensitive
  substring match), the valence term is dropped and its `0.10` weight
  redistributed proportionally across the other four terms. Dark tracks are
  therefore not penalized for low valence. Genre tags sourced from
  `track_lastfm_tags` and `rym_album_genres`/`rym_genres`.

All sub-inputs are expected in `[0,1]` (the `_norm` columns already are);
`valence`/`danceability` are clamped defensively.

### Replay (0.20) — new, from `lastfm_stats`

```
ratio        = playcount / listeners        (global plays-per-listener)
replay_score = percentile of log1p(ratio) across the library
```

A high global plays-per-listener ratio means people who know the track replay
it — a repeat-play banger signal. Note this is **global** Last.fm data, not the
owner's personal listening; it measures "tracks the world replays," which is
still a reasonable banger proxy. `listeners = 0` → replay signal absent.

## Graceful degradation

Audio analysis is incomplete on the 12.7k+ library, so a track may be missing a
group. Weights renormalize over present groups:

| Track has | Active groups | Effective weights |
|---|---|---|
| audio + lastfm | all three | 0.45 / 0.35 / 0.20 |
| lastfm only | popularity + replay | 0.69 / 0.31 |
| audio only | sonic | 1.00 |
| neither | — | score 0 (skipped, as today) |

## Confidence

Extends the current 4-tier logic to account for group coverage and agreement:

- All three groups present and mutually high → top band (`0.85–1.0`).
- Two groups, or one strong signal → mid band (`0.55–0.80`).
- Single weak group but `score > 0.3` → low band (`0.25–0.50`).
- Else → `max(0.05, score*0.5)`.

(Exact band math finalized in implementation; preserves the existing shape.)

## `sources` JSON

Each contributing signal is logged with its sub-value for UI transparency and
debugging, e.g.:

```json
[
  {"type": "lastfm_artist_rank",     "value": 0.92, "artist_tracks": 14},
  {"type": "lastfm_global_listeners","value": 0.81, "percentile": 81.0},
  {"type": "sonic_audio",            "value": 0.74, "energy": 0.7, "tempo_score": 1.0, "valence_corrected": true},
  {"type": "lastfm_replay_ratio",    "value": 0.66, "ratio": 23.4}
]
```

## Validation

Per the repo's Algorithm Change Policy, scoring changes must pass an eval run
before being considered complete. The implementation plan will include:

1. Recompute flags: `/enrich/banger-flags` (or `app.cli_v3`) against the running
   `playlist-generator` container.
2. `./eval_loop.py --multi --max-iter 2` and compare to the historical baseline.
3. Keep / revert / iterate per the eval-changes decision tree.

## Out of scope

- Group B (velocity) and Group C (social) — dropped as above.
- The advisory threshold buckets (0.4 / 0.65 / 0.8) — curation scoring consumes
  the raw `[0,1]` score, not buckets; thresholds remain documentation only.
- Any change to `candidates.py` curation weights.
