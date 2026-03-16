export interface CollectionOverviewStats {
  total_tracks: number
  total_artists: number
  total_albums: number
  total_duration_ms: number
  avg_duration_ms: number
  median_duration_ms: number
  avg_tracks_per_artist: number
  avg_tracks_per_album: number
  total_file_size_bytes: number
  total_files: number
}

export interface FormatEntry {
  format: string
  count: number
}

export interface DecadeEntry {
  decade: number
  count: number
}

export interface YearEntry {
  year: number
  count: number
}

export interface TrackRef {
  title: string
  artist: string
  year: number
}

export interface DominantDecade {
  decade: number
  count: number
  percentage: number
}

export interface TagEntry {
  name: string
  track_count: number
  artist_count: number
}

export interface RareTag {
  name: string
  artist_count: number
}

export interface TagPair {
  tag1: string
  tag2: string
  shared_artists: number
}

export interface ArtistCount {
  name: string
  count: number
}

export interface ArtistPlaytime {
  name: string
  duration_ms: number
}

export interface OneTrackArtists {
  count: number
  percentage: number
}

export interface AlbumTrackEntry {
  title: string
  artist: string
  track_count: number
}

export interface AlbumDurationEntry {
  title: string
  artist: string
  duration_ms: number
  track_count: number
}

export interface ProfileAverages {
  energy: number
  darkness: number
  tempo: number
  texture: number
  count: number
}

export interface DistributionBin {
  bin: number
  label: string
  count: number
}

export interface ProfileDistributions {
  energy: DistributionBin[]
  darkness: DistributionBin[]
  tempo: DistributionBin[]
  texture: DistributionBin[]
}

export interface ClusterArtist {
  name: string
  weight: number
}

export interface ClusterTag {
  name: string
  count: number
}

export interface SceneCluster {
  id: number
  name: string
  size: number
  top_artists: ClusterArtist[]
  top_tags: ClusterTag[]
}

export interface BpmEntry {
  bpm: number
  count: number
}

export interface KeyEntry {
  key: string
  count: number
}

export interface AudioAverages {
  avg_bpm: number
  avg_loudness_rms: number
  avg_spectral_centroid: number
  analyzed_count: number
}

export interface ArcTypeEntry {
  arc_type: string
  count: number
  avg_time_ms: number
}

export interface UsedTrack {
  title: string
  artist: string
  usage_count: number
}

export interface FunTitle {
  title: string
  length: number
  artist: string
}

export interface FunTrack {
  title: string
  duration_ms: number
  artist: string
}

export interface WordCount {
  word: string
  count: number
}

export interface PathEntry {
  path: string
  length?: number
  depth?: number
}

export interface FunStats {
  longest_titles: FunTitle[]
  longest_tracks: FunTrack[]
  shortest_tracks: FunTrack[]
  common_title_words: WordCount[]
  common_artist_words: WordCount[]
  longest_paths: PathEntry[]
  deepest_paths: PathEntry[]
}

// ── Cultural Map ──────────────────────────────────────────────────

export interface CulturalGravityEntry {
  tag: string
  artist_count: number
}

export interface TagEvolutionDecade {
  decade: number
  tags: { tag: string; artist_count: number }[]
}

export interface GenrePurity {
  pure: number
  hybrid: number
  highly_hybrid: number
  total_tagged_artists: number
  pure_pct: number
  hybrid_pct: number
  highly_hybrid_pct: number
}

export interface CulturalMapData {
  cultural_gravity: CulturalGravityEntry[]
  tag_evolution: TagEvolutionDecade[]
  genre_purity: GenrePurity
}

// ── Darkness Index ────────────────────────────────────────────────

export interface DarknessKeyword {
  word: string
  count: number
}

export interface DarknessProfileDistribution {
  very_dark: number
  dark: number
  neutral: number
  light: number
  very_light: number
  avg_darkness: number
  total: number
}

export interface DarkestArtist {
  name: string
  avg_darkness: number
  track_count: number
}

export interface DarknessIndexData {
  keyword_counts: DarknessKeyword[]
  total_dark_title_tracks: number
  total_tracks: number
  dark_title_pct: number
  profile_distribution: DarknessProfileDistribution | null
  darkest_artists: DarkestArtist[]
}

// ── Longform & Title Archetypes ───────────────────────────────────

export interface LongformThresholds {
  over_10min: number
  over_15min: number
  over_20min: number
  over_30min: number
  total_tracks: number
}

export interface LongformTrack {
  title: string
  artist: string
  duration_ms: number
}

export interface TitleArchetype {
  pattern: string
  count: number
}

export interface LongformData {
  thresholds: LongformThresholds
  longest_tracks: LongformTrack[]
  title_archetypes: TitleArchetype[]
}

// ── Collection Archaeology ────────────────────────────────────────

export interface CompilationStats {
  compilation_tracks: number
  total_tracks: number
  compilation_pct: number
}

export interface CompilationArtist {
  name: string
  track_count: number
}

export interface ForgottenStats {
  forgotten_count: number
  total_tracks: number
  forgotten_pct: number
}

export interface ForgottenTrack {
  title: string
  artist: string
  year: number | null
  duration_ms: number
}

export interface TemporalBiasEntry {
  decade: number
  library_count: number
  library_pct: number
  usage_count: number
  usage_pct: number
}

export interface ArchaeologyData {
  compilation: CompilationStats
  compilation_artists: CompilationArtist[]
  forgotten: ForgottenStats
  forgotten_sample: ForgottenTrack[]
  temporal_bias: TemporalBiasEntry[]
}

// ── Genre Gateways ────────────────────────────────────────────────

export interface BridgeArtist {
  name: string
  tag_count: number
  tags: string[]
}

export interface GenreBridge {
  tag1: string
  tag2: string
  bridge_count: number
}

export interface GatewaysData {
  bridge_artists: BridgeArtist[]
  genre_bridges: GenreBridge[]
}

export interface ObservatoryData {
  collection: CollectionOverviewStats
  formats: FormatEntry[]
  decades: DecadeEntry[]
  years: YearEntry[]
  oldest_year: number | null
  newest_year: number | null
  oldest_tracks: TrackRef[]
  newest_tracks: TrackRef[]
  dominant_decade: DominantDecade | null
  top_tags: TagEntry[]
  rare_tags: RareTag[]
  tag_pairs: TagPair[]
  top_artists_by_tracks: ArtistCount[]
  top_artists_by_playtime: ArtistPlaytime[]
  top_artists_by_albums: ArtistCount[]
  one_track_artists: OneTrackArtists
  albums_most_tracks: AlbumTrackEntry[]
  albums_longest: AlbumDurationEntry[]
  albums_shortest: AlbumDurationEntry[]
  profile_averages: ProfileAverages | null
  profile_distributions: ProfileDistributions | null
  clusters: SceneCluster[]
  bpm_distribution: BpmEntry[]
  key_distribution: KeyEntry[]
  audio_averages: AudioAverages | null
  total_playlists: number
  arc_type_breakdown: ArcTypeEntry[]
  most_used_tracks: UsedTrack[]
  fun_stats: FunStats
  // Music Archaeology sections
  cultural_map: CulturalMapData
  darkness_index: DarknessIndexData
  longform: LongformData
  archaeology: ArchaeologyData
  gateways: GatewaysData
}
