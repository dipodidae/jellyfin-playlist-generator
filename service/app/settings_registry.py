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
    SettingDef("discogs_consumer_key", "secret", "credentials",
               "Discogs consumer key", secret=True),
    SettingDef("discogs_consumer_secret", "secret", "credentials",
               "Discogs consumer secret", secret=True),
    SettingDef("discogs_oauth_token", "secret", "credentials", "Discogs OAuth token", secret=True),
    SettingDef("discogs_oauth_token_secret", "secret", "credentials",
               "Discogs OAuth token secret", secret=True),
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
    SettingDef("cluster_secondary_weight_threshold", "float", "advanced",
               "Cluster: secondary weight threshold"),
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
