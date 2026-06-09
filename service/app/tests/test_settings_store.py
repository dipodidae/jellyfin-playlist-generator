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
