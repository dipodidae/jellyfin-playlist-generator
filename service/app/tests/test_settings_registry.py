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
