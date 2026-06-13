# Scoring Utilization of Collected Signals — Design (P3)

**Date:** 2026-06-13
**Status:** Approved (user waived per-spec review for this program)
**Project:** P3 — make the algorithms USE signals we collect but ignore.
**Binding constraint:** every change here touches `trajectory/`, `genre/`, or
`sequencer.py`, so the project's **Algorithm Change Policy applies** — changes
that alter playlist output must pass `eval_loop.py` before commit.

## Data-availability reality (measured 2026-06-13)

| Signal | Coverage | Implication |
|---|---|---|
| `key_estimate` (track_audio_features) | **34,218 / 34,218** analyzed tracks | C4 is live & high-value now |
| `album_tags` | **0 rows** (P2 backfill not yet run) | C2/C3 ship **dormant**: provably no-op until backfill |
| `track_lastfm_tags` | 163 / 38,007 tracks | C1 data-starved; wire it, low impact until enriched |
| RYM `descriptors` | **0 rows** (RYM scraping disabled by default) | C1's descriptor half inert until RYM runs |

This ordering drives the plan: **C4 is the one behavioural change validated by
eval now; C2/C3 are dormant wiring; C1 is wired but data-limited.**

## C4 — Harmonic continuity in the sequencer (LIVE)

`key_estimate` (e.g. "C major", "A minor") is stored for every analyzed track and
never read. Add a harmonic-compatibility term to `score_transition`
(`sequencer.py:237-398`) alongside the existing acoustic-continuity block
(`sequencer.py:346-380`).

- **Field:** add `key_estimate: str | None = None` to `CandidateTrack`; load
  `taf.key_estimate` in the candidate SQL (semantic + keyword search paths).
- **Pure helpers** (new module `trajectory/harmony.py`, fully unit-tested):
  - `parse_key(s)` → `(pitch_class:int 0-11, mode:'maj'|'min')` or None.
  - `camelot(pitch_class, mode)` → Camelot code (1A–12B).
  - `harmonic_compat(key_a, key_b)` → score in [0,1]: 1.0 same key; ~0.9 adjacent
    on the Camelot wheel or relative major/minor; mid for a perfect-fifth move;
    low for distant keys. Returns a neutral 0.5 when either key is missing/unparseable.
- **Integration:** append `(harmonic_compat(prev.key_estimate, curr.key_estimate), W_KEY)`
  to `acoustic_parts`. To keep the change conservative and the existing acoustic
  weights' relative balance intact, use `W_KEY = 0.10` and let the existing
  weighted-average normalization (`wsum`) absorb it — no other weights change.
  When a key is missing the term contributes a neutral 0.5 (doesn't dominate).
- **Eval:** rebuild + `BACKEND_URL=http://localhost:8080 ./eval_loop.py --multi
  --max-iter 2`; keep only if non-regressive vs the baseline table. A short
  single-prompt run first for a sanity check.

## C2 — Album genres into genre match + GMS (DORMANT until album_tags backfill)

Read `album_tags` and merge album-level genres with the per-track genres already
used.

- **Genre match** (`candidates.py:compute_genre_match_score`, `_w_genre=0.20`):
  load an album-genre set per candidate and union it into
  `genre_set_with_families` before the Jaccard loop. New SQL on the candidate:
  album genres via the track's album (`track_albums → album_tags`).
- **GMS ensemble** (`manifold.py:_ensemble`, currently kNN .35 / lastfm .30 /
  direct .25 / audio .10 = 1.0): add an `album_tags` component. Rebalance to
  kNN .30 / lastfm .25 / direct .25 / **album .10** / audio .10 = 1.0. Loader
  `_load_track_album_genres()` joins `track_albums → album_tags` and maps tags to
  genre families via the existing `_ALIAS_TO_FAMILY`.
- **Dormant-safe:** with `album_tags` empty, both paths add the empty set →
  byte-identical output. This is the safety property that lets C2 ship before the
  backfill; a **follow-up eval is required after the album_tags backfill** runs
  (flagged below), since that is when behaviour actually changes.

## C3 — Consensus weighting (folded into C2)

`album_tags.weight` carries source-native confidence (Last.fm tag weight, MB/RYM
vote counts). In the GMS album loader, weight each album genre by a normalized
`weight` (fall back to 1.0 when null) and by source priority, so a genre agreed
on by multiple sources / high vote counts contributes more than a single weak
tag. Implemented as part of the C2 album loader — no separate integration point.

## C1 — Positive mood term from track tags + RYM descriptors (WIRED, data-limited)

Today `track.rym_descriptors` is read only by
`compute_negative_constraint_penalty` (`candidates.py:257`) and
`track_lastfm_tags` aren't loaded onto the candidate at all.

- **Intent:** add positive mood/descriptor extraction to intent parsing (sibling
  to `extract_avoid_keywords`, `intent.py:859`), producing a `mood_terms` set
  from the prompt (the descriptive adjectives that aren't genres or avoid-terms).
- **Candidate:** load `track_lastfm_tags` (names) onto `CandidateTrack`; expose
  `rym_descriptors` (already loaded for the negative path).
- **Score:** new `compute_mood_match(track, mood_terms)` → [0,1] over the union
  of track tags + RYM descriptors; add `+ mood_match * _w_mood` to `total_score`
  with a small `_w_mood` (≈0.08). Neutral 0 when no mood terms or no tags.
- **Honesty:** with present coverage (163 tracks tagged, 0 descriptors) this moves
  almost nothing. It is correct wiring that pays off once Last.fm track-tag and
  RYM enrichment are run. Because it can change output for the 163 tagged tracks,
  it is included in the C4 eval run.

## Eval plan & gating

1. Implement C4 + C1 (both can change output now) and C2/C3 (dormant).
2. Rebuild: `docker compose --profile unified up -d --build app`.
3. Sanity: `BACKEND_URL=http://localhost:8080 ./eval_loop.py --prompt "dark
   atmospheric post-punk" --max-iter 1`.
4. Full: `./eval_loop.py --multi --max-iter 2` against the historical baseline.
5. Keep/revert per the policy decision tree. Commit only on a non-regressive run.
6. **Deferred eval (flagged):** after the `album_tags` backfill populates the
   table, re-run eval to validate C2/C3's now-active contribution. Until then they
   are dormant and non-regressive by construction.

## Testing

- `trajectory/harmony.py`: `parse_key`, `camelot`, `harmonic_compat` — same key,
  relative maj/min, adjacent wheel, fifth, tritone, missing/garbage → all pure.
- Album-genre merge: genre-match union and GMS album loader with a synthetic
  `album_tags` row (rolled-back DB test); empty-table → no-op assertion.
- `compute_mood_match`: overlap, empty terms, empty tags (pure).

## Documentation (same commit)

- `AGENTS.md` V4 Scoring section: new harmonic-continuity term and weight; GMS
  ensemble reweight (kNN .30/lastfm .25/direct .25/album .10/audio .10); new
  `_w_mood`; genre match now includes album genres.
- `SKILL.md` current weight state (if present).
