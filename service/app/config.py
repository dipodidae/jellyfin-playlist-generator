from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    # Database (PostgreSQL + pgvector)
    database_url: str = "postgresql://playlist:playlist_dev@localhost:5432/playlist_generator"

    # Scanner
    music_directories: str = "/music"  # Comma-separated paths
    scan_threads: int = 8

    # Export
    m3u_output_dir: str = "/playlists"

    # Embeddings
    embedding_model_version: int = 1

    # Clustering – HDBSCAN + UMAP pipeline
    cluster_min_tracks: int = 3  # Min embedded tracks per artist for clustering inclusion
    cluster_secondary_weight_threshold: float = 0.2  # Min weight for secondary cluster membership
    cluster_max_per_artist: int = 3  # Max clusters an artist can belong to
    cluster_random_state: int = 42  # Random seed for reproducibility (UMAP)

    # HDBSCAN parameters
    cluster_min_cluster_size: int = 5  # Min artists to form a cluster
    cluster_min_samples: int = 3  # Density parameter (higher = stricter clusters)

    # UMAP dimensionality reduction (applied before HDBSCAN)
    cluster_umap_n_components: int = 20  # Output dimensions
    cluster_umap_n_neighbors: int = 15  # Local structure preservation
    cluster_umap_min_dist: float = 0.05  # Tightness of packing (lower = tighter)

    # Post-clustering merge & quality
    cluster_merge_threshold: float = 0.85  # Cosine similarity above which clusters merge
    cluster_noise_weight: float = 0.3  # Weight for noise-point soft-assignment
    cluster_tag_weight: float = 0.3  # Blend weight for artist-tag embedding (vs track-averaged)

    # Last.fm
    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""

    # OpenAI (for LLM intent parsing and title generation)
    openai_api_key: str = ""

    # MusicBrainz
    musicbrainz_app_name: str = "playlist-generator"
    musicbrainz_app_version: str = "1.0"
    musicbrainz_contact: str = ""  # email, required by MB API ToS

    # Discogs (release date resolution)
    discogs_token: str = ""  # personal access token from discogs.com/settings/developers

    # RateYourMusic (scraping)
    rym_scrape_delay_min: float = 2.0
    rym_scrape_delay_max: float = 5.0
    rym_scrape_enabled: bool = False  # explicit opt-in

    # Jellyfin integration
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""
    jellyfin_path_prefix: str = ""  # Path prefix inside Jellyfin container (e.g. /data/movies)
    local_path_prefix: str = ""     # Corresponding local path prefix (e.g. /mnt/drive-next)

    # Legacy (deprecated, kept for migration)
    database_path: str = ""  # Old DuckDB path

    model_config = SettingsConfigDict(
        env_file=[
            _PROJECT_ROOT / ".env",
            ".env",
        ],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def music_dirs(self) -> list[str]:
        """Parse comma-separated music directories."""
        return [d.strip() for d in self.music_directories.split(",") if d.strip()]


settings = Settings()
