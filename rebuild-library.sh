#!/usr/bin/env bash
#
# rebuild-library.sh — Flush and rebuild the playlist-generator music library.
#
# Runs the complete enrichment pipeline in order:
#   1. flush      — TRUNCATE all library tables (skip with --no-flush)
#   2. scan       — Scan music files from MUSIC_DIRECTORIES
#   3. lastfm     — Enrich artist metadata from Last.fm
#   4. embeddings — Generate sentence-transformer embeddings for all tracks
#   5. profiles   — Generate 4D semantic profiles (energy/tempo/darkness/texture)
#   6. clusters   — Generate scene/artist clusters for diversity scoring
#   7. audio      — Analyse audio features (BPM/loudness/brightness) via librosa
#
# RESUMABILITY
#   Each step writes a sentinel file to STATE_DIR on success. Re-running the
#   script skips completed steps automatically, so it is safe to re-run after
#   any failure without losing progress.
#
#   Use --force to ignore all checkpoints and run everything from scratch.
#   Use --from=STEP to clear checkpoints from STEP onward and resume there.
#
# USAGE
#   ./rebuild-library.sh [OPTIONS]
#
#   -h, --help           Show this help and exit
#   -f, --force          Ignore all checkpoints; re-run every step
#       --no-flush       Skip the database flush (incremental rebuild)
#       --from=STEP      Restart from STEP, clearing later checkpoints
#                        Steps: flush scan lastfm embeddings profiles clusters audio
#       --skip-audio     Skip the long-running audio analysis step
#       --state-dir=DIR  Override checkpoint directory
#                        Default: ~/.local/state/playlist-generator/rebuild
#
# EXAMPLES
#   ./rebuild-library.sh                      # Full flush + rebuild
#   ./rebuild-library.sh --no-flush           # Re-run enrichment without wiping DB
#   ./rebuild-library.sh --from=embeddings    # Re-run from embeddings step onward
#   ./rebuild-library.sh --force --skip-audio # Force full rebuild, skip audio
#
# RUNNING IN SCREEN
#   screen -S rebuild ./rebuild-library.sh
#   screen -r rebuild   # Reattach if disconnected

set -euo pipefail

# ─── Script identity ─────────────────────────────────────────────────────────

readonly SCRIPT_PATH="${BASH_SOURCE[0]}"
readonly SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
readonly SCRIPT_NAME="$(basename "${SCRIPT_PATH}")"
readonly SERVICE_DIR="${SCRIPT_DIR}/service"
readonly VENV="${SERVICE_DIR}/.venv"
readonly ENV_FILE="${SERVICE_DIR}/.env"
readonly BACKEND_URL="http://localhost:8000"

# Pipeline steps in execution order
readonly -a ALL_STEPS=(flush scan lastfm embeddings profiles clusters audio)

# ─── Colour support ──────────────────────────────────────────────────────────

if [[ -t 1 ]] && [[ "${TERM:-}" != "dumb" ]]; then
  CLR_RED='\033[0;31m'
  CLR_GREEN='\033[0;32m'
  CLR_YELLOW='\033[1;33m'
  CLR_CYAN='\033[0;36m'
  CLR_BOLD='\033[1m'
  CLR_RESET='\033[0m'
else
  CLR_RED='' CLR_GREEN='' CLR_YELLOW='' CLR_CYAN='' CLR_BOLD='' CLR_RESET=''
fi

# ─── Logging ─────────────────────────────────────────────────────────────────

_ts()       { date '+%H:%M:%S'; }
log_info()  { printf '%s [INFO]  %s\n'                              "$(_ts)" "$*"; }
log_ok()    { printf "%s [  OK]  %b%s%b\n"  "$(_ts)" "${CLR_GREEN}"  "$*" "${CLR_RESET}"; }
log_warn()  { printf "%s [WARN]  %b%s%b\n"  "$(_ts)" "${CLR_YELLOW}" "$*" "${CLR_RESET}" >&2; }
log_err()   { printf "%s [ERR]   %b%s%b\n"  "$(_ts)" "${CLR_RED}"    "$*" "${CLR_RESET}" >&2; }
log_step()  { printf "\n%b━━━ %s ━━━%b\n" "${CLR_BOLD}${CLR_CYAN}" "$*" "${CLR_RESET}"; }

# ─── Defaults (overridable by flags) ─────────────────────────────────────────

OPT_FORCE="false"
OPT_NO_FLUSH="false"
OPT_SKIP_AUDIO="false"
OPT_FROM_STEP=""
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/playlist-generator/rebuild"

# ─── Usage ───────────────────────────────────────────────────────────────────

usage() {
  sed -n 's/^# \{0,1\}//p; /^set -/q' "${SCRIPT_PATH}" | head -n -1
  exit 0
}

# ─── Argument parsing ─────────────────────────────────────────────────────────

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h|--help)      usage ;;
      -f|--force)     OPT_FORCE="true" ;;
      --no-flush)     OPT_NO_FLUSH="true" ;;
      --skip-audio)   OPT_SKIP_AUDIO="true" ;;
      --from=*)       OPT_FROM_STEP="${1#*=}" ;;
      --state-dir=*)  STATE_DIR="${1#*=}" ;;
      *)
        log_err "Unknown option: $1"
        log_err "Run './${SCRIPT_NAME} --help' for usage."
        exit 1
        ;;
    esac
    shift
  done
}

# ─── State / checkpoint management ───────────────────────────────────────────

init_state_dir() {
  mkdir -p "${STATE_DIR}"
  log_info "Checkpoint directory: ${STATE_DIR}"
}

_checkpoint_file() { echo "${STATE_DIR}/$1.done"; }

is_done() {
  local step="$1"
  [[ -f "$(_checkpoint_file "${step}")" ]]
}

mark_done() {
  local step="$1"
  date --iso-8601=seconds > "$(_checkpoint_file "${step}")"
  log_ok "Step '${step}' marked complete"
}

mark_not_done() {
  local step="$1"
  rm -f "$(_checkpoint_file "${step}")"
}

validate_step_name() {
  local step="$1"
  local s
  for s in "${ALL_STEPS[@]}"; do
    [[ "${s}" == "${step}" ]] && return 0
  done
  log_err "Unknown step '${step}'. Valid steps: ${ALL_STEPS[*]}"
  exit 1
}

clear_from_step() {
  local from_step="$1"
  validate_step_name "${from_step}"

  local found=0
  local step
  for step in "${ALL_STEPS[@]}"; do
    [[ "${step}" == "${from_step}" ]] && found=1
    [[ "${found}" -eq 1 ]] && mark_not_done "${step}"
  done
  log_info "Cleared checkpoints from '${from_step}' onward"
}

print_checkpoint_status() {
  log_info "Step status:"
  local step
  for step in "${ALL_STEPS[@]}"; do
    if is_done "${step}"; then
      local ts
      ts="$(cat "$(_checkpoint_file "${step}")" 2>/dev/null || echo 'done')"
      printf "  %-12s %b✓  %s%b\n" "${step}" "${CLR_GREEN}" "${ts}" "${CLR_RESET}"
    else
      printf "  %-12s %b○  pending%b\n" "${step}" "${CLR_YELLOW}" "${CLR_RESET}"
    fi
  done
  echo
}

# ─── Environment / dependency checks ─────────────────────────────────────────

DB_URL=""

load_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    log_err "Missing env file: ${ENV_FILE}"
    log_err "Copy .env.example and configure it, then retry."
    exit 1
  fi

  DB_URL="$(grep -E '^DATABASE_URL=' "${ENV_FILE}" | head -1 | cut -d= -f2- | tr -d "\"'")"

  if [[ -z "${DB_URL}" ]]; then
    log_err "DATABASE_URL not set in ${ENV_FILE}"
    exit 1
  fi

  # Log the URL with password masked
  log_info "Database: $(echo "${DB_URL}" | sed 's|://[^:]*:[^@]*@|://***:***@|')"
}

require_command() {
  local cmd="$1"
  local hint="${2:-Install ${cmd} first.}"
  if ! command -v "${cmd}" > /dev/null 2>&1; then
    log_err "'${cmd}' not found. ${hint}"
    exit 1
  fi
}

require_venv() {
  if [[ ! -x "${VENV}/bin/python3" ]]; then
    log_err "Python venv not found at ${VENV}"
    log_err "Run: cd service && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
  fi
}

require_backend() {
  local attempts=3
  local delay=5
  local i
  log_info "Checking backend at ${BACKEND_URL}..."
  for (( i = 1; i <= attempts; i++ )); do
    if curl -sf "${BACKEND_URL}/health" > /dev/null 2>&1; then
      log_ok "Backend is healthy"
      return 0
    fi
    if [[ "${i}" -lt "${attempts}" ]]; then
      log_warn "Backend not responding (attempt ${i}/${attempts}), retrying in ${delay}s..."
      sleep "${delay}"
    fi
  done
  log_err "Backend is not responding at ${BACKEND_URL} after ${attempts} attempts."
  log_err "Start it: systemctl --user start playlist-generator-backend"
  exit 1
}

# ─── Database helpers ─────────────────────────────────────────────────────────

run_sql() {
  local sql="$1"
  psql --no-psqlrc -q "${DB_URL}" -c "${sql}"
}

query_count() {
  local table="$1"
  psql --no-psqlrc -t -q "${DB_URL}" \
    -c "SELECT COUNT(*) FROM ${table};" 2>/dev/null | tr -d ' \n' || echo '?'
}

# ─── SSE streaming helper ─────────────────────────────────────────────────────
#
# Posts to an enrichment /stream endpoint, prints progress lines, and returns
# the exit status of the job (0 = success, 1 = the server reported an error,
# 2 = stream ended without a completion signal).

stream_enrichment() {
  local label="$1"
  local url="$2"
  local body="${3:-{}}"

  log_info "Starting: ${label}"

  # curl flags: -s silent, -N no buffering, -f fail on HTTP errors
  local pipe_exit=0
  curl -sf -N \
      -X POST \
      -H "Content-Type: application/json" \
      -d "${body}" \
      "${url}" \
    | python3 -u -c "
import sys, json

got_done = False
for raw in sys.stdin:
    raw = raw.strip()
    if not raw.startswith('data:'):
        continue
    try:
        d = json.loads(raw[5:].strip())
    except json.JSONDecodeError:
        continue

    msg      = d.get('message', '')
    progress = d.get('progress', '')
    err_msg  = d.get('error', '')
    done     = d.get('done', False)

    if msg:
        pct = '[{:3d}%] '.format(progress) if isinstance(progress, int) else ''
        print('  ' + pct + msg, flush=True)

    if done:
        got_done = True
        if err_msg:
            print('ERROR: ' + str(err_msg), file=sys.stderr, flush=True)
            sys.exit(1)
        sys.exit(0)

if not got_done:
    print('Stream closed without a completion signal.', file=sys.stderr, flush=True)
    sys.exit(2)
" || pipe_exit=$?

  if [[ "${pipe_exit}" -ne 0 ]]; then
    log_err "${label} stream failed (exit ${pipe_exit})."
    return "${pipe_exit}"
  fi
}

# Retry wrapper: attempt up to N times with exponential back-off.
stream_enrichment_with_retry() {
  local label="$1"
  local url="$2"
  local body="${3:-{}}"
  local max_attempts="${4:-3}"
  local delay=10

  local attempt
  for (( attempt = 1; attempt <= max_attempts; attempt++ )); do
    if stream_enrichment "${label}" "${url}" "${body}"; then
      return 0
    fi
    if [[ "${attempt}" -lt "${max_attempts}" ]]; then
      log_warn "Attempt ${attempt}/${max_attempts} failed. Retrying in ${delay}s..."
      sleep "${delay}"
      delay=$(( delay * 2 ))
    fi
  done

  log_err "${label} failed after ${max_attempts} attempts."
  return 1
}

# ─── CLI helper ───────────────────────────────────────────────────────────────

run_cli() {
  (cd "${SERVICE_DIR}" && "${VENV}/bin/python3" -m app.cli_v3 "$@")
}

# ─── Pipeline steps ───────────────────────────────────────────────────────────

step_flush() {
  log_step "Step 1/7 — Flush library data"

  if [[ "${OPT_NO_FLUSH}" == "true" ]]; then
    log_info "Skipping flush (--no-flush passed)."
    mark_done flush
    return 0
  fi

  local track_count
  track_count="$(query_count tracks)"
  log_info "Current library: ${track_count} tracks — flushing all library tables..."
  log_warn "path_mappings, scan_directories, and generated_playlists will be preserved."

  run_sql "TRUNCATE
    tracks, artists, albums, genres,
    scene_clusters, sync_metadata,
    scan_jobs, scan_job_events
    CASCADE;"

  log_ok "Database flushed."
  mark_done flush
}

step_scan() {
  log_step "Step 2/7 — Scan music files"
  log_info "Scanning MUSIC_DIRECTORIES (full scan)..."

  run_cli scan --full

  local track_count
  track_count="$(query_count tracks)"
  log_ok "Scan complete: ${track_count} tracks in database."
  mark_done scan
}

step_lastfm() {
  log_step "Step 3/7 — Last.fm enrichment"

  local artist_count
  artist_count="$(query_count artists)"
  log_info "Enriching ${artist_count} artists from Last.fm..."

  run_cli enrich-lastfm

  mark_done lastfm
}

step_embeddings() {
  log_step "Step 4/7 — Generate embeddings"

  local pending
  pending="$(psql --no-psqlrc -t -q "${DB_URL}" \
    -c "SELECT COUNT(*) FROM tracks t
        LEFT JOIN track_embeddings te ON t.id = te.track_id
        WHERE te.track_id IS NULL;" 2>/dev/null | tr -d ' \n' || echo '?')"
  log_info "Tracks needing embeddings: ${pending}"

  run_cli generate-embeddings

  mark_done embeddings
}

step_profiles() {
  log_step "Step 5/7 — Generate semantic profiles"

  local pending
  pending="$(psql --no-psqlrc -t -q "${DB_URL}" \
    -c "SELECT COUNT(*) FROM tracks t
        LEFT JOIN track_profiles tp ON t.id = tp.track_id
        WHERE tp.track_id IS NULL;" 2>/dev/null | tr -d ' \n' || echo '?')"
  log_info "Tracks needing profiles: ${pending}"

  run_cli generate-profiles

  mark_done profiles
}

step_clusters() {
  log_step "Step 6/7 — Scene clustering"
  require_backend

  stream_enrichment_with_retry \
    "Scene clustering" \
    "${BACKEND_URL}/enrich/clusters/stream"

  local cluster_count
  cluster_count="$(query_count scene_clusters)"
  log_ok "Clustering complete: ${cluster_count} scene clusters."
  mark_done clusters
}

step_audio() {
  log_step "Step 7/7 — Audio feature analysis"

  if [[ "${OPT_SKIP_AUDIO}" == "true" ]]; then
    log_warn "Skipping audio analysis (--skip-audio)."
    log_warn "Re-run without --skip-audio later to populate BPM/loudness/brightness."
    mark_done audio
    return 0
  fi

  require_backend

  local unanalyzed
  unanalyzed="$(psql --no-psqlrc -t -q "${DB_URL}" \
    -c "SELECT COUNT(*) FROM tracks t
        LEFT JOIN track_audio_features taf ON t.id = taf.track_id
        WHERE taf.track_id IS NULL;" 2>/dev/null | tr -d ' \n' || echo '?')"

  if [[ "${unanalyzed}" == "0" ]]; then
    log_ok "All tracks already have audio features — nothing to do."
    mark_done audio
    return 0
  fi

  log_info "${unanalyzed} tracks need audio analysis (BPM, loudness, spectral features)."
  log_warn "Audio analysis is long-running (up to several hours for large libraries)."
  log_warn "It runs in the backend as a background job and continues if this script exits."

  local response
  response="$(curl -sf -X POST "${BACKEND_URL}/enrich/audio" || true)"
  if [[ -z "${response}" ]]; then
    log_warn "No response from /enrich/audio — backend may be unavailable."
    log_warn "Start it manually: systemctl --user start playlist-generator-backend"
    log_warn "Then POST to ${BACKEND_URL}/enrich/audio"
  else
    log_info "Backend response: ${response}"
    log_ok "Audio analysis job started (running in backend background)."
  fi

  log_info "Monitor progress:"
  log_info "  journalctl --user -u playlist-generator-backend -f"
  log_info "Or re-run this script later — the audio step will skip already-analysed tracks."

  # Mark done so we don't re-fire the background job on every re-run.
  # The analysis itself is idempotent (only processes un-analysed tracks).
  mark_done audio
}

# ─── Exit trap ───────────────────────────────────────────────────────────────

_on_exit() {
  local code=$?
  if [[ "${code}" -ne 0 ]]; then
    echo
    log_err "Rebuild exited with code ${code}."
    log_err "Re-run './${SCRIPT_NAME}' to resume from the last incomplete step."
    log_err "Or use './${SCRIPT_NAME} --from=STEP' to restart a specific step."
    log_err "Checkpoints: ${STATE_DIR}"
  fi
}

trap '_on_exit' EXIT

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
  parse_args "$@"

  log_step "Playlist Generator — Library Rebuild"
  log_info "Script: ${SCRIPT_DIR}/${SCRIPT_NAME}"
  log_info "Service: ${SERVICE_DIR}"

  # Validate dependencies before touching anything
  load_env
  require_command psql "Install postgresql-client."
  require_command curl "Install curl."
  require_venv
  init_state_dir

  # Apply --force: wipe all checkpoints
  if [[ "${OPT_FORCE}" == "true" ]]; then
    log_info "--force: clearing all checkpoints."
    local step
    for step in "${ALL_STEPS[@]}"; do
      mark_not_done "${step}"
    done
  fi

  # Apply --from=STEP: clear that step and everything after
  if [[ -n "${OPT_FROM_STEP}" ]]; then
    clear_from_step "${OPT_FROM_STEP}"
  fi

  print_checkpoint_status

  # Execute pipeline
  local step
  for step in "${ALL_STEPS[@]}"; do
    if is_done "${step}"; then
      log_info "Skipping '${step}' (checkpoint exists — use --from=${step} to re-run)."
      continue
    fi

    if ! "step_${step}"; then
      log_err "Step '${step}' failed. Fix the issue and re-run to resume from here."
      exit 1
    fi
  done

  # ── Summary ──────────────────────────────────────────────────────────────
  log_step "All steps complete"
  log_info "Final library stats:"
  printf "  %-25s %s\n" "tracks:"              "$(query_count tracks)"
  printf "  %-25s %s\n" "track_embeddings:"    "$(query_count track_embeddings)"
  printf "  %-25s %s\n" "track_profiles:"      "$(query_count track_profiles)"
  printf "  %-25s %s\n" "track_audio_features:""$(query_count track_audio_features)"
  printf "  %-25s %s\n" "scene_clusters:"      "$(query_count scene_clusters)"
  printf "  %-25s %s\n" "artist_clusters:"     "$(query_count artist_clusters)"
  echo
  log_ok "Rebuild complete. Checkpoints: ${STATE_DIR}"
}

main "$@"
