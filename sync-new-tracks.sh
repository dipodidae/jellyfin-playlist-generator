#!/usr/bin/env bash
#
# sync-new-tracks.sh — Incrementally add new tracks and run all analysis.
#
# Hits the /sync/full-pipeline endpoint which chains:
#   1.  scan            — Incremental file scan (new/changed files only)
#   1b. musicbrainz     — Resolve MusicBrainz IDs for artists & albums
#   2.  lastfm          — Enrich new artists from Last.fm
#   2b. metal_archives  — Enrich album legitimacy from Metal Archives
#   2c. release_dates   — Resolve true original release dates (Discogs/MB/file)
#   3.  embeddings      — Generate embeddings for unprocessed tracks
#   4.  profiles        — Generate 4D profiles for unprocessed tracks
#   5.  clusters        — Rebuild scene/artist clusters (global operation)
#   5b. banger_flags    — Compute banger detection flags
#   6.  audio           — Audio feature analysis (optional, off by default)
#   7.  vectors         — Rebuild BM25 search vectors
#
# Designed to run in a screen/tmux session. Safe to re-run at any time;
# each step only processes what hasn't been done yet.
#
# USAGE
#   ./sync-new-tracks.sh [OPTIONS]
#
#   -h, --help           Show this help and exit
#       --skip-lastfm    Skip Last.fm enrichment (faster, avoids API limits)
#       --with-audio     Include audio analysis (slow on Pi, off by default)
#
# EXAMPLES
#   ./sync-new-tracks.sh                     # Full incremental sync
#   ./sync-new-tracks.sh --skip-lastfm       # Skip Last.fm (faster)
#   ./sync-new-tracks.sh --with-audio        # Include audio analysis
#
# RUNNING IN SCREEN
#   screen -S sync ./sync-new-tracks.sh
#   screen -r sync   # Reattach if disconnected

set -euo pipefail

# ─── Script identity ─────────────────────────────────────────────────────────

readonly SCRIPT_PATH="${BASH_SOURCE[0]}"
readonly SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
readonly SCRIPT_NAME="$(basename "${SCRIPT_PATH}")"
readonly SERVICE_DIR="${SCRIPT_DIR}/service"
readonly ENV_FILE="${SERVICE_DIR}/.env"
readonly BACKEND_URL="http://localhost:8000"

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

_ts() { date '+%H:%M:%S'; }
log_info() { printf '%s [INFO]  %s\n' "$(_ts)" "$*"; }
log_ok() { printf "%s [  OK]  %b%s%b\n" "$(_ts)" "${CLR_GREEN}" "$*" "${CLR_RESET}"; }
log_warn() { printf "%s [WARN]  %b%s%b\n" "$(_ts)" "${CLR_YELLOW}" "$*" "${CLR_RESET}" >&2; }
log_err() { printf "%s [ERR]   %b%s%b\n" "$(_ts)" "${CLR_RED}" "$*" "${CLR_RESET}" >&2; }
log_step() { printf "\n%b━━━ %s ━━━%b\n" "${CLR_BOLD}${CLR_CYAN}" "$*" "${CLR_RESET}"; }

# ─── Defaults ─────────────────────────────────────────────────────────────────

OPT_SKIP_LASTFM="false"
OPT_WITH_AUDIO="false"

# ─── Usage ───────────────────────────────────────────────────────────────────

usage() {
	sed -n 's/^# \{0,1\}//p; /^set -/q' "${SCRIPT_PATH}" | head -n -1
	exit 0
}

# ─── Argument parsing ────────────────────────────────────────────────────────

parse_args() {
	while [[ $# -gt 0 ]]; do
		case "$1" in
		-h | --help) usage ;;
		--skip-lastfm) OPT_SKIP_LASTFM="true" ;;
		--with-audio) OPT_WITH_AUDIO="true" ;;
		*)
			log_err "Unknown option: $1"
			log_err "Run './${SCRIPT_NAME} --help' for usage."
			exit 1
			;;
		esac
		shift
	done
}

# ─── Preflight checks ────────────────────────────────────────────────────────

require_command() {
	local cmd="$1"
	local hint="${2:-Install ${cmd} first.}"
	if ! command -v "${cmd}" >/dev/null 2>&1; then
		log_err "'${cmd}' not found. ${hint}"
		exit 1
	fi
}

require_backend() {
	local attempts=3
	local delay=5
	local i
	log_info "Checking backend at ${BACKEND_URL}..."
	for ((i = 1; i <= attempts; i++)); do
		if curl -sf "${BACKEND_URL}/health" >/dev/null 2>&1; then
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

# ─── SSE stream consumer ─────────────────────────────────────────────────────
#
# Reads the SSE stream from /sync/full-pipeline, prints coloured progress,
# and exits 0 on success or 1 on error.

consume_pipeline_stream() {
	local url="$1"

	curl -sf -N -X POST "${url}" | python3 -u -c "
import sys, json

stage_labels = {
    'scan':            'Scanning',
    'musicbrainz':     'MusicBrainz',
    'lastfm':          'Last.fm',
    'metal_archives':  'Metal Archives',
    'release_dates':   'Release dates',
    'embeddings':      'Embeddings',
    'profiles':        'Profiles',
    'clusters':        'Clustering',
    'banger_flags':    'Banger detection',
    'audio':           'Audio',
    'search_vectors':  'Search vectors',
    'complete':        'Complete',
    'error':           'Error',
}

prev_stage = None
got_done = False

for raw in sys.stdin:
    raw = raw.strip()
    if not raw.startswith('data:'):
        continue
    try:
        d = json.loads(raw[5:].strip())
    except json.JSONDecodeError:
        continue

    stage    = d.get('stage', '')
    msg      = d.get('message', '')
    progress = d.get('progress', '')
    err_msg  = d.get('error', '')
    done     = d.get('done', False)

    label = stage_labels.get(stage, stage)

    if stage != prev_stage and stage not in ('complete', 'error'):
        print(f'\n  [{label}]', flush=True)
        prev_stage = stage

    if msg:
        pct = f'[{progress:3d}%] ' if isinstance(progress, int) else ''
        print(f'    {pct}{msg}', flush=True)

    if done:
        got_done = True
        if err_msg:
            print(f'\n  ERROR: {err_msg}', file=sys.stderr, flush=True)
            sys.exit(1)

        stats = d.get('stats', {})
        if stats:
            print('\n  Pipeline stats:', flush=True)
            for step, step_stats in stats.items():
                if isinstance(step_stats, dict):
                    summary = ', '.join(f'{k}={v}' for k, v in step_stats.items() if v)
                    print(f'    {step}: {summary}', flush=True)

        sys.exit(0)

if not got_done:
    print('Stream closed without a completion signal.', file=sys.stderr, flush=True)
    sys.exit(2)
"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
	parse_args "$@"

	log_step "Playlist Generator — Sync New Tracks"
	log_info "Script: ${SCRIPT_DIR}/${SCRIPT_NAME}"

	require_command curl "Install curl."
	require_command python3 "Install python3."
	require_backend

	# Build query string
	local qs=""
	if [[ "${OPT_SKIP_LASTFM}" == "true" ]]; then
		qs="${qs}&skip_lastfm=true"
		log_info "Skipping Last.fm enrichment (--skip-lastfm)"
	fi
	if [[ "${OPT_WITH_AUDIO}" == "true" ]]; then
		qs="${qs}&skip_audio=false"
		log_info "Including audio analysis (--with-audio)"
	fi
	# Strip leading &
	qs="${qs#&}"
	[[ -n "${qs}" ]] && qs="?${qs}"

	local url="${BACKEND_URL}/sync/full-pipeline${qs}"
	log_info "Pipeline URL: ${url}"

	local start_time
	start_time="$(date +%s)"

	log_step "Running pipeline"

	if consume_pipeline_stream "${url}"; then
		local end_time elapsed_min elapsed_sec
		end_time="$(date +%s)"
		elapsed_sec=$((end_time - start_time))
		elapsed_min=$((elapsed_sec / 60))
		elapsed_rem=$((elapsed_sec % 60))

		echo
		log_ok "Sync complete in ${elapsed_min}m ${elapsed_rem}s"
	else
		echo
		log_err "Pipeline failed. Check backend logs:"
		log_err "  journalctl --user -u playlist-generator-backend --since '5 min ago'"
		exit 1
	fi
}

main "$@"
