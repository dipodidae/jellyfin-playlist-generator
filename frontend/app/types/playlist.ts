export interface Track {
  id: string
  title: string
  artist_name: string
  album_name: string
  year: number
  duration_ms: number
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
  stage: 'parsing' | 'trajectory' | 'candidates' | 'matching' | 'composing' | 'saving' | 'complete' | 'error'
  progress: number
  message: string
  phase?: string
  playlist?: GeneratedPlaylist
  error?: string
}
