const STAGE_LABELS: Record<string, string> = {
  idle: 'Idle',
  starting: 'Starting',
  discovering: 'Discovering files',
  scanning_files: 'Scanning files',
  saving_tracks: 'Saving tracks',
  complete: 'Complete',
  error: 'Error',
}

export function useStageLabel() {
  function stageLabel(stage: string): string {
    return STAGE_LABELS[stage] ?? 'Scanning'
  }

  return { stageLabel }
}
