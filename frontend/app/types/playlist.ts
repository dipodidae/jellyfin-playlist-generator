export interface Track {
  id: string
  title: string
  artist_name: string
  album_name: string
  year: number
  duration_ms: number
  explanation?: string
}

export interface GeneratedPlaylist {
  id?: string
  prompt: string
  title: string
  playlist_size: number
  tracks: Track[]
  partial?: boolean
  warning?: string
}

export interface ProgressEvent {
  stage: 'parsing' | 'trajectory' | 'candidates' | 'matching' | 'composing' | 'metrics' | 'explaining' | 'titling' | 'complete' | 'error'
  progress: number
  message: string
  phase?: string
  playlist?: GeneratedPlaylist
  error?: string
}

export interface JellyfinStatus {
  available: boolean
  configured: boolean
  server_name: string | null
  version: string | null
  error: string | null
}

export interface JellyfinExportResult {
  success: boolean
  error: string | null
  jellyfin_playlist_id: string | null
  jellyfin_url: string | null
  matched_count: number
  total_count: number
  unmatched_tracks: Array<{ title: string, artist_name: string }>
}
