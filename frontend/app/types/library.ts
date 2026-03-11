export interface LibraryStats {
  tracks: number
  artists: number
  albums: number
  genres: number
  lastfm_tags: number
  playlists: number
  track_files?: number
  missing_files?: number
  artists_with_tags?: number
  artist_similarities?: number
  tracks_with_tags?: number
  tracks_with_embeddings?: number
  tracks_with_profiles?: number
}

export interface ScanStats {
  files_found: number
  files_scanned: number
  files_skipped: number
  tracks_added: number
  tracks_updated: number
  files_missing: number
  errors: number
}

export interface ScanEvent {
  created_at?: string | null
  stage: string
  event_type?: string
  message: string
  current: number
  total: number
}

export interface ScanStatus {
  is_running: boolean
  operation: string | null
  job_id: string | null
  status: string
  scan_type: string | null
  stage: string
  started_at: string | null
  updated_at: string | null
  completed_at: string | null
  current: number
  total: number
  progress: number
  message: string
  error: string | null
  stats: ScanStats
  source: string
  is_live: boolean
  events?: ScanEvent[]
}

export interface PathMapping {
  id: string
  name: string
  source_prefix: string
  target_prefix: string
  priority: number
}
