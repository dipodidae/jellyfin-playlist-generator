# In-App Settings Page — Design

**Date:** 2026-06-09
**Status:** Approved (design); pending implementation plan

## Problem

All third-party credentials and tunable config currently live in `.env` and are
read once at process start by a pydantic `Settings` singleton (`service/app/config.py`).
Changing a key means editing `.env`, rebuilding/recreating the container, and there is
no in-app way to see what is configured or to authenticate Discogs via OAuth. The owner
wants every settable value managed from a settings page in the app, with the database as
the single source of truth, so `.env` no longer holds these concerns.

## Goals

- A settings page in the Nuxt frontend where every app-level setting can be viewed and edited.
- Postgres is the single source of truth for these settings; values take effect live (no restart).
- Discogs supports a full 3-legged OAuth 1.0a flow initiated from the page, with consumer
  key/secret as an always-works fallback.
- Secrets stored plaintext (same trust level as today's `.env`), masked in API responses.

## Non-Goals

- No encryption at rest (explicitly chosen: plaintext, single-user homelab behind SWAG + basic auth).
- No triggering of enrichment/backfill from this page (separate concern).
- No per-setting audit history, no multi-user roles/permissions.
- No OAuth for non-Discogs services (Last.fm/OpenAI/MusicBrainz are plain keys/values).

## Decisions (from brainstorming)

- **Architecture:** Approach A — keep the existing `settings` pydantic singleton, overlay DB
  values onto it at startup and on every save. Justified by single uvicorn process (no
  `--workers`), so in-memory mutation is globally visible; ~60 existing `settings.<key>` reads
  stay untouched.
- **Source of truth:** DB only. `.env` is ignored after a one-time seed.
- **First-boot seed (startup behavior, no toggle):** on startup, for any registry key absent
  from the table, seed the row from the matching env var if present. Idempotent — never
  overwrites an existing row, so it only ever acts on the first boot of a fresh DB. Migrates
  existing working keys (e.g. `LASTFM_API_KEY`, `OPENAI_API_KEY`) once, after which `.env`
  can be emptied.
- **Secret storage:** plaintext strings in the DB.
- **Discogs:** full OAuth 1.0a flow, with key/secret fallback so enrichment works immediately.

## Irreducible env exceptions (NOT in the settings table)

- `DATABASE_URL` — chicken-and-egg; can't store the DB connection string in the DB.
- `AUTH_USER` / `AUTH_PASS` — baked into the nginx htpasswd at container start.

Everything else moves to the DB: Last.fm key/secret, OpenAI key, Discogs (token / consumer
key+secret / OAuth access token+secret), MusicBrainz contact (+ app name/version), RYM
enable + delays, scan threads, music dirs, M3U output dir, Jellyfin URL/key/user/path
prefixes, embedding model version, and the clustering/UMAP/HDBSCAN params.

## Complete settable inventory

Every field in `config.py` is mapped below. The registry MUST cover all "DB-settable" rows;
the implementation is not complete until each appears in the settings page.

| `config.py` field | group | type | notes |
|---|---|---|---|
| `lastfm_api_key` | credentials | secret | |
| `lastfm_api_secret` | credentials | secret | |
| `openai_api_key` | credentials | secret | |
| `discogs_token` | credentials | secret | personal access token |
| `discogs_consumer_key` | credentials | secret | |
| `discogs_consumer_secret` | credentials | secret | |
| `discogs_oauth_token` | credentials | secret | **new** — set by OAuth callback |
| `discogs_oauth_token_secret` | credentials | secret | **new** — set by OAuth callback |
| `musicbrainz_contact` | credentials | str | email, MB ToS |
| `musicbrainz_app_name` | advanced | str | |
| `musicbrainz_app_version` | advanced | str | |
| `rym_scrape_enabled` | enrichment | bool | |
| `rym_scrape_delay_min` | enrichment | float | |
| `rym_scrape_delay_max` | enrichment | float | |
| `jellyfin_url` | jellyfin | str | |
| `jellyfin_api_key` | jellyfin | secret | |
| `jellyfin_user_id` | jellyfin | str | |
| `jellyfin_path_prefix` | jellyfin | str | |
| `local_path_prefix` | jellyfin | str | |
| `music_directories` | library | csv | |
| `scan_threads` | library | int | |
| `m3u_output_dir` | library | str | |
| `embedding_model_version` | advanced | int | |
| `cluster_min_tracks` | advanced | int | |
| `cluster_secondary_weight_threshold` | advanced | float | |
| `cluster_max_per_artist` | advanced | int | |
| `cluster_random_state` | advanced | int | |
| `cluster_min_cluster_size` | advanced | int | |
| `cluster_min_samples` | advanced | int | |
| `cluster_umap_n_components` | advanced | int | |
| `cluster_umap_n_neighbors` | advanced | int | |
| `cluster_umap_min_dist` | advanced | float | |
| `cluster_merge_threshold` | advanced | float | |
| `cluster_noise_weight` | advanced | float | |
| `cluster_tag_weight` | advanced | float | |

**Not in the registry (intentional):**
- `database_url` — env-only bootstrap (chicken-and-egg).
- `database_path` — deprecated legacy DuckDB path; dropped from the page entirely.
- `AUTH_USER` / `AUTH_PASS` / `TZ` — infra, baked at container start (not `config.py` fields).

## Data Layer

### Migration `012_app_settings.sql`

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

Values are stored as strings; typed coercion (bool / int / float / str / csv-list) happens
on load, driven by the registry.

### Settings registry (`config.py`)

A declarative list — the single source that drives load/coerce, the API schema, and the
frontend form. Each entry:

| field | meaning |
|---|---|
| `key` | matches the `Settings` attribute name and the env var (upper-cased) |
| `type` | `str` \| `secret` \| `bool` \| `int` \| `float` \| `csv` |
| `group` | `credentials` \| `enrichment` \| `jellyfin` \| `library` \| `advanced` |
| `label` | human label for the form |
| `default` | fallback when unset in DB and env |
| `secret` | if true, masked in API responses |

Adding a future setting = one registry entry (no separate frontend/API edits).

### Load / reload

- `reload_settings()`: read all `app_settings` rows, coerce per registry, `setattr` onto the
  `settings` singleton. Called at startup (after env load + seed) and after every successful `PUT`.
- Seed-once: at startup, for each registry key with no DB row, if the env var is set, insert a row.

## Backend API (`routes_v3.py` + a `settings` module)

- `GET /settings` — registry (groups/labels/types) merged with current values. Secret fields
  masked: return `{is_set: bool, masked: "••••Cwk6"}` instead of the raw value.
- `PUT /settings` — partial `{key: value}` map. Validate types against registry, write rows,
  call `reload_settings()`. **Sentinel rule:** a secret submitted equal to its mask (or blank)
  is ignored — saving the form never overwrites a secret with its mask.
- `POST /settings/test/{group}` — lightweight credential check per group:
  - Last.fm: a no-auth read call (e.g. `track.getInfo`/`artist.getInfo`).
  - OpenAI: `GET /v1/models`.
  - Discogs: `GET /database/search?q=test` with current auth tier.
  - MusicBrainz: a trivial lookup with the contact UA.
  Returns `{ok: bool, message: str}`.

### Discogs OAuth 1.0a (3-legged)

- `POST /settings/discogs/oauth/start` — using stored consumer key/secret, call Discogs
  `oauth/request_token`; store the temp request-token secret; return `authorize_url`.
- `GET /settings/discogs/oauth/callback?oauth_token=…&oauth_verifier=…` — exchange for the
  permanent access token + access-token secret; store both; clear the temp secret.
- Callback base URL derives from the request host → `https://playlist-generator.4eva.me/api/settings/discogs/oauth/callback` through SWAG; no new config var.
- `discogs.py` auth tiers in priority order: **OAuth access token (HMAC-SHA1 signed) →
  consumer key+secret header → personal token**. Add a minimal OAuth 1.0a signer (hand-rolled
  ~30 lines or the lightest available helper; no new heavy dependency).

## Frontend (`frontend/app/pages/settings.vue`)

- New page linked in the existing nav (with index/eval/observatory), behind the same
  `nuxt-auth-utils` basic-auth gate.
- Nuxt UI v4, registry-driven: fetches `GET /settings`, renders groups as sections —
  *Credentials*, *Enrichment*, *Jellyfin*, *Library*, and an *Advanced* collapsible
  (clustering/UMAP/HDBSCAN). No hardcoded field list.
- Field rendering by type: secrets → password input showing `••••last4` with hint
  "leave blank to keep current"; booleans → toggles; numbers → numeric inputs.
- Per-credential-group **Test** button → `POST /settings/test/{group}`, inline green/red result.
- Discogs group: **Connect with Discogs** button → calls OAuth start, opens authorize URL in a
  new tab; on callback success the page refreshes and shows status:
  "Connected (OAuth)" / "Using key/secret" / "Not configured".
- Save posts only changed fields via `PUT /settings`; masked-unchanged secrets skipped client-side.
  Success toast; values live immediately.
- Nuxt server proxy under `frontend/server/api/settings/…` forwards to the backend (keeps
  backend URL private, consistent with existing routes).

## Error Handling

- `PUT` type-validation failures → 422 with the offending key; frontend shows field error.
- OAuth start with missing consumer key/secret → 400 with a clear "set Discogs consumer
  key/secret first" message.
- OAuth callback failure (denied/expired verifier) → redirect back to settings with an error toast.
- Test endpoints never throw; always `{ok, message}`.

## Testing

- **pytest:** registry coercion (each type); mask/unmask sentinel logic; `PUT` validation;
  env seed-once behavior (seeds when absent, does not clobber existing rows); mocked Discogs
  OAuth round-trip (request-token → callback → stored access token); `_auth_header()` tier precedence.
- **Smoke:** `python scripts/test_scripts.py`-style import check passes.
- **Frontend:** lint pass; manual verification of the page render + save + test buttons.

## Documentation updates (same commit)

Per the repo's Documentation Freshness Policy: `AGENTS.md` (new env→DB settings model, new
endpoints, new table), `README.md` (Configuration section + API reference), `CLAUDE.md`
(settings page + reload gotcha), and `.env.example` (note that listed keys are now seed-only).

## Rollout

1. Apply migration `012_app_settings.sql`.
2. Deploy; startup seeds the table from current `.env`.
3. Verify the page shows existing keys as configured; complete Discogs OAuth if desired.
4. Optionally empty the migrated keys from `.env` (leave `DATABASE_URL`, `AUTH_*`).
