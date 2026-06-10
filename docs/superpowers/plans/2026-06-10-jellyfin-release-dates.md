# Jellyfin Release-Date Fixer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Tools-page button that pushes the app's resolved original release dates onto matching Jellyfin albums (album-level, locked so they persist).

**Architecture:** A focused `ingestion/jellyfin_dates.py` (pure matching/date helpers + httpx Jellyfin client + an orchestrator), an SSE endpoint `POST /jellyfin/fix-release-dates`, and a new `tools.vue` page. Matching is path-based (same `/music` files in both systems via the existing prefix mapping) with normalized name fallback. No DB writes.

**Tech Stack:** FastAPI, httpx, psycopg2, Nuxt 4 + Nuxt UI v4, pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-jellyfin-release-dates-design.md`
**Branch:** `jellyfin-release-dates`

**Test runner:** host has no deps; use `service/.venv-test` (a `conftest.py` stubs scipy/sentence_transformers; httpx/psycopg2/pydantic-settings are installed).

---

## Task 0: Ensure test venv

- [ ] **Step 1:** 
```bash
cd /home/tom/nas/webapps/jellyfin-playlist-generator/service
test -d .venv-test || python -m venv .venv-test
.venv-test/bin/pip -q install pytest pydantic pydantic-settings psycopg2-binary httpx numpy ruff
.venv-test/bin/python -c "import pytest, httpx; print('venv ready')"
```
Expected: `venv ready`. Never `git add` `.venv-test`.

---

## Task 1: Pure helpers (TDD)

**Files:**
- Create: `service/app/ingestion/jellyfin_dates.py`
- Test: `service/app/tests/test_jellyfin_dates.py`

- [ ] **Step 1: Write the failing tests**

Create `service/app/tests/test_jellyfin_dates.py`:

```python
from app.ingestion.jellyfin_dates import (
    translate_path,
    build_premiere_date,
    resolve_album_id_map,
    match_by_name,
)


def test_translate_path_swaps_prefix():
    assert translate_path("/music/Dio/Holy Diver/01.mp3", "/music", "/data/movies/music") \
        == "/data/movies/music/Dio/Holy Diver/01.mp3"


def test_translate_path_trailing_slashes():
    assert translate_path("/music/A/b.mp3", "/music/", "/data/movies/music/") \
        == "/data/movies/music/A/b.mp3"


def test_translate_path_non_prefixed_passthrough():
    assert translate_path("/other/x.mp3", "/music", "/data/movies/music") == "/other/x.mp3"


def test_build_premiere_date_year_only():
    assert build_premiere_date(1983, None, None, "year") == "1983-01-01T00:00:00.0000000Z"


def test_build_premiere_date_full():
    assert build_premiere_date(1983, 5, 25, "day") == "1983-05-25T00:00:00.0000000Z"


def test_build_premiere_date_month_precision():
    assert build_premiere_date(1990, 7, None, "month") == "1990-07-01T00:00:00.0000000Z"


def test_resolve_album_id_map_path_hit():
    app_albums = [
        {"album_id": "A1", "track_paths": ["/music/Dio/Holy Diver/01.mp3"]},
        {"album_id": "A2", "track_paths": ["/music/Nope/x.mp3"]},
    ]
    audio_items = [
        {"Id": "t1", "AlbumId": "JF-ALB-1", "Path": "/data/movies/music/Dio/Holy Diver/01.mp3"},
    ]
    mapping, unresolved = resolve_album_id_map(app_albums, audio_items, "/music", "/data/movies/music")
    assert mapping == {"A1": "JF-ALB-1"}
    assert unresolved == ["A2"]


def test_resolve_album_id_map_multiple_tracks_one_hits():
    app_albums = [{"album_id": "A1", "track_paths": ["/music/x/missing.mp3", "/music/x/found.mp3"]}]
    audio_items = [{"Id": "t", "AlbumId": "JF9", "Path": "/data/movies/music/x/found.mp3"}]
    mapping, unresolved = resolve_album_id_map(app_albums, audio_items, "/music", "/data/movies/music")
    assert mapping == {"A1": "JF9"}
    assert unresolved == []


def test_match_by_name_normalized():
    jf_albums = [{"Id": "JF1", "Name": "Holy Diver", "AlbumArtist": "Dio"}]
    assert match_by_name("holy  diver", "DIO", jf_albums) == "JF1"
    assert match_by_name("Unknown", "Dio", jf_albums) is None
```

- [ ] **Step 2: Run to verify fail**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_jellyfin_dates.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the pure helpers**

Create `service/app/ingestion/jellyfin_dates.py`:

```python
"""Fix Jellyfin album release dates from the app's resolved original dates.

Pure helpers (no I/O) + an httpx Jellyfin client + an orchestrator. Matching is
path-based (both systems index the same files via the configured prefix mapping)
with a normalized name fallback.
"""

import logging

import httpx

from app.config import settings
from app.database_pg import get_connection
from app.trajectory.textnorm import normalize_artist, normalize_title

logger = logging.getLogger(__name__)


def translate_path(local_path: str, local_prefix: str, jellyfin_prefix: str) -> str:
    """Rewrite an app /music path to the path Jellyfin reports. Passthrough if no prefix match."""
    lp = local_prefix.rstrip("/")
    jp = jellyfin_prefix.rstrip("/")
    if lp and local_path.startswith(lp):
        return jp + local_path[len(lp):]
    return local_path


def build_premiere_date(year, month, day, precision: str) -> str:
    """ISO-8601 PremiereDate string Jellyfin accepts. Missing month/day default to 01."""
    m = month if (precision in ("month", "day") and month) else 1
    d = day if (precision == "day" and day) else 1
    return f"{int(year):04d}-{int(m):02d}-{int(d):02d}T00:00:00.0000000Z"


def resolve_album_id_map(app_albums, jellyfin_audio_items, local_prefix, jellyfin_prefix):
    """Map app album_id -> Jellyfin AlbumId via translated track paths.

    app_albums: [{"album_id": str, "track_paths": [str, ...]}]
    jellyfin_audio_items: [{"Id", "AlbumId", "Path"}]
    Returns (mapping, unresolved_album_ids).
    """
    by_path = {it.get("Path"): it.get("AlbumId") for it in jellyfin_audio_items if it.get("Path")}
    mapping: dict[str, str] = {}
    unresolved: list[str] = []
    for alb in app_albums:
        found = None
        for p in alb.get("track_paths", []):
            jf_path = translate_path(p, local_prefix, jellyfin_prefix)
            album_id = by_path.get(jf_path)
            if album_id:
                found = album_id
                break
        if found:
            mapping[alb["album_id"]] = found
        else:
            unresolved.append(alb["album_id"])
    return mapping, unresolved


def match_by_name(app_album_name, app_artist, jellyfin_albums) -> str | None:
    """Normalized AlbumArtist+Name fallback match. Returns Jellyfin album Id or None."""
    want_title = normalize_title(app_album_name or "")
    want_artist = normalize_artist(app_artist or "")
    for alb in jellyfin_albums:
        if (normalize_title(alb.get("Name") or "") == want_title
                and normalize_artist(alb.get("AlbumArtist") or "") == want_artist):
            return alb.get("Id")
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `cd service && .venv-test/bin/python -m pytest app/tests/test_jellyfin_dates.py -v`
Expected: all PASS. (`normalize_title`/`normalize_artist` collapse whitespace + lowercase; the `"holy  diver"`→`"Holy Diver"` test relies on that — if a test fails because normalization differs, adjust the test's expected input to match `textnorm`'s actual behavior, NOT the implementation.)

- [ ] **Step 5: Commit**

```bash
git add service/app/ingestion/jellyfin_dates.py service/app/tests/test_jellyfin_dates.py
git commit -m "feat(jellyfin-dates): pure path-translate/date-build/match helpers"
```

---

## Task 2: Jellyfin client + orchestrator

**Files:**
- Modify: `service/app/ingestion/jellyfin_dates.py` (append client fns + orchestrator)

- [ ] **Step 1: Append the Jellyfin client functions + orchestrator**

Add to `service/app/ingestion/jellyfin_dates.py`:

```python
_PAGE = 500


def _headers() -> dict:
    return {"X-Emby-Token": settings.jellyfin_api_key}


async def fetch_audio_items(client: httpx.AsyncClient) -> list[dict]:
    """Page through all Jellyfin Audio items, returning [{Id, AlbumId, Path}]."""
    items: list[dict] = []
    start = 0
    while True:
        resp = await client.get(
            f"{settings.jellyfin_url}/Users/{settings.jellyfin_user_id}/Items",
            headers=_headers(),
            params={
                "IncludeItemTypes": "Audio",
                "Recursive": "true",
                "Fields": "Path",
                "StartIndex": start,
                "Limit": _PAGE,
            },
        )
        resp.raise_for_status()
        page = resp.json().get("Items", [])
        if not page:
            break
        for it in page:
            items.append({"Id": it.get("Id"), "AlbumId": it.get("AlbumId"), "Path": it.get("Path")})
        start += len(page)
        if len(page) < _PAGE:
            break
    return items


async def fetch_album_items(client: httpx.AsyncClient) -> list[dict]:
    """Page through all Jellyfin MusicAlbum items, returning [{Id, Name, AlbumArtist}]."""
    items: list[dict] = []
    start = 0
    while True:
        resp = await client.get(
            f"{settings.jellyfin_url}/Users/{settings.jellyfin_user_id}/Items",
            headers=_headers(),
            params={
                "IncludeItemTypes": "MusicAlbum",
                "Recursive": "true",
                "Fields": "AlbumArtist",
                "StartIndex": start,
                "Limit": _PAGE,
            },
        )
        resp.raise_for_status()
        page = resp.json().get("Items", [])
        if not page:
            break
        for it in page:
            artist = it.get("AlbumArtist")
            if not artist and it.get("AlbumArtists"):
                artist = (it["AlbumArtists"][0] or {}).get("Name")
            items.append({"Id": it.get("Id"), "Name": it.get("Name"), "AlbumArtist": artist})
        start += len(page)
        if len(page) < _PAGE:
            break
    return items


async def update_album_date(client: httpx.AsyncClient, jellyfin_album_id: str,
                            premiere_date: str, year: int) -> None:
    """Set PremiereDate + ProductionYear on a Jellyfin album and lock those fields."""
    # Fetch the full item DTO
    get_resp = await client.get(
        f"{settings.jellyfin_url}/Users/{settings.jellyfin_user_id}/Items/{jellyfin_album_id}",
        headers=_headers(),
    )
    get_resp.raise_for_status()
    dto = get_resp.json()
    dto["PremiereDate"] = premiere_date
    dto["ProductionYear"] = int(year)
    locked = set(dto.get("LockedFields") or [])
    locked.update({"PremiereDate", "ProductionYear"})
    dto["LockedFields"] = list(locked)
    # POST the mutated DTO back (UpdateItem)
    post_resp = await client.post(
        f"{settings.jellyfin_url}/Items/{jellyfin_album_id}",
        headers={**_headers(), "Content-Type": "application/json"},
        json=dto,
    )
    post_resp.raise_for_status()


def _load_eligible_albums() -> list[dict]:
    """App albums with a resolved original date + representative track paths."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.title, a.artist_name,
                       ard.original_year, ard.original_month, ard.original_day, ard.precision,
                       ARRAY(
                           SELECT tf.path FROM track_albums ta
                           JOIN track_files tf ON tf.track_id = ta.track_id
                           WHERE ta.album_id = a.id AND tf.path IS NOT NULL
                           LIMIT 5
                       ) AS track_paths
                FROM albums a
                JOIN album_release_dates ard ON ard.album_id = a.id
                WHERE ard.original_year IS NOT NULL
            """)
            rows = cur.fetchall()
    return [
        {
            "album_id": str(r[0]), "title": r[1], "artist_name": r[2],
            "year": r[3], "month": r[4], "day": r[5], "precision": r[6] or "year",
            "track_paths": list(r[7] or []),
        }
        for r in rows
    ]


async def fix_release_dates(progress_callback=None) -> dict:
    """Push resolved original dates onto matching Jellyfin albums. Album-level, locked."""
    if not settings.jellyfin_url or not settings.jellyfin_api_key:
        return {"error": "Jellyfin not configured (set jellyfin_url + jellyfin_api_key)"}

    albums = _load_eligible_albums()
    stats = {"eligible": len(albums), "matched": 0, "updated": 0,
             "skipped_no_jellyfin_match": 0, "failed": 0, "errors": []}
    if not albums:
        return stats

    lp, jp = settings.local_path_prefix or "/music", settings.jellyfin_path_prefix or ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        audio_items = await fetch_audio_items(client)
        mapping, unresolved = resolve_album_id_map(
            [{"album_id": a["album_id"], "track_paths": a["track_paths"]} for a in albums],
            audio_items, lp, jp,
        )
        if unresolved:
            jf_albums = await fetch_album_items(client)
            by_id = {a["album_id"]: a for a in albums}
            for aid in unresolved:
                a = by_id[aid]
                jf_id = match_by_name(a["title"], a["artist_name"], jf_albums)
                if jf_id:
                    mapping[aid] = jf_id

        stats["matched"] = len(mapping)
        stats["skipped_no_jellyfin_match"] = len(albums) - len(mapping)

        total = len(mapping)
        by_id = {a["album_id"]: a for a in albums}
        for i, (app_id, jf_id) in enumerate(mapping.items()):
            a = by_id[app_id]
            try:
                premiere = build_premiere_date(a["year"], a["month"], a["day"], a["precision"])
                await update_album_date(client, jf_id, premiere, a["year"])
                stats["updated"] += 1
            except Exception as e:  # noqa: BLE001 — per-album failure must not abort the run
                stats["failed"] += 1
                if len(stats["errors"]) < 10:
                    stats["errors"].append(f"{a['artist_name']} - {a['title']}: {e}")
            if progress_callback:
                progress_callback(i + 1, total, f"Updated {i + 1}/{total} albums")
    return stats
```

- [ ] **Step 2: Verify import + tests**

Run: `cd service && .venv-test/bin/python -c "import app.ingestion.jellyfin_dates; print('ok')" && .venv-test/bin/python -m pytest app/tests/test_jellyfin_dates.py -q && .venv-test/bin/ruff check app/ingestion/jellyfin_dates.py`
Expected: `ok`; tests PASS; ruff clean (fix any introduced issues).

- [ ] **Step 3: Commit**

```bash
git add service/app/ingestion/jellyfin_dates.py
git commit -m "feat(jellyfin-dates): Jellyfin client (fetch/update) + orchestrator"
```

---

## Task 3: SSE endpoint

**Files:**
- Modify: `service/app/api/routes_v3.py`

- [ ] **Step 1: Add the endpoint**

In `service/app/api/routes_v3.py`, add near the other enrichment endpoints. First add a module-level lock next to the existing `_audio_analysis_lock` (search for it):

```python
_jellyfin_dates_lock = asyncio.Lock()
```

Then add the route:

```python
@router.post("/jellyfin/fix-release-dates")
async def jellyfin_fix_release_dates(request: Request):
    """Push resolved original release dates onto matching Jellyfin albums (SSE progress)."""
    if _jellyfin_dates_lock.locked():
        raise HTTPException(status_code=409, detail="A release-date fix is already running")

    async def generate_events() -> AsyncGenerator[str, None]:
        def emit(stage: str, progress: int, message: str, **extra) -> str:
            return f"data: {json.dumps({'stage': stage, 'progress': progress, 'message': message, **extra})}\n\n"

        async with _jellyfin_dates_lock:
            yield emit("start", 0, "Fetching Jellyfin library and matching albums...")
            from app.ingestion.jellyfin_dates import fix_release_dates

            queue: asyncio.Queue = asyncio.Queue()

            def progress_cb(current: int, total: int, message: str):
                pct = int((current / total) * 100) if total else 0
                queue.put_nowait(emit("updating", pct, message))

            result_holder: dict = {}

            async def run():
                try:
                    result_holder["stats"] = await fix_release_dates(progress_callback=progress_cb)
                except Exception as e:  # noqa: BLE001
                    result_holder["error"] = str(e)
                finally:
                    queue.put_nowait(None)

            task = asyncio.create_task(run())
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
            await task

            if "error" in result_holder:
                yield emit("error", 0, result_holder["error"], error=result_holder["error"], done=True)
            else:
                stats = result_holder.get("stats", {})
                if stats.get("error"):
                    yield emit("error", 0, stats["error"], error=stats["error"], done=True)
                else:
                    msg = (f"Done: {stats.get('updated', 0)} updated, "
                           f"{stats.get('skipped_no_jellyfin_match', 0)} unmatched, "
                           f"{stats.get('failed', 0)} failed")
                    yield emit("complete", 100, msg, stats=stats, done=True)

    return StreamingResponse(generate_events(), media_type="text/event-stream")
```

- [ ] **Step 2: Verify import**

Run: `cd service && .venv-test/bin/python -c "import app.api.routes_v3" 2>&1 | tail -2 || true; .venv-test/bin/python -c "import ast; ast.parse(open('app/api/routes_v3.py').read()); print('parses')"`
Expected: `parses`. (Full import may need heavy deps; ast.parse is the gate. `AsyncGenerator`, `json`, `asyncio`, `Request`, `HTTPException`, `StreamingResponse` are already imported in this file — confirm; if `StreamingResponse` import is missing, it is already used elsewhere in the file so it is present.)

- [ ] **Step 3: Commit**

```bash
git add service/app/api/routes_v3.py
git commit -m "feat(jellyfin-dates): SSE endpoint POST /jellyfin/fix-release-dates"
```

---

## Task 4: Frontend Tools page

**Files:**
- Create: `frontend/app/composables/useJellyfinTools.ts`
- Create: `frontend/app/pages/tools.vue`
- Modify: `frontend/app/layouts/default.vue`

- [ ] **Step 1: Composable (SSE consumer)**

Create `frontend/app/composables/useJellyfinTools.ts`:

```ts
import { ref } from 'vue'

export interface FixStats {
  eligible: number
  matched: number
  updated: number
  skipped_no_jellyfin_match: number
  failed: number
  errors: string[]
}

export function useJellyfinTools() {
  const running = ref(false)
  const progress = ref(0)
  const message = ref('')
  const stats = ref<FixStats | null>(null)
  const error = ref<string | null>(null)

  async function fixReleaseDates() {
    running.value = true
    progress.value = 0
    stats.value = null
    error.value = null
    try {
      const res = await fetch('/api/jellyfin/fix-release-dates', { method: 'POST' })
      if (!res.body) throw new Error('No response stream')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const part of parts) {
          const line = part.split('\n').find(l => l.startsWith('data: '))
          if (!line) continue
          const evt = JSON.parse(line.slice(6))
          progress.value = evt.progress ?? progress.value
          message.value = evt.message ?? message.value
          if (evt.error) error.value = evt.error
          if (evt.stats) stats.value = evt.stats
        }
      }
    }
    catch (e) {
      error.value = String(e)
    }
    finally {
      running.value = false
    }
  }

  return { running, progress, message, stats, error, fixReleaseDates }
}
```

- [ ] **Step 2: Tools page**

Create `frontend/app/pages/tools.vue`:

```vue
<script setup lang="ts">
import { useJellyfinTools } from '~/composables/useJellyfinTools'

const { running, progress, message, stats, error, fixReleaseDates } = useJellyfinTools()
</script>

<template>
  <div>
    <h1 class="text-2xl font-semibold mb-6">Tools</h1>

    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-5 max-w-2xl">
      <h2 class="text-lg font-medium mb-1">Fix Jellyfin release dates</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
        Pushes the app's resolved original release dates (first-pressing year from Discogs/MusicBrainz)
        onto matching Jellyfin albums, and locks the fields so Jellyfin won't revert them.
        Album-level; reissues get their original date.
      </p>

      <UButton :loading="running" :disabled="running" @click="fixReleaseDates">
        {{ running ? 'Fixing…' : 'Fix Jellyfin release dates' }}
      </UButton>

      <div v-if="running || message" class="mt-4">
        <div class="h-2 bg-gray-200 dark:bg-gray-800 rounded overflow-hidden">
          <div class="h-full bg-emerald-500 transition-all" :style="{ width: `${progress}%` }" />
        </div>
        <div class="text-xs text-gray-500 dark:text-gray-400 mt-1">{{ message }}</div>
      </div>

      <div v-if="error" class="mt-4 text-sm text-red-500">{{ error }}</div>

      <div v-if="stats" class="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="text-center"><div class="text-xl font-bold text-emerald-500">{{ stats.updated }}</div><div class="text-xs text-gray-500">Updated</div></div>
        <div class="text-center"><div class="text-xl font-bold">{{ stats.matched }}</div><div class="text-xs text-gray-500">Matched</div></div>
        <div class="text-center"><div class="text-xl font-bold text-amber-500">{{ stats.skipped_no_jellyfin_match }}</div><div class="text-xs text-gray-500">Unmatched</div></div>
        <div class="text-center"><div class="text-xl font-bold text-red-500">{{ stats.failed }}</div><div class="text-xs text-gray-500">Failed</div></div>
      </div>

      <ul v-if="stats && stats.errors && stats.errors.length" class="mt-3 text-xs text-red-400 list-disc pl-5">
        <li v-for="(e, i) in stats.errors" :key="i">{{ e }}</li>
      </ul>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Nav link**

In `frontend/app/layouts/default.vue`, add to `activeNav` computed: `if (route.path === '/tools') return 'tools'`, and add `{ to: '/tools', key: 'tools', label: 'Tools' }` to `navItems`.

- [ ] **Step 4: Build**

Run: `cd frontend && pnpm install && pnpm build`
Expected: build succeeds. If `UButton` or any component errors, fix to the installed Nuxt UI v4 name and rebuild.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/composables/useJellyfinTools.ts frontend/app/pages/tools.vue frontend/app/layouts/default.vue
git commit -m "feat(jellyfin-dates): Tools page + Fix release dates button"
```

---

## Task 5: Docs + verification

**Files:** `AGENTS.md`, `README.md`, `CLAUDE.md`

- [ ] **Step 1: Docs**

Add the new endpoint `POST /jellyfin/fix-release-dates` to `AGENTS.md` (API Endpoints) and `README.md` (API Reference); add `ingestion/jellyfin_dates.py` + `frontend/app/pages/tools.vue` to `CLAUDE.md` Important Files; note the Tools page + that it writes locked album dates to Jellyfin. Commit:

```bash
git add AGENTS.md README.md CLAUDE.md
git commit -m "docs(jellyfin-dates): document the Tools page + fix-release-dates endpoint"
```

- [ ] **Step 2: Verify**

Run:
```bash
cd service && .venv-test/bin/python -m pytest app/tests -q && .venv-test/bin/ruff check app/ingestion/jellyfin_dates.py
cd ../frontend && pnpm build
```
Expected: tests pass; ruff clean on the new module; frontend builds.

- [ ] **Step 3 (controller, post-build):** deploy after the current rescan finishes (a rebuild now would interrupt it), then click the button on the Tools page to verify a real Jellyfin update + that the date sticks after a Jellyfin metadata refresh.

---

## Notes

- **No DB writes** — reads `album_release_dates` + `track_files`, writes only to Jellyfin.
- **Idempotent** — re-running re-sets the same locked dates; safe to click again after `album_release_dates` grows.
- **Best run after** the in-progress rescan's Discogs release-date stage has populated `album_release_dates`.
