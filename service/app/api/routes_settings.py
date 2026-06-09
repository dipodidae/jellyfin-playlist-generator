"""Settings API: read (masked), update, and test credentials."""

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.config import settings
from app.ingestion import discogs_oauth
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
