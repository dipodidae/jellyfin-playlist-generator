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
    public_base_url: str = ""  # e.g. https://playlist-generator.4eva.me — used for OAuth callbacks

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
    openai_intent_model: str = "gpt-4o-mini"  # model for structured intent parsing

    # Parse hardening (PARSE_AUDIT P2/P4/P6). All default-on; flip off to
    # restore the legacy prompt-and-pray behaviour without a redeploy.
    intent_grounding_enabled: bool = True     # inject library vocab into the parse prompt (P2)
    genre_snapping_enabled: bool = True       # snap out-of-vocab genres to nearest known term (P4)
    genre_snap_min_similarity: float = 0.55   # below this cosine, drop the hint instead of snapping
    intent_parse_cache_enabled: bool = True   # cache LLM parse keyed on normalized prompt (P6)
    intent_parse_seed: int = 7                # OpenAI seed for reproducible parses (P6)
    artist_seed_weight: float = 0.35          # how hard artist_seeds pull the query embedding (P1)
    seed_affinity_weight: float = 0.30        # +weight on seed_affinity_score: named bands + Last.fm-tag neighbors (P-SEED)

    # MusicBrainz
    musicbrainz_app_name: str = "playlist-generator"
    musicbrainz_app_version: str = "1.0"
    musicbrainz_contact: str = ""  # email, required by MB API ToS

    # Discogs (release date resolution). Either a personal access token OR a
    # consumer key/secret pair authenticates the non-user endpoints we use
    # (search, masters, versions). Token takes precedence if both are set.
    discogs_token: str = ""  # personal access token from discogs.com/settings/developers
    discogs_consumer_key: str = ""    # app consumer key (discogs.com/settings/developers)
    discogs_consumer_secret: str = ""  # app consumer secret
    discogs_oauth_token: str = ""          # set by the in-app OAuth flow
    discogs_oauth_token_secret: str = ""   # set by the in-app OAuth flow

    # Sequencing: harmonic-continuity (key matching) term — experimental, off by
    # default. See trajectory/harmony.py and the settings registry description.
    harmonic_continuity_enabled: bool = False

    # Jellyfin integration
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""
    jellyfin_path_prefix: str = ""  # Path prefix inside Jellyfin container (e.g. /data/movies)
    local_path_prefix: str = ""     # Corresponding local path prefix (e.g. /mnt/drive-next)

    # --- Snapshot mode (archival breadth-across-artists cross-section) ---
    snapshot_soft_cap: int = 120            # target chonky size; thinner niche → fewer
    snapshot_relevance_floor: float = 0.35  # strict floor: drop tracks below this niche fit
    snapshot_min_per_artist: int = 2        # minimum picks per qualifying artist
    snapshot_max_per_artist: int = 4        # maximum picks per qualifying artist
    snapshot_album_cap: int = 2             # max tracks from one album within an artist
    snapshot_banger_percentile: float = 0.6  # top frac of an artist's popularity = "banger"
    snapshot_mood_weight: float = 0.3       # weight of mood(darkness) proximity in relevance
    snapshot_pool_limit: int = 1500         # candidate pool size before selection
    # Snapshot quality blend: score = (w_rel*relevance + w_leg*MA_legitimacy
    # + w_ban*banger + w_classic*classic) * studio_factor. Weights sum to ~1.0.
    snapshot_w_relevance: float = 0.30      # niche fit
    snapshot_w_legitimacy: float = 0.30     # Metal-Archives album rating (percentile) — wins
    snapshot_w_banger: float = 0.25         # Last.fm banger signal
    snapshot_w_classic: float = 0.15        # slight bias toward OG/classic releases
    snapshot_nonstudio_factor: float = 0.25  # multiplier for live/demo/remix (studio always wins)
    snapshot_classic_anchor_year: int = 1970  # oldness scale anchor (oldest → bonus 1.0)
    snapshot_classic_ref_year: int = 2025   # oldness scale reference ("now")

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
