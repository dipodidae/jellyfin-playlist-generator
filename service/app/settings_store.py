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
