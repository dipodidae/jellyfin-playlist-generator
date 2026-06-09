# In-App Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every app-level config value (API keys, enrichment toggles, Jellyfin, library, clustering params) out of `.env` into a DB-backed settings table editable from a new in-app settings page, with a full Discogs OAuth flow.

**Architecture:** A declarative settings registry drives load/coerce, the API, and the form. On startup the app seeds the `app_settings` table from env (once, idempotent) and overlays DB values onto the existing pydantic `settings` singleton; every save re-overlays live. Single uvicorn process makes in-memory mutation globally visible — no cache/TTL needed. Frontend is a registry-driven Nuxt UI v4 page calling `/api/settings` (proxied to the backend by existing nitro routeRules).

**Tech Stack:** FastAPI, psycopg2 (ThreadedConnectionPool), pydantic-settings, PostgreSQL, Nuxt 4 + Nuxt UI v4, pytest.

**Spec:** `docs/superpowers/specs/2026-06-09-in-app-settings-page-design.md`

**Deviations from spec (deliberate, codebase-driven):**
- No Nuxt server proxy route — the app already proxies `/api/**` to the backend via `nitro.routeRules`. The page calls `/api/settings`.
- Discogs OAuth uses the **PLAINTEXT** signature method (supported by Discogs over HTTPS, per their OAuth docs) instead of HMAC-SHA1 — simpler and no base-string construction.
- The `app_settings` table is created both by a numbered migration file (manual flow) and by `init_database()` (so it always exists at startup).

---

## File Structure

**Backend (create):**
- `service/app/settings_registry.py` — registry list + pure helpers (coerce, mask, sentinel). No DB/network imports → fully unit-testable.
- `service/app/settings_store.py` — DB-backed load/reload/save/seed, depends on registry + `database_pg` + `config`.
- `service/app/api/routes_settings.py` — `/settings*` endpoints on their own `APIRouter`.
- `service/app/ingestion/discogs_oauth.py` — PLAINTEXT OAuth header builder + request-token/access-token exchange helpers.
- `service/app/migrations/012_app_settings.sql` — the table migration.
- `service/app/tests/test_settings_registry.py`, `service/app/tests/test_discogs_oauth.py` — unit tests.

**Backend (modify):**
- `service/app/database_pg.py` — add `app_settings` table to `init_database()`.
- `service/app/main.py` — lifespan: seed + reload after `init_database()`; include settings router.
- `service/app/ingestion/discogs.py` — add OAuth access-token tier to `_auth_header()` / request auth.

**Frontend (create):**
- `frontend/app/types/settings.ts` — TS types.
- `frontend/app/composables/useSettings.ts` — fetch/save/test/oauth.
- `frontend/app/pages/settings.vue` — the page.

**Frontend (modify):**
- `frontend/app/layouts/default.vue` — add Settings nav link.

**Docs (modify):** `AGENTS.md`, `README.md`, `CLAUDE.md`, `.env.example`.

---

## Task 1: Create the `app_settings` table

**Files:**
- Create: `service/app/migrations/012_app_settings.sql`
- Modify: `service/app/database_pg.py` (inside `init_database()`, after the `sync_metadata` table block ~line 418-426)

- [ ] **Step 1: Write the migration file**

Create `service/app/migrations/012_app_settings.sql`:

```sql
-- 012_app_settings.sql
-- Key/value store for runtime-editable application settings (source of truth,
-- overlaid onto the config singleton at startup and on every save).
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

- [ ] **Step 2: Add the same table to `init_database()`**

In `service/app/database_pg.py`, find the `sync_metadata` `CREATE TABLE IF NOT EXISTS` block (~line 418) and add immediately after its `cur.execute(...)` call:

```python
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)
```

- [ ] **Step 3: Verify Python still imports**

Run: `cd service && python -c "import app.database_pg"`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add service/app/migrations/012_app_settings.sql service/app/database_pg.py
git commit -m "feat(settings): add app_settings table (migration + init_database)"
```

---

## Task 2: Settings registry + pure helpers

**Files:**
- Create: `service/app/settings_registry.py`
- Test: `service/app/tests/test_settings_registry.py`

- [ ] **Step 1: Write failing tests**

Create `service/app/tests/test_settings_registry.py`:

```python
import pytest

from app.settings_registry import (
    REGISTRY,
    SettingDef,
    coerce_value,
    mask_value,
    is_unchanged_secret,
    registry_by_key,
)


def test_registry_keys_are_unique():
    keys = [s.key for s in REGISTRY]
    assert len(keys) == len(set(keys))


def test_registry_covers_expected_keys():
    keys = registry_by_key()
    # Spot-check one from each group plus the new OAuth fields.
    for k in ["lastfm_api_key", "discogs_oauth_token", "rym_scrape_enabled",
              "jellyfin_url", "scan_threads", "cluster_min_samples"]:
        assert k in keys
    # Bootstrap/deprecated keys must NOT be settable.
    assert "database_url" not in keys
    assert "database_path" not in keys


def test_coerce_bool():
    assert coerce_value("bool", "true") is True
    assert coerce_value("bool", "false") is False
    assert coerce_value("bool", "1") is True
    assert coerce_value("bool", "0") is False


def test_coerce_int_and_float():
    assert coerce_value("int", "8") == 8
    assert coerce_value("float", "0.05") == 0.05


def test_coerce_csv_and_str():
    assert coerce_value("csv", "/music, /more") == "/music, /more"
    assert coerce_value("str", "hello") == "hello"
    assert coerce_value("secret", "sk-abc") == "sk-abc"


def test_mask_value_shows_last_four():
    assert mask_value("sk-proj-ABCD1234Cwk6") == "••••Cwk6"


def test_mask_value_short_or_empty():
    assert mask_value("") == ""
    assert mask_value("ab") == "••••"


def test_is_unchanged_secret_detects_mask_and_blank():
    assert is_unchanged_secret("••••Cwk6") is True
    assert is_unchanged_secret("") is True
    assert is_unchanged_secret("a-real-new-value") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd service && python -m pytest app/tests/test_settings_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.settings_registry'`.

- [ ] **Step 3: Implement the registry**

Create `service/app/settings_registry.py`:

```python
"""Declarative registry of runtime-editable settings + pure helpers.

This module has NO database or network imports so it stays trivially testable.
Each SettingDef.key matches an attribute on the config `settings` singleton AND
its upper-cased env var name.
"""

from __future__ import annotations

from dataclasses import dataclass

# type ∈ {"str", "secret", "bool", "int", "float", "csv"}
# group ∈ {"credentials", "enrichment", "jellyfin", "library", "advanced"}


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: str
    group: str
    label: str
    secret: bool = False


REGISTRY: list[SettingDef] = [
    # credentials
    SettingDef("lastfm_api_key", "secret", "credentials", "Last.fm API key", secret=True),
    SettingDef("lastfm_api_secret", "secret", "credentials", "Last.fm API secret", secret=True),
    SettingDef("openai_api_key", "secret", "credentials", "OpenAI API key", secret=True),
    SettingDef("discogs_token", "secret", "credentials", "Discogs personal token", secret=True),
    SettingDef("discogs_consumer_key", "secret", "credentials", "Discogs consumer key", secret=True),
    SettingDef("discogs_consumer_secret", "secret", "credentials", "Discogs consumer secret", secret=True),
    SettingDef("discogs_oauth_token", "secret", "credentials", "Discogs OAuth token", secret=True),
    SettingDef("discogs_oauth_token_secret", "secret", "credentials", "Discogs OAuth token secret", secret=True),
    SettingDef("musicbrainz_contact", "str", "credentials", "MusicBrainz contact email"),
    # enrichment
    SettingDef("rym_scrape_enabled", "bool", "enrichment", "Enable RYM scraping"),
    SettingDef("rym_scrape_delay_min", "float", "enrichment", "RYM delay min (s)"),
    SettingDef("rym_scrape_delay_max", "float", "enrichment", "RYM delay max (s)"),
    # jellyfin
    SettingDef("jellyfin_url", "str", "jellyfin", "Jellyfin URL"),
    SettingDef("jellyfin_api_key", "secret", "jellyfin", "Jellyfin API key", secret=True),
    SettingDef("jellyfin_user_id", "str", "jellyfin", "Jellyfin user ID"),
    SettingDef("jellyfin_path_prefix", "str", "jellyfin", "Jellyfin path prefix"),
    SettingDef("local_path_prefix", "str", "jellyfin", "Local path prefix"),
    # library
    SettingDef("music_directories", "csv", "library", "Music directories (comma-separated)"),
    SettingDef("scan_threads", "int", "library", "Scan threads"),
    SettingDef("m3u_output_dir", "str", "library", "M3U output directory"),
    # advanced
    SettingDef("public_base_url", "str", "advanced", "Public base URL (for OAuth callbacks, e.g. https://playlist-generator.4eva.me)"),
    SettingDef("musicbrainz_app_name", "str", "advanced", "MusicBrainz app name"),
    SettingDef("musicbrainz_app_version", "str", "advanced", "MusicBrainz app version"),
    SettingDef("embedding_model_version", "int", "advanced", "Embedding model version"),
    SettingDef("cluster_min_tracks", "int", "advanced", "Cluster: min tracks/artist"),
    SettingDef("cluster_secondary_weight_threshold", "float", "advanced", "Cluster: secondary weight threshold"),
    SettingDef("cluster_max_per_artist", "int", "advanced", "Cluster: max clusters/artist"),
    SettingDef("cluster_random_state", "int", "advanced", "Cluster: random state"),
    SettingDef("cluster_min_cluster_size", "int", "advanced", "HDBSCAN: min cluster size"),
    SettingDef("cluster_min_samples", "int", "advanced", "HDBSCAN: min samples"),
    SettingDef("cluster_umap_n_components", "int", "advanced", "UMAP: n_components"),
    SettingDef("cluster_umap_n_neighbors", "int", "advanced", "UMAP: n_neighbors"),
    SettingDef("cluster_umap_min_dist", "float", "advanced", "UMAP: min_dist"),
    SettingDef("cluster_merge_threshold", "float", "advanced", "Cluster: merge threshold"),
    SettingDef("cluster_noise_weight", "float", "advanced", "Cluster: noise weight"),
    SettingDef("cluster_tag_weight", "float", "advanced", "Cluster: tag weight"),
]


def registry_by_key() -> dict[str, SettingDef]:
    return {s.key: s for s in REGISTRY}


def coerce_value(type_: str, raw: str):
    """Coerce a stored string value to its typed Python form."""
    if type_ == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if type_ == "int":
        return int(raw)
    if type_ == "float":
        return float(raw)
    # str, secret, csv all stay strings
    return raw


def mask_value(value: str) -> str:
    """Mask a secret for display: last 4 chars only."""
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


def is_unchanged_secret(submitted: str) -> bool:
    """True when a submitted secret is blank or still its mask (→ do not overwrite)."""
    if submitted == "":
        return True
    return submitted.startswith("••••")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd service && python -m pytest app/tests/test_settings_registry.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add service/app/settings_registry.py service/app/tests/test_settings_registry.py
git commit -m "feat(settings): declarative registry + pure coerce/mask/sentinel helpers"
```

---

## Task 3: Settings store (DB load / reload / save / seed)

**Files:**
- Create: `service/app/settings_store.py`
- Test: `service/app/tests/test_settings_store.py`

- [ ] **Step 1: Write failing tests (pure parts, DB mocked)**

Create `service/app/tests/test_settings_store.py`:

```python
from app import settings_store
from app.config import settings


def test_apply_overlays_typed_values_onto_singleton(monkeypatch):
    monkeypatch.setattr(settings, "scan_threads", 8, raising=False)
    monkeypatch.setattr(settings, "rym_scrape_enabled", False, raising=False)
    settings_store._apply_rows({"scan_threads": "16", "rym_scrape_enabled": "true"})
    assert settings.scan_threads == 16
    assert settings.rym_scrape_enabled is True


def test_apply_ignores_unknown_keys(monkeypatch):
    settings_store._apply_rows({"not_a_real_key": "x"})
    assert not hasattr(settings, "not_a_real_key")


def test_seed_payload_only_includes_set_env_for_missing_keys():
    existing = {"lastfm_api_key"}  # already in DB
    env = {"LASTFM_API_KEY": "k1", "OPENAI_API_KEY": "k2", "DISCOGS_TOKEN": ""}
    payload = settings_store._seed_payload(existing, env)
    # lastfm already present → skipped; discogs empty → skipped; openai set+missing → seeded
    assert payload == {"openai_api_key": "k2"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd service && python -m pytest app/tests/test_settings_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.settings_store'`.

- [ ] **Step 3: Implement the store**

Create `service/app/settings_store.py`:

```python
"""DB-backed settings: load/reload/save/seed.

The DB is the source of truth. At startup we seed missing rows from env (once,
idempotent), then overlay all rows onto the `settings` singleton. Every save
re-overlays so values take effect live (single uvicorn process).
"""

import logging
import os

from app.config import settings
from app.database_pg import get_cursor
from app.settings_registry import REGISTRY, coerce_value, registry_by_key

logger = logging.getLogger(__name__)


def _apply_rows(rows: dict[str, str]) -> None:
    """Overlay raw string rows onto the settings singleton, coercing per registry."""
    defs = registry_by_key()
    for key, raw in rows.items():
        sdef = defs.get(key)
        if sdef is None:
            continue  # unknown / bootstrap key — ignore
        if raw is None:
            continue
        try:
            setattr(settings, key, coerce_value(sdef.type, raw))
        except (ValueError, TypeError) as e:
            logger.warning("Skipping bad setting %s=%r: %s", key, raw, e)


def load_rows() -> dict[str, str]:
    """Read all rows from app_settings."""
    with get_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT key, value FROM app_settings")
        return {r["key"]: r["value"] for r in cur.fetchall()}


def reload_settings() -> None:
    """Re-read the table and overlay onto the singleton."""
    _apply_rows(load_rows())


def save(updates: dict[str, str]) -> None:
    """Upsert the given key→value rows, then reload onto the singleton."""
    if updates:
        with get_cursor() as cur:
            for key, value in updates.items():
                cur.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (key) DO UPDATE
                        SET value = EXCLUDED.value, updated_at = now()
                    """,
                    (key, value),
                )
    reload_settings()


def _seed_payload(existing_keys: set[str], env: dict[str, str]) -> dict[str, str]:
    """Compute {key: value} to seed: registry keys absent from DB whose env var is set."""
    payload: dict[str, str] = {}
    for sdef in REGISTRY:
        if sdef.key in existing_keys:
            continue
        env_val = env.get(sdef.key.upper(), "")
        if env_val != "":
            payload[sdef.key] = env_val
    return payload


def seed_from_env() -> None:
    """One-time idempotent seed: insert rows for registry keys missing from the DB
    whose matching env var is set. Never overwrites an existing row."""
    existing = set(load_rows().keys())
    payload = _seed_payload(existing, dict(os.environ))
    if payload:
        with get_cursor() as cur:
            for key, value in payload.items():
                cur.execute(
                    "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO NOTHING",
                    (key, value),
                )
        logger.info("Seeded %d setting(s) from env: %s", len(payload), sorted(payload))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd service && python -m pytest app/tests/test_settings_store.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add service/app/settings_store.py service/app/tests/test_settings_store.py
git commit -m "feat(settings): DB-backed store with env seed + live reload onto singleton"
```

---

## Task 4: Wire seed + reload into startup

**Files:**
- Modify: `service/app/main.py` (lifespan, ~lines 27-35)

- [ ] **Step 1: Update the lifespan to seed + reload (PostgreSQL path only)**

In `service/app/main.py`, replace the `lifespan` function body so that after `init_database()` it seeds and reloads settings. Use the existing `USE_POSTGRES` flag:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_database()
    logger.info("Database initialized")
    if USE_POSTGRES:
        from app.settings_store import seed_from_env, reload_settings
        seed_from_env()
        reload_settings()
        logger.info("Settings loaded from DB")
    yield
    logger.info("Shutting down...")
    close_pool()
```

- [ ] **Step 2: Verify import**

Run: `cd service && python -c "import app.main"`
Expected: logs "Using PostgreSQL..." or "Using DuckDB...", exit 0.

- [ ] **Step 3: Commit**

```bash
git add service/app/main.py
git commit -m "feat(settings): seed from env + reload settings on startup"
```

---

## Task 5: Settings API endpoints

**Files:**
- Create: `service/app/api/routes_settings.py`
- Modify: `service/app/main.py` (include the new router)

- [ ] **Step 1: Implement the settings router**

Create `service/app/api/routes_settings.py`:

```python
"""Settings API: read (masked), update, and test credentials."""

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.settings_registry import (
    REGISTRY,
    coerce_value,
    is_unchanged_secret,
    mask_value,
    registry_by_key,
)
from app.settings_store import load_rows, save

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    values: dict[str, str]


@router.get("")
async def get_settings():
    """Return registry metadata + current values. Secrets are masked."""
    rows = load_rows()
    fields = []
    for sdef in REGISTRY:
        current = getattr(settings, sdef.key, None)
        raw = rows.get(sdef.key, "" if current is None else str(current))
        if sdef.secret:
            fields.append({
                "key": sdef.key, "type": sdef.type, "group": sdef.group,
                "label": sdef.label, "secret": True,
                "is_set": bool(raw), "masked": mask_value(raw or ""),
            })
        else:
            fields.append({
                "key": sdef.key, "type": sdef.type, "group": sdef.group,
                "label": sdef.label, "secret": False,
                "value": coerce_value(sdef.type, raw) if raw != "" else current,
            })
    return {"fields": fields}


@router.put("")
async def update_settings(payload: SettingsUpdate):
    """Validate + persist changed values. Masked/blank secrets are ignored."""
    defs = registry_by_key()
    to_save: dict[str, str] = {}
    for key, value in payload.values.items():
        sdef = defs.get(key)
        if sdef is None:
            raise HTTPException(status_code=422, detail=f"Unknown setting: {key}")
        if sdef.secret and is_unchanged_secret(value):
            continue  # keep existing secret
        # validate type by attempting coercion
        try:
            coerce_value(sdef.type, value)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail=f"Invalid value for {key}")
        to_save[key] = value
    save(to_save)
    return {"saved": sorted(to_save.keys())}


@router.post("/test/{group}")
async def test_credentials(group: str):
    """Lightweight reachability check for a credential group."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if group == "credentials_lastfm" or group == "lastfm":
                if not settings.lastfm_api_key:
                    return {"ok": False, "message": "No Last.fm API key set"}
                r = await client.get(
                    "https://ws.audioscrobbler.com/2.0/",
                    params={"method": "artist.getinfo", "artist": "Radiohead",
                            "api_key": settings.lastfm_api_key, "format": "json"},
                )
                return {"ok": r.status_code == 200, "message": f"HTTP {r.status_code}"}
            if group == "openai":
                if not settings.openai_api_key:
                    return {"ok": False, "message": "No OpenAI API key set"}
                r = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                )
                return {"ok": r.status_code == 200, "message": f"HTTP {r.status_code}"}
            if group == "discogs":
                from app.ingestion.discogs import _auth_header
                auth = _auth_header()
                if not auth:
                    return {"ok": False, "message": "No Discogs credentials set"}
                r = await client.get(
                    "https://api.discogs.com/database/search",
                    params={"q": "test", "per_page": 1},
                    headers={"Authorization": auth, "User-Agent": "playlist-generator/1.0"},
                )
                return {"ok": r.status_code == 200, "message": f"HTTP {r.status_code}"}
            if group == "jellyfin":
                if not settings.jellyfin_url or not settings.jellyfin_api_key:
                    return {"ok": False, "message": "Jellyfin URL/key not set"}
                r = await client.get(
                    f"{settings.jellyfin_url.rstrip('/')}/System/Info",
                    headers={"X-Emby-Token": settings.jellyfin_api_key},
                )
                return {"ok": r.status_code == 200, "message": f"HTTP {r.status_code}"}
    except Exception as e:  # noqa: BLE001 — test endpoint never throws
        return {"ok": False, "message": str(e)}
    return {"ok": False, "message": f"Unknown group: {group}"}
```

- [ ] **Step 2: Include the router in main.py**

In `service/app/main.py`, after `app.include_router(router)`, add (PostgreSQL only, since it depends on the store):

```python
if USE_POSTGRES:
    from app.api.routes_settings import router as settings_router
    app.include_router(settings_router)
```

- [ ] **Step 3: Verify import**

Run: `cd service && python -c "import app.main; import app.api.routes_settings"`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add service/app/api/routes_settings.py service/app/main.py
git commit -m "feat(settings): GET/PUT /settings + POST /settings/test/{group}"
```

---

## Task 6: Discogs OAuth (PLAINTEXT) endpoints + helper

**Files:**
- Create: `service/app/ingestion/discogs_oauth.py`
- Test: `service/app/tests/test_discogs_oauth.py`
- Modify: `service/app/api/routes_settings.py` (add OAuth start + callback routes)

- [ ] **Step 1: Write failing tests for the header builder**

Create `service/app/tests/test_discogs_oauth.py`:

```python
from app.ingestion.discogs_oauth import build_oauth_header


def test_request_token_header_plaintext_signature():
    h = build_oauth_header(
        consumer_key="CK", consumer_secret="CS",
        token=None, token_secret=None,
        callback="https://x/cb", verifier=None,
        nonce="NONCE", timestamp="123",
    )
    assert 'oauth_consumer_key="CK"' in h
    assert 'oauth_signature_method="PLAINTEXT"' in h
    assert 'oauth_signature="CS&"' in h          # no token secret yet
    assert 'oauth_callback="https%3A%2F%2Fx%2Fcb"' in h
    assert 'oauth_nonce="NONCE"' in h
    assert 'oauth_timestamp="123"' in h


def test_access_token_header_includes_token_and_verifier():
    h = build_oauth_header(
        consumer_key="CK", consumer_secret="CS",
        token="RT", token_secret="RTS",
        callback=None, verifier="VERIF",
        nonce="N", timestamp="1",
    )
    assert 'oauth_token="RT"' in h
    assert 'oauth_verifier="VERIF"' in h
    assert 'oauth_signature="CS&RTS"' in h        # consumer secret & token secret
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd service && python -m pytest app/tests/test_discogs_oauth.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the OAuth helper**

Create `service/app/ingestion/discogs_oauth.py`:

```python
"""Discogs 3-legged OAuth 1.0a using the PLAINTEXT signature method.

Discogs permits PLAINTEXT over HTTPS, so the signature is simply
`consumer_secret&token_secret` and no base-string/HMAC is needed.
Flow: request_token -> user authorizes -> access_token.
"""

import logging
from urllib.parse import parse_qs, quote

import httpx

logger = logging.getLogger(__name__)

_REQUEST_TOKEN_URL = "https://api.discogs.com/oauth/request_token"
_AUTHORIZE_URL = "https://www.discogs.com/oauth/authorize"
_ACCESS_TOKEN_URL = "https://api.discogs.com/oauth/access_token"
_UA = "playlist-generator/1.0"


def _q(v: str) -> str:
    return quote(str(v), safe="")


def build_oauth_header(
    *, consumer_key: str, consumer_secret: str,
    token: str | None, token_secret: str | None,
    callback: str | None, verifier: str | None,
    nonce: str, timestamp: str,
) -> str:
    """Build an OAuth 1.0a Authorization header value (PLAINTEXT signature)."""
    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "PLAINTEXT",
        "oauth_signature": f"{consumer_secret}&{token_secret or ''}",
        "oauth_timestamp": timestamp,
        "oauth_version": "1.0",
    }
    if callback:
        params["oauth_callback"] = callback
    if token:
        params["oauth_token"] = token
    if verifier:
        params["oauth_verifier"] = verifier
    parts = ", ".join(f'{k}="{_q(v)}"' for k, v in params.items())
    return f"OAuth {parts}"


def _nonce_and_ts() -> tuple[str, str]:
    import time
    import uuid
    return uuid.uuid4().hex, str(int(time.time()))


async def fetch_request_token(consumer_key: str, consumer_secret: str, callback: str) -> dict:
    """Step 1: get a temporary request token + secret + the authorize URL."""
    nonce, ts = _nonce_and_ts()
    header = build_oauth_header(
        consumer_key=consumer_key, consumer_secret=consumer_secret,
        token=None, token_secret=None, callback=callback, verifier=None,
        nonce=nonce, timestamp=ts,
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(_REQUEST_TOKEN_URL,
                             headers={"Authorization": header, "User-Agent": _UA})
    r.raise_for_status()
    data = {k: v[0] for k, v in parse_qs(r.text).items()}
    return {
        "oauth_token": data["oauth_token"],
        "oauth_token_secret": data["oauth_token_secret"],
        "authorize_url": f"{_AUTHORIZE_URL}?oauth_token={data['oauth_token']}",
    }


async def fetch_access_token(
    consumer_key: str, consumer_secret: str,
    request_token: str, request_token_secret: str, verifier: str,
) -> dict:
    """Step 3: exchange the authorized request token for a permanent access token."""
    nonce, ts = _nonce_and_ts()
    header = build_oauth_header(
        consumer_key=consumer_key, consumer_secret=consumer_secret,
        token=request_token, token_secret=request_token_secret,
        callback=None, verifier=verifier, nonce=nonce, timestamp=ts,
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(_ACCESS_TOKEN_URL,
                              headers={"Authorization": header, "User-Agent": _UA})
    r.raise_for_status()
    data = {k: v[0] for k, v in parse_qs(r.text).items()}
    return {
        "oauth_token": data["oauth_token"],
        "oauth_token_secret": data["oauth_token_secret"],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd service && python -m pytest app/tests/test_discogs_oauth.py -v`
Expected: all PASS.

- [ ] **Step 5: Add OAuth start + callback endpoints to the settings router**

First, add a `public_base_url` field to `service/app/config.py` (after `m3u_output_dir`, since the OAuth callback needs the externally-reachable URL):

```python
    public_base_url: str = ""  # e.g. https://playlist-generator.4eva.me — used for OAuth callbacks
```

Then in `service/app/api/routes_settings.py`, add imports near the top (note: `load_rows` and `save` are already imported in Task 5 — do NOT re-import them):

```python
from fastapi import Request
from fastapi.responses import RedirectResponse
from app.ingestion import discogs_oauth
```

Then append these routes to the router:

```python
@router.post("/discogs/oauth/start")
async def discogs_oauth_start(request: Request):
    """Begin Discogs OAuth: return the authorize URL, stash the request-token secret."""
    if not (settings.discogs_consumer_key and settings.discogs_consumer_secret):
        raise HTTPException(status_code=400, detail="Set Discogs consumer key/secret first")
    # The callback must be the PUBLIC URL (Discogs redirects the user's browser to it),
    # not the backend's internal 127.0.0.1 host. Prefer the configured public_base_url;
    # fall back to forwarded headers set by SWAG. The public path is /api/... because the
    # frontend proxies /api/** to the backend (stripping /api).
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        base = f"{proto}://{host}"
    callback = f"{base}/api/settings/discogs/oauth/callback"
    try:
        rt = await discogs_oauth.fetch_request_token(
            settings.discogs_consumer_key, settings.discogs_consumer_secret, callback)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Discogs request token failed: {e}")
    # Persist the temp request-token secret so the callback can complete the exchange.
    save({"_discogs_rt_secret": rt["oauth_token_secret"],
          "_discogs_rt_token": rt["oauth_token"]})
    return {"authorize_url": rt["authorize_url"]}


@router.get("/discogs/oauth/callback")
async def discogs_oauth_callback(oauth_token: str, oauth_verifier: str):
    """Complete Discogs OAuth and store the permanent access token."""
    rows = load_rows()
    rt_token = rows.get("_discogs_rt_token")
    rt_secret = rows.get("_discogs_rt_secret")
    if not rt_secret or oauth_token != rt_token:
        return RedirectResponse(url="/settings?discogs=error", status_code=302)
    try:
        at = await discogs_oauth.fetch_access_token(
            settings.discogs_consumer_key, settings.discogs_consumer_secret,
            rt_token, rt_secret, oauth_verifier)
    except Exception:  # noqa: BLE001
        return RedirectResponse(url="/settings?discogs=error", status_code=302)
    save({
        "discogs_oauth_token": at["oauth_token"],
        "discogs_oauth_token_secret": at["oauth_token_secret"],
        "_discogs_rt_token": "", "_discogs_rt_secret": "",
    })
    return RedirectResponse(url="/settings?discogs=connected", status_code=302)
```

Note: `_discogs_rt_token`/`_discogs_rt_secret` are transient working rows, intentionally NOT in the registry (so they never render in the form and are ignored by `_apply_rows`).

- [ ] **Step 6: Verify import + tests**

Run: `cd service && python -c "import app.api.routes_settings" && python -m pytest app/tests/test_discogs_oauth.py -v`
Expected: import ok, tests PASS.

- [ ] **Step 7: Commit**

```bash
git add service/app/ingestion/discogs_oauth.py service/app/tests/test_discogs_oauth.py service/app/api/routes_settings.py
git commit -m "feat(settings): Discogs PLAINTEXT OAuth start/callback flow"
```

---

## Task 7: Add OAuth access-token tier to the Discogs client

**Files:**
- Modify: `service/app/ingestion/discogs.py` (`_auth_header()` + add `config.py` fields)

- [ ] **Step 1: Add the two OAuth config fields**

In `service/app/config.py`, after the `discogs_consumer_secret` line, add:

```python
    discogs_oauth_token: str = ""          # set by the in-app OAuth flow
    discogs_oauth_token_secret: str = ""   # set by the in-app OAuth flow
```

- [ ] **Step 2: Add the OAuth tier to `_auth_header()`**

In `service/app/ingestion/discogs.py`, replace the body of `_auth_header()` so OAuth wins when present:

```python
def _auth_header() -> str | None:
    """Build the Discogs Authorization header value from configured credentials.

    Priority: OAuth access token (PLAINTEXT-signed) > consumer key/secret > personal token.
    Returns None when no usable credentials are configured.
    """
    if (settings.discogs_oauth_token and settings.discogs_oauth_token_secret
            and settings.discogs_consumer_key and settings.discogs_consumer_secret):
        import time
        import uuid
        from app.ingestion.discogs_oauth import build_oauth_header
        nonce, ts = uuid.uuid4().hex, str(int(time.time()))
        return build_oauth_header(
            consumer_key=settings.discogs_consumer_key,
            consumer_secret=settings.discogs_consumer_secret,
            token=settings.discogs_oauth_token,
            token_secret=settings.discogs_oauth_token_secret,
            callback=None, verifier=None, nonce=nonce, timestamp=ts,
        )
    if settings.discogs_token:
        return f"Discogs token={settings.discogs_token}"
    if settings.discogs_consumer_key and settings.discogs_consumer_secret:
        return (
            f"Discogs key={settings.discogs_consumer_key}, "
            f"secret={settings.discogs_consumer_secret}"
        )
    return None
```

- [ ] **Step 3: Verify import + existing discogs behavior unchanged**

Run: `cd service && python -c "import app.ingestion.discogs" && python -m pytest app/tests -q`
Expected: import ok; all existing tests still PASS.

- [ ] **Step 4: Commit**

```bash
git add service/app/config.py service/app/ingestion/discogs.py
git commit -m "feat(settings): Discogs client honors OAuth access token (PLAINTEXT)"
```

---

## Task 8: Frontend types + composable

**Files:**
- Create: `frontend/app/types/settings.ts`
- Create: `frontend/app/composables/useSettings.ts`

- [ ] **Step 1: Create the TS types**

Create `frontend/app/types/settings.ts`:

```ts
export interface SettingField {
  key: string
  type: 'str' | 'secret' | 'bool' | 'int' | 'float' | 'csv'
  group: 'credentials' | 'enrichment' | 'jellyfin' | 'library' | 'advanced'
  label: string
  secret: boolean
  value?: string | number | boolean | null
  is_set?: boolean
  masked?: string
}

export interface SettingsResponse {
  fields: SettingField[]
}

export interface TestResult {
  ok: boolean
  message: string
}
```

- [ ] **Step 2: Create the composable**

Create `frontend/app/composables/useSettings.ts`:

```ts
import { ref } from 'vue'
import type { SettingField, SettingsResponse, TestResult } from '~/types/settings'

export function useSettings() {
  const fields = ref<SettingField[]>([])
  const loading = ref(false)

  async function fetchSettings() {
    loading.value = true
    try {
      const res = await fetch('/api/settings')
      if (res.ok) {
        const data: SettingsResponse = await res.json()
        fields.value = data.fields
      }
    }
    finally {
      loading.value = false
    }
  }

  async function saveSettings(values: Record<string, string>) {
    const res = await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    })
    if (!res.ok) throw new Error((await res.json()).detail ?? 'Save failed')
    await fetchSettings()
  }

  async function testGroup(group: string): Promise<TestResult> {
    const res = await fetch(`/api/settings/test/${group}`, { method: 'POST' })
    return res.json()
  }

  async function startDiscogsOauth(): Promise<string> {
    const res = await fetch('/api/settings/discogs/oauth/start', { method: 'POST' })
    if (!res.ok) throw new Error((await res.json()).detail ?? 'OAuth start failed')
    return (await res.json()).authorize_url
  }

  return { fields, loading, fetchSettings, saveSettings, testGroup, startDiscogsOauth }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/types/settings.ts frontend/app/composables/useSettings.ts
git commit -m "feat(settings): frontend types + useSettings composable"
```

---

## Task 9: Settings page

**Files:**
- Create: `frontend/app/pages/settings.vue`

- [ ] **Step 1: Create the page**

Create `frontend/app/pages/settings.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useSettings } from '~/composables/useSettings'
import type { SettingField } from '~/types/settings'

const { fields, loading, fetchSettings, saveSettings, testGroup, startDiscogsOauth } = useSettings()
const toast = useToast()
const route = useRoute()

// edits holds only changed keys (string values for the PUT payload)
const edits = reactive<Record<string, string>>({})
const saving = ref(false)
const testResults = reactive<Record<string, string>>({})

const GROUPS: { key: SettingField['group'], label: string, advanced?: boolean }[] = [
  { key: 'credentials', label: 'Credentials' },
  { key: 'enrichment', label: 'Enrichment' },
  { key: 'jellyfin', label: 'Jellyfin' },
  { key: 'library', label: 'Library' },
  { key: 'advanced', label: 'Advanced', advanced: true },
]

function fieldsFor(group: string) {
  return fields.value.filter(f => f.group === group)
}

function modelFor(f: SettingField) {
  if (f.key in edits) return edits[f.key]
  if (f.secret) return '' // password field starts blank; placeholder shows mask
  if (f.type === 'bool') return f.value
  return f.value ?? ''
}

function setField(f: SettingField, val: string | boolean) {
  edits[f.key] = typeof val === 'boolean' ? String(val) : val
}

async function onSave() {
  saving.value = true
  try {
    await saveSettings({ ...edits })
    Object.keys(edits).forEach(k => delete edits[k])
    toast.add({ title: 'Settings saved', color: 'success' })
  }
  catch (e) {
    toast.add({ title: 'Save failed', description: String(e), color: 'error' })
  }
  finally {
    saving.value = false
  }
}

async function onTest(group: string) {
  const r = await testGroup(group)
  testResults[group] = `${r.ok ? '✓' : '✗'} ${r.message}`
}

async function onConnectDiscogs() {
  try {
    const url = await startDiscogsOauth()
    window.open(url, '_blank')
  }
  catch (e) {
    toast.add({ title: 'Discogs OAuth failed', description: String(e), color: 'error' })
  }
}

const discogsStatus = computed(() => {
  const tok = fields.value.find(f => f.key === 'discogs_oauth_token')
  if (tok?.is_set) return 'Connected (OAuth)'
  const ck = fields.value.find(f => f.key === 'discogs_consumer_key')
  if (ck?.is_set) return 'Using key/secret'
  return 'Not configured'
})

onMounted(async () => {
  await fetchSettings()
  if (route.query.discogs === 'connected') toast.add({ title: 'Discogs connected', color: 'success' })
  if (route.query.discogs === 'error') toast.add({ title: 'Discogs OAuth error', color: 'error' })
})
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-semibold">Settings</h1>
      <UButton :loading="saving" @click="onSave">Save changes</UButton>
    </div>

    <div v-if="loading">Loading…</div>

    <div v-else class="space-y-8">
      <section v-for="g in GROUPS" :key="g.key">
        <h2 class="text-lg font-medium mb-3">{{ g.label }}</h2>
        <div class="space-y-3">
          <div v-for="f in fieldsFor(g.key)" :key="f.key" class="flex items-center gap-3">
            <label class="w-64 text-sm text-gray-600 dark:text-gray-400">{{ f.label }}</label>

            <UToggle
              v-if="f.type === 'bool'"
              :model-value="modelFor(f) === true || modelFor(f) === 'true'"
              @update:model-value="(v: boolean) => setField(f, v)"
            />
            <UInput
              v-else-if="f.secret"
              type="password"
              :placeholder="f.is_set ? f.masked : 'not set'"
              :model-value="(edits[f.key] ?? '')"
              class="flex-1"
              @update:model-value="(v: string) => setField(f, v)"
            />
            <UInput
              v-else
              :type="(f.type === 'int' || f.type === 'float') ? 'number' : 'text'"
              :model-value="String(modelFor(f) ?? '')"
              class="flex-1"
              @update:model-value="(v: string) => setField(f, v)"
            />
          </div>

          <!-- Per-group test / connect actions -->
          <div v-if="g.key === 'credentials'" class="flex flex-wrap gap-2 pt-2">
            <UButton size="xs" variant="soft" @click="onTest('lastfm')">Test Last.fm</UButton>
            <span class="text-xs self-center">{{ testResults['lastfm'] }}</span>
            <UButton size="xs" variant="soft" @click="onTest('openai')">Test OpenAI</UButton>
            <span class="text-xs self-center">{{ testResults['openai'] }}</span>
            <UButton size="xs" variant="soft" @click="onTest('discogs')">Test Discogs</UButton>
            <span class="text-xs self-center">{{ testResults['discogs'] }}</span>
            <UButton size="xs" color="primary" @click="onConnectDiscogs">Connect with Discogs</UButton>
            <span class="text-xs self-center">{{ discogsStatus }}</span>
          </div>
          <div v-if="g.key === 'jellyfin'" class="flex gap-2 pt-2">
            <UButton size="xs" variant="soft" @click="onTest('jellyfin')">Test Jellyfin</UButton>
            <span class="text-xs self-center">{{ testResults['jellyfin'] }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Type-check / build the frontend**

Run: `cd frontend && pnpm install && pnpm build`
Expected: build succeeds (no TS/Vue errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/app/pages/settings.vue
git commit -m "feat(settings): registry-driven settings page (Nuxt UI v4)"
```

---

## Task 10: Add Settings to the nav

**Files:**
- Modify: `frontend/app/layouts/default.vue`

- [ ] **Step 1: Add the nav item + active state**

In `frontend/app/layouts/default.vue`, update `activeNav` and `navItems`:

```ts
const activeNav = computed(() => {
  if (route.path === '/observatory') return 'observatory'
  if (route.path === '/eval') return 'eval'
  if (route.path === '/settings') return 'settings'
  return 'generator'
})

const navItems = [
  { to: '/', key: 'generator', label: 'Generator' },
  { to: '/observatory', key: 'observatory', label: 'Observatory' },
  { to: '/eval', key: 'eval', label: 'Eval' },
  { to: '/settings', key: 'settings', label: 'Settings' },
]
```

- [ ] **Step 2: Build to confirm**

Run: `cd frontend && pnpm build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/layouts/default.vue
git commit -m "feat(settings): add Settings to nav"
```

---

## Task 11: Documentation updates

**Files:**
- Modify: `AGENTS.md`, `README.md`, `CLAUDE.md`, `.env.example`

- [ ] **Step 1: AGENTS.md**

Add to the Environment Variables section a note that the listed app keys are now **DB-backed settings** seeded once from env on first boot; only `DATABASE_URL` and `AUTH_*` remain env-only. Add to API Endpoints: `GET/PUT /settings`, `POST /settings/test/{group}`, `POST /settings/discogs/oauth/start`, `GET /settings/discogs/oauth/callback`. Add `app_settings` to the table list.

- [ ] **Step 2: README.md**

In the Configuration section, state that settings are managed in-app at `/settings` (DB is source of truth; `.env` only seeds the first boot). Add the four new endpoints to the API Reference.

- [ ] **Step 3: CLAUDE.md**

Add a Gotcha: "Settings are DB-backed (`app_settings`) and overlaid onto the `settings` singleton at startup + on save; this relies on the single uvicorn process. `.env` for app keys is seed-only after first boot." Add `service/app/settings_registry.py`, `settings_store.py`, `api/routes_settings.py`, `ingestion/discogs_oauth.py` to Important Files.

- [ ] **Step 4: .env.example (both root and submodule)**

Add a header comment above the API-key block: "These are seed-only — after first boot, manage them in the app at /settings; the DB is the source of truth." (Edit `webapps/jellyfin-playlist-generator/.env.example`; the NAS root `.env.example` is in the parent repo — note it in the handoff but only edit within this repo's scope.)

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md README.md CLAUDE.md .env.example
git commit -m "docs(settings): document DB-backed settings, endpoints, and seed-only env"
```

---

## Task 12: Full verification

- [ ] **Step 1: Backend tests + lint**

Run: `cd service && python -m pytest app/tests -q && ruff check app`
Expected: all tests PASS; ruff clean (fix any lint).

- [ ] **Step 2: Frontend lint + build**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: clean.

- [ ] **Step 3: Container build (matches deployment)**

Run: `cd /home/tom/nas && docker compose --profile unified build app`
Expected: image builds.

- [ ] **Step 4: Live smoke (after deploy)**

```bash
docker compose --profile unified up -d --build app
# wait ~90s for model load
curl -s localhost:8080/settings | head -c 400      # masked fields render
```
Expected: JSON with `fields[]`, secrets masked, existing keys showing `is_set: true` (seeded from env).

- [ ] **Step 5: Final commit (if any lint fixes)**

```bash
git add -A && git commit -m "chore(settings): lint fixes + verification"
```

---

## Post-implementation note

Filling keys in the page does not retroactively enrich the 12.7k existing tracks. After setting MusicBrainz contact + Discogs, trigger the enrichment pipeline (MB resolution → legitimacy → banger detection → release dates) via the sync pipeline or `app.cli_v3` to populate the currently-empty `mb_release_groups` / `album_legitimacy` / `track_banger_flags` / `album_release_dates` tables. This is intentionally out of scope for this plan.
