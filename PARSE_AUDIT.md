# PARSE_AUDIT.md — Prompt parsing + LLM integration audit

> **STATUS (2026-06-15): all 8 proposals (P1–P8) IMPLEMENTED.** See the
> "Implementation status" section at the end for the per-proposal mapping to
> code, tests, and config. Validated by `app/tests` (135 + 23 new, all green)
> and a live end-to-end eval against the 41k-track library.

Audit date: 2026-06-15. Read-only trace of `raw prompt → structured intent →
scoring`. Every claim cites `file:line`. The active production path is
**PostgreSQL → `routes_v3` → `composer_v4`** (`service/app/main.py:15-25`,
`service/app/main.py:17-19`); the DuckDB `routes.py`/`composer.py` path is
legacy and only loads when `DATABASE_URL` is not `postgresql://`.

---

## Phase 1 — The parse path

### Entry point

- HTTP: `POST /generate` and `/generate/stream` →
  `service/app/api/routes_v3.py:1874-1877` and `:1928-1965`, which call
  `compose_playlist_v4` / `compose_playlist_v4_streaming`.
- Composer: `service/app/trajectory/composer_v4.py:66` and `:200` both call
  `intent = parse_prompt(prompt, target_size=target_size)`.
- Parse: `service/app/trajectory/intent.py:1277` `parse_prompt()` is the single
  funnel. It (1) always generates a prompt embedding
  (`intent.py:1286-1287`), (2) tries the LLM
  (`_parse_prompt_with_llm`, `intent.py:1290`), (3) falls back to keyword
  parsing (`intent.py:1295-1297`).

### LLM-driven vs heuristic — it is **hybrid, LLM-first**

`parse_prompt` (`intent.py:1290-1297`):

```python
llm_data = _parse_prompt_with_llm(prompt)
if llm_data is not None:
    return _build_intent_from_llm(prompt, prompt_embedding, llm_data, target_size)
# Fallback: keyword-based parsing
logger.info("Using keyword-based prompt parsing (LLM unavailable)")
return _build_intent_from_keywords(prompt, prompt_embedding, target_size)
```

Field-by-field provenance (which branch supplies what):

| Field | LLM branch (`_build_intent_from_llm`, intent.py:1300) | Keyword branch (`_build_intent_from_keywords`, intent.py:1462) |
|---|---|---|
| genres/subgenres | LLM `genre_hints` (`:1321`), then `expand_genre_hints` (`:1325`) | regex taxonomy `extract_genre_hints` (`:1469`, `:639`) |
| moods | LLM `mood_keywords` (`:1327`) | `extract_mood_keywords` keyword list (`:1477`, `:613`) |
| energy-arc shape | LLM `arc_type` (`:1307`), validated/defaulted to `journey` | `detect_arc_type` keyword match (`:1476`, `:564`) |
| era / year range | LLM `year_range` (`:1329`) **+** always-on `detect_era_mode` (`:1335`) | `extract_year_range` regex (`:1480`, `:694`) + `detect_era_mode` (`:1494`) |
| artist references | LLM `artist_seeds` (`:1326`) | `extract_artist_seeds` regex (`:1478`, `:677`) |
| exclusions | LLM `avoid_keywords` **unioned** with regex `extract_avoid_keywords(prompt)` (`:1328`) | `extract_avoid_keywords` regex (`:1479`, `:859`) |
| impact (banger/deep-cut) | **always regex** `extract_impact_preference(prompt)` (`:1331`, `:828`) — LLM ignored | same regex (`:1482`) |
| valence | **always regex** `parse_valence_target(prompt)` (`:1343`, `:750`) | same regex (`:1501`) |
| prefer_live | **always regex** `detect_prefer_live(prompt)` (`:1353`, `:765`) | same regex (`:1511`) |

Note the asymmetry: even on the LLM path, `impact_preference`, `valence_target`,
`prefer_live`, `era_mode` and the regex `avoid_keywords` are recomputed
heuristically and override/augment the model — so the LLM never fully owns the
intent.

### Intermediate data structure

`PlaylistIntent` dataclass — `service/app/trajectory/intent.py:129-192`:

```python
@dataclass
class PlaylistIntent:
    raw_prompt: str
    prompt_embedding: list[float]
    arc_type: ArcType = ArcType.STEADY
    arc_confidence: float = 0.5
    target_size: int = 20
    target_duration_minutes: int | None = None
    impact_preference: float = 0.0
    prompt_type: PromptType = PromptType.MIXED
    mood_keywords: list[str] = field(default_factory=list)
    genre_hints: list[str] = field(default_factory=list)
    genre_hints_primary: set[str] = field(default_factory=set)  # pre-expansion
    artist_seeds: list[str] = field(default_factory=list)
    trajectory_curve: TrajectoryCurve | None = None
    waypoints: list[TrajectoryWaypoint] = field(default_factory=list)
    dimension_weights: DimensionWeights = field(default_factory=DimensionWeights)
    base_energy: float = 0.5
    base_darkness: float = 0.5
    base_tempo: float = 0.5
    base_texture: float = 0.5
    avoid_keywords: list[str] = field(default_factory=list)
    year_range: tuple[int | None, int | None] = (None, None)
    era_mode: str = "none"          # none, chronological, reverse, locked, arc
    prefer_live: bool = False
    abstract_concepts: list[str] = field(default_factory=list)
    genre_mode: GenreMode = GenreMode.BALANCED
    genre_centroids: dict[str, list[float]] = field(default_factory=dict)
```

Supporting types: `PromptType` (genre/arc/mixed, `:31`), `GenreMode`
(strict/balanced/exploratory, `:38`), `ArcType` (7 shapes, `:45`),
`TrajectoryWaypoint` (6D + per-phase `genres`, `:56`), `DimensionWeights`
(`:72`).

### Sibling-genre expansion — hardcoded, hand-curated, NOT derived from the library

The "coldwave pulls darkwave/post-punk/synth-pop" behaviour lives in **two
disconnected places**:

1. `_RELATED_FAMILIES` dict — `service/app/trajectory/intent.py:478-503`. Used by
   `expand_genre_hints` (`:515-543`). Example:
   ```python
   "coldwave": ["darkwave", "post-punk", "synth-pop", "new wave"],
   ```
   This is a **hand-written static graph**. The header comment (`:248-253`)
   claims the *alias taxonomy* (`GENRE_ALIASES`, `:254-466`) was "built from
   actual library data (400 genres + 2 296 Last.fm artist tags)", but
   `_RELATED_FAMILIES` itself has no such provenance — it is invented/curated,
   not computed from tag co-occurrence in the DB.
2. The **LLM system prompt** independently hardcodes a *different*, overlapping
   sibling list as inline examples (`intent.py:1062-1070`), e.g. `"coldwave" →
   ["coldwave", "darkwave", "minimal wave", "post-punk"]` and `"doom metal" →
   ["doom metal", "stoner metal", "sludge metal"]`. Note `minimal wave` and
   `stoner metal` appear in the prompt graph but the relationships are not
   identical to `_RELATED_FAMILIES`. **Two sources of truth that can drift.**

There *is* a library-derived adjacency available — `get_adjacent_genres()` from
the Genre Manifold (used at `candidates.py:1281-1284`) — but it is only consulted
during scoring, not during hint expansion.

### Energy-arc classifier — keyword match (fallback) OR LLM (primary)

- LLM path: `arc_type` comes straight from the model, then coerced by
  `_validate_llm_intent` (`intent.py:1186-1189`) — **invalid/missing arc defaults
  to `"journey"`**.
- Keyword path: `detect_arc_type` (`intent.py:564-610`) counts substring hits
  against `ARC_KEYWORDS` (`:231-238`):
  ```python
  if not arc_scores:
      if genre_hints and len(prompt.split()) < 6:
          return ArcType.JOURNEY, 0.5
      return ArcType.STEADY, 0.3   # Low confidence default
  best_arc = max(arc_scores, key=arc_scores.get)
  ```
  Default with no keyword and a short genre prompt → `JOURNEY` (conf 0.5);
  otherwise → `STEADY` (conf 0.3). Confidence is a hand-tuned formula
  (`:602-608`), not a learned signal.

---

## Phase 2 — OpenAI usage

### The intent-parse call (verbatim) — `intent.py:1146-1159`

```python
import openai
client = openai.OpenAI(api_key=settings.openai_api_key)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": _LLM_INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ],
    response_format={"type": "json_object"},
    max_tokens=800,
    temperature=0.3,
)
```

- Model: `gpt-4o-mini`. Temperature `0.3`. `max_tokens=800`. **No `seed`.**
- `response_format={"type": "json_object"}` → this is **JSON mode, NOT
  structured outputs**. There is no `json_schema`, no function/tool definition.
  The model is free to emit any JSON object shape; nothing enforces the field
  set or types at the API layer.

### System prompt (verbatim) — `intent.py:1017-1134`

The full system prompt is the module constant `_LLM_INTENT_SYSTEM_PROMPT`
(`intent.py:1017`). It is long; key facts:
- It documents the desired JSON schema in prose (arc_type, arc_confidence,
  base_energy/darkness/tempo/texture, genre_hints, artist_seeds, mood_keywords,
  avoid_keywords, year_range, target_duration_minutes, prompt_type, genre_mode,
  dimension_weights, custom_waypoints).
- **Few-shot examples** are inline only as genre-expansion bullet lists
  (`:1065-1070`) and one-line musical-literacy hints (`:1127-1129`, e.g.
  `"Crushing doom" implies high darkness, low tempo...`). There are **no full
  input→JSON exemplars.**
- Ends with `"Return ONLY valid JSON, no other text."` (`:1134`).

### Structured-output enforcement — NO (prompt-and-pray + manual parse)

Parse + validation — `intent.py:1161-1181`:
```python
raw = response.choices[0].message.content
if not raw:
    logger.warning("LLM intent parsing returned empty content")
    return None
parsed = json.loads(raw.strip())
_validate_llm_intent(parsed)
...
except json.JSONDecodeError as e:
    logger.warning(...); return None
except Exception as e:
    logger.warning(...); return None
```

`_validate_llm_intent` (`intent.py:1184-1274`) is a hand-rolled coercion layer:
unknown `arc_type` → `"journey"` (`:1188-1189`); floats clamped to `[0,1]`
(`:1191-1197`); non-list fields forced to `[]` (`:1200-1204`); bad
`prompt_type`/`genre_mode` → defaults (`:1224-1232`). It validates **types and
enum membership only — it never checks `genre_hints` against the real library
vocabulary.** A genre like `"blackgaze"` or a hallucinated `"cascadian doomgaze"`
passes validation unchanged.

### Fallback path — present and graceful (degraded heuristic mode)

`_parse_prompt_with_llm` returns `None` on: no API key (`:1142-1144`), empty
content (`:1162-1164`), `JSONDecodeError` (`:1176-1178`), or any other exception
(`:1179-1181`). `parse_prompt` then routes to `_build_intent_from_keywords`
(`:1296-1297`) — a fully functional non-LLM mode. **Good:** the system never
hard-fails on LLM problems.

### Grounding — NONE

The system prompt is a **static module constant** (`intent.py:1017`). It is never
templated with the library's actual genres, Last.fm tags, scene-cluster labels,
or available artist names. The model emits free-text genres/artists with **no
knowledge of what exists in the 41k-track DB**. The taxonomy in `GENRE_ALIASES`
(`:254-466`) exists in the codebase but is never injected into the prompt.

### Caching, cost, call count

- **No caching anywhere on the parse path.** `parse_prompt` /
  `_parse_prompt_with_llm` carry no `@lru_cache`. (`lru_cache` exists only in
  `observability.py:264`, `textnorm.py:43/51`, `sequencer.py:31` — none on
  parse or generate.) Identical prompts re-hit OpenAI every time.
- Non-determinism: `temperature=0.3` with no `seed` → the same prompt can parse
  differently run-to-run.
- LLM calls **per playlist generate**: 1 for intent parsing + 1 (sometimes 2,
  on the `X of Y` title-retry at `title_generator.py:71-74`) for the title
  (`generate_playlist_title`, `routes_v3.py:1902`, `:2001`; model `gpt-4o-mini`,
  temp `0.7`, `max_tokens=30`, `title_generator.py:52-61`). So **2–3 calls per
  playlist**, all uncached. `enhance_prompt` (`routes_v3.py:1863`,
  `prompt_enhancer.py:194`) is a **separate `/enhance` endpoint**, not part of
  generate.

---

## Phase 3 — parse → scoring handoff

### The 4(+) scoring dimensions and weighting

The trajectory dimensions (energy, tempo, darkness, texture, + era/valence) are
turned into a `trajectory_curve` (`intent.py:1359-1370`) and scored per-position
inside `score_trajectory_match` (`candidates.py:857`). The **per-component weight
mix** is in `total_score` — `candidates.py:152-166`:

```python
self.semantic_score * self._w_semantic +
self.trajectory_score * self._w_trajectory +
self.genre_match_score * self._w_genre +
self.curation_score * self._w_curation +
self.year_score -
self.gravity_penalty * self._w_gravity - ...
```

The weighting is **a coarse hardcoded bucket keyed on `prompt_type`**, NOT a
continuous function of parse confidence — `get_adaptive_weights`
(`candidates.py:952-985`):

- `GENRE`  → semantic 0.29, trajectory 0.15, **genre 0.23**, gravity 0.15,
  duration 0.10, curation 0.08
- `ARC`    → semantic 0.10, **trajectory 0.45**, genre 0.16, ...
- `MIXED`  → semantic 0.28, trajectory 0.26, genre 0.15, ...

**Verifying the UI claims:** "arc-prompts = 40% trajectory" → real value is
**0.45** (`:971`). "genre-prompts = 35% genre" → **false**: genre weight for a
GENRE prompt is **0.23** (`:963`); the 0.35-ish genre emphasis instead shows up
as the keyword/BM25 boost (`kw_weight = 0.50 if GENRE else 0.35`,
`candidates.py:1110`) and the enhanced semantic query (`:1079-1083`). The bucket
is selected once from `intent.prompt_type` (`:1050`); `arc_confidence` exists
(`intent.py:137`) but **does not modulate the weights** — a 0.51-confidence and a
0.99-confidence arc get identical weighting.

### CRITICAL: how an LLM genre like "blackgaze" matches tracks

Two mechanisms, **both effectively exact-string**, neither embedding-based for
the label itself:

1. **Pool retrieval** (`candidates.py:1145-1156`, `:1172-1185`, `:1199-1214`):
   substring SQL `WHERE g.name ILIKE ANY(%s)` with patterns `f"%{g}%"`. Forgiving
   on substrings but still literal — `"blackgaze"` only retrieves rows whose
   genre/tag string contains `blackgaze`.
2. **Scoring** `compute_genre_match_score` (`candidates.py:173-224`): builds
   `hint_set` from `intent.genre_hints` + canonical families via
   `_ALIAS_TO_FAMILY` (`:1253-1258`), then scores by **exact set membership**:
   ```python
   for genre_name in genre_set_with_families:
       if genre_name not in hint_set:
           continue
   ```
   A track's genre contributes only if the exact string (or its
   `_ALIAS_TO_FAMILY` family) is in `hint_set`.

The only embedding-based route is the **hybrid query centroid**
(`candidates.py:1069-1083` → `build_hybrid_query_embedding`, `manifold.py:742`),
but it requires `get_genre_centroids` (`manifold.py:711-739`) to return a row,
which is keyed on `genre_family` resolved through `_ALIAS_TO_FAMILY` — **an
unknown LLM label falls through to `h.lower()` and matches no manifold row**, so
no centroid, no embedding bias.

**Silent-zero-match flag.** Any LLM-emitted label that is (a) not a literal
substring of any DB genre/tag and (b) not a key in `_ALIAS_TO_FAMILY`
(`intent.py:469-472`) contributes **0** to `genre_match_score` and pulls **0**
tracks into the genre/tag/year pools. Concrete failure sites:
- `candidates.py:1146` / `:1173` / `:1200` — pool ILIKE patterns silently return
  nothing for an unknown label.
- `candidates.py:210` — `if genre_name not in hint_set: continue` (the label is
  in `hint_set` but no track genre matches it → 0).
- `manifold.py:715` — unknown family → no centroid.
`blackgaze` happens to be in `GENRE_ALIASES` (`intent.py:260`, `:357`) so it
survives; but the LLM is explicitly told to invent siblings (`intent.py:1062`)
and is given no vocabulary list, so out-of-taxonomy labels are likely and fail
silently. There is **no log line** when a hint maps to zero tracks.

### Artist references — PARSED THEN DROPPED in production

`artist_seeds` is populated on both parse branches (`intent.py:1326`, `:1478`),
but its **only consumer is the legacy composer**:
`service/app/trajectory/composer.py:169`
(`seed_artist_ids = get_artist_ids_by_name(intent.artist_seeds)`). A full-repo
grep shows **no reference to `artist_seeds` in `composer_v4.py`,
`candidates.py`, or `sequencer.py`**. Since production runs `composer_v4`
(`main.py:19`, `routes_v3.py:35`), **artist references in the prompt are
extracted, validated, logged (`intent.py:1457`), and then completely ignored.**
There is no MBID lookup, no Last.fm similar-artists expansion, and no embedding
anchor for the referenced artist anywhere in the v4 path. An absent artist is
"handled gracefully" only because the whole feature is dead.

### Exclusions — soft post-score penalty, unreliable

`avoid_keywords` are applied **after scoring**, never as a pre-filter:
- Penalty: `compute_negative_constraint_penalty` (`candidates.py:227-260`),
  capped at `min(0.45, penalty)` (`:260`). Exact-phrase substring hit = +0.25;
  full-token overlap = +0.18; partial = +0.10.
- Subtracted full-weight in `total_score` (`candidates.py:162`).
- Hard exclusion only via the admissibility gate
  (`admission.py:28`): `if negative_constraint_penalty >= neg_constraint_ceiling:
  return False`, with `neg_constraint_ceiling = 0.35` (ARC) / `0.45` (other)
  (`candidates.py:1357`).

**Reliability problem:** since the penalty is capped at exactly `0.45` and the
ceiling for non-ARC prompts is `0.45`, a track is hard-excluded only if it hits
the absolute maximum penalty (multiple exact matches). A single `"no synths"`
yields 0.25 → the track is merely down-ranked by 0.25 and can still appear.
Exclusions are therefore best-effort, not guarantees.

---

## Phase 4 — Proposals (ranked by impact ÷ effort)

> Not implemented. Each: file:line · current · why it hurts · fix · effort ·
> risk.

### P1 — Wire `artist_seeds` into the v4 pipeline (or remove the feature)
- **Where:** `composer_v4.py` / `candidates.py` (absent); parsed at
  `intent.py:1326`, `:1478`; dead consumer at `composer.py:169`.
- **Current:** artist references parsed, validated, logged, then discarded in
  production.
- **Why it hurts:** "like Bohren", "similar to Slowdive" silently does nothing —
  a headline capability the parser advertises is non-functional.
- **Fix:** resolve `artist_seeds` → artist IDs (reuse
  `get_artist_ids_by_name`), pull their track/artist embeddings, and add a
  seed-similarity term to candidate scoring (or blend into the query embedding
  like `build_hybrid_query_embedding`). Gracefully skip absent artists with a log
  line. If not worth it, delete the field to stop misleading callers.
- **Effort:** M · **Risk:** M (new scoring term → must pass `eval-changes`).
- **Impact/effort:** highest — restores a whole advertised dimension.

### P2 — Ground the LLM parse in the real library vocabulary
- **Where:** `intent.py:1017` (static system prompt); `:1150-1159` (call).
- **Current:** prompt never sees DB genres/tags/scene labels/artists; model
  emits free-text and is *instructed* to invent siblings (`:1062-1070`).
- **Why it hurts:** out-of-taxonomy labels silently match zero tracks (Phase 3).
- **Fix:** inject a curated, cached vocabulary slice into the system prompt — top
  N library genres + high-weight Last.fm tags + scene-cluster labels (data
  already queryable, cf. `database_pg.py:795-832`, `:1018-1036`). Instruct the
  model to choose only from the provided list (plus a free-text `notes` field).
  Cache the vocabulary string (refresh on sync), not per request.
- **Effort:** M · **Risk:** L (prompt-only; fallback unchanged).
- **Impact/effort:** very high — removes the root cause of zero-match genres.

### P3 — Enforce structured output (json_schema) instead of JSON mode
- **Where:** `intent.py:1156` (`response_format={"type":"json_object"}`),
  `:1184-1274` (manual coercion).
- **Current:** prompt-and-pray JSON mode + hand-rolled `_validate_llm_intent`.
- **Why it hurts:** model can omit/mistype fields; coercion silently rewrites
  (e.g. any bad arc → `journey`), masking parse failures as confident output.
- **Fix:** define a strict JSON Schema (or a Pydantic model exported via
  `response_format={"type":"json_schema", ...}` with `strict: true`). Keep
  `_validate_llm_intent` as a thin clamp for value ranges. Add a `seed` for
  determinism (pairs with P6).
- **Effort:** S–M · **Risk:** L (gpt-4o-mini supports structured outputs; keep
  keyword fallback for any failure).
- **Impact/effort:** high.

### P4 — Post-parse genre snapping to nearest known tag (embedding) + logged confidence
- **Where:** after `genre_hints` assembled — `intent.py:1321-1325` (LLM),
  `:1469-1473` (keyword).
- **Current:** unknown labels flow straight to exact-match scoring → 0.
- **Why it hurts:** no safety net between a hallucinated label and silent
  zero-match; no observability.
- **Fix:** for each hint not in `_ALIAS_TO_FAMILY` and not a DB-genre substring,
  embed it and snap to the nearest library genre/tag/manifold centroid above a
  similarity threshold; record `(original, snapped, score)` and log it. Below
  threshold → drop with a warning rather than carry a dead hint.
- **Effort:** M · **Risk:** M (could over-snap; gate by threshold + eval).
- **Impact/effort:** high (depends partly on P2 reducing how often it fires).

### P5 — Make exclusions reliable (hard pre-filter for explicit avoids)
- **Where:** `candidates.py:227-260`, `:1357`; `admission.py:28`.
- **Current:** soft penalty capped at 0.45, hard-cut only at the 0.45 ceiling →
  single-term avoids never actually exclude.
- **Why it hurts:** "no live", "without synths" still leak through.
- **Fix:** treat high-confidence explicit avoids (exact phrase / genre-name
  match) as a pre-score hard filter on title/artist/album/genre fields; keep the
  graded penalty only for fuzzy/partial matches. Distinguish "avoid genre X"
  (filterable against `track.genres`) from "avoid vague-mood".
- **Effort:** S–M · **Risk:** M (over-filtering small pools — add a floor that
  reverts to penalty mode if it empties the pool).
- **Impact/effort:** high.

### P6 — Cache + determinism keyed on normalized prompt
- **Where:** `parse_prompt` (`intent.py:1277`); no cache today.
- **Current:** every generate re-calls OpenAI (2–3 calls); `temperature=0.3` no
  `seed` → non-deterministic parses.
- **Why it hurts:** cost/latency on repeats; identical prompts yield different
  playlists, hurting reproducibility and the eval loop.
- **Fix:** normalize prompt text (reuse `textnorm`) and cache the parsed
  `llm_data`/`PlaylistIntent` (in-process LRU or a DB/Redis table keyed on
  `(normalized_prompt, model, schema_version)`). Add `seed=` to the API call.
- **Effort:** S · **Risk:** L (must key on prompt **and** target_size + schema
  version to avoid stale hits).
- **Impact/effort:** high (cheap, immediate cost/latency/eval win).

### P7 — Scoring weights as a function of parse confidence, not a 3-way bucket
- **Where:** `get_adaptive_weights` (`candidates.py:952-985`), selected at
  `:1050`; `arc_confidence` unused for weighting (`intent.py:137`).
- **Current:** three frozen weight vectors; `arc_confidence` and (proposed)
  genre-snap confidence ignored.
- **Why it hurts:** a barely-detected arc gets the same 0.45 trajectory weight as
  an explicit one; coarse buckets fight nuanced prompts.
- **Fix:** interpolate weights continuously from `arc_confidence`,
  genre-hint strength, and parse confidence (e.g. lerp between ARC and GENRE
  vectors). Keep current vectors as the confident endpoints.
- **Effort:** M · **Risk:** M–L (changes scoring everywhere → full
  `eval-changes` run mandatory).
- **Impact/effort:** medium.

### P8 — Unify the sibling-genre graph (single source of truth)
- **Where:** `_RELATED_FAMILIES` (`intent.py:478-503`) vs the inline lists in the
  system prompt (`intent.py:1065-1070`) vs library-derived
  `get_adjacent_genres` (`manifold.py`, used at `candidates.py:1281`).
- **Current:** three overlapping, drifting definitions; the hand-curated graph is
  not derived from the library.
- **Why it hurts:** expansion and prompt guidance disagree; maintenance hazard;
  invented relationships may not reflect the actual collection.
- **Fix:** derive sibling families from tag co-occurrence / manifold adjacency
  once, persist, and have both `expand_genre_hints` and the (grounded, P2) prompt
  read from it.
- **Effort:** M · **Risk:** L–M (changes expansion → eval).
- **Impact/effort:** medium (compounds with P2/P4).

### Suggested order
P6 (cheap, immediate) → P3 (enforce schema) → P2 (ground) → P4 (snap) → P5
(exclusions) → P1 (artists) → P7 (confidence weights) → P8 (unify graph). P2+P4
together close the silent-zero-match hole; P3+P6 harden and cheapen the call;
P1 restores a dead feature.

---

*Per the Algorithm Change Policy (`CLAUDE.md`), any of P1/P4/P5/P7/P8 that touch
`trajectory/` or `genre/` scoring must pass `eval-changes` before being
considered complete.*

---

## Implementation status (2026-06-15)

All eight proposals are implemented. Toggles are config defaults read from env at
boot (see `service/app/config.py`; not in the settings registry).

| # | Proposal | Where | Tests |
|---|----------|-------|-------|
| P1 | Artist seeds wired into v4 | `candidates.py:get_artist_seed_embedding()` + query-embedding blend (`settings.artist_seed_weight`) | live eval (Lebanon Hanover pulled in) |
| P2 | Grounded parse in library vocab | `library_vocab.build_vocabulary_prompt_block()` injected via `intent._build_intent_system_prompt()` | live eval |
| P3 | Enforced structured output | `intent._LLM_INTENT_SCHEMA` + `response_format=json_schema` (strict) in `_call_intent_llm()`, JSON-mode fallback | live eval |
| P4 | Genre snapping to nearest known tag | `library_vocab.snap_genres()` via `intent._ground_and_expand_genres()`, logged confidence | live eval |
| P5 | Reliable hard exclusions | `intent.extract_hard_avoid_keywords()` + `candidates.compute_genre_exclusion()` with pool-floor guard | `test_hard_avoid.py` |
| P6 | Cache + determinism | `intent._RAW_PARSE_CACHE` (normalized prompt + schema version) + `_cached_prompt_embedding` + `seed` | live eval |
| P7 | Confidence-driven weights | `candidates.get_adaptive_weights(intent)` interpolates GENRE/ARC/MIXED by `arc_confidence`/`genre_confidence` | `test_adaptive_weights.py` |
| P8 | Unified sibling-genre graph | `manifold.GENRE_GRAPH` + `get_related_families()`; `_RELATED_FAMILIES` removed; `expand_genre_hints` + sequencer read it | `test_genre_graph_unify.py` |

**Config toggles** (`config.py`): `openai_intent_model`, `intent_grounding_enabled`,
`genre_snapping_enabled`, `genre_snap_min_similarity`, `intent_parse_cache_enabled`,
`intent_parse_seed`, `artist_seed_weight`.

**No DB migrations** were required — all changes are code + config; `init_database()`
is unchanged.
