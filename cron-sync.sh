#!/usr/bin/env bash
#
# cron-sync.sh — Scheduled incremental sync for the playlist generator.
#
# Detects new/changed music files and, if any exist, runs the FULL enrichment
# pipeline (incremental scan + every scannable parameter, audio included) by
# hitting the live Docker container's /sync/full-pipeline endpoint.
#
# The live deployment is the `playlist-generator` container (compose `unified`
# profile), which publishes no host port — uvicorn listens on 127.0.0.1:8000
# *inside* the container behind nginx basic-auth. We reach it auth-free with
# `docker exec ... curl 127.0.0.1:8000`, which also bypasses SWAG entirely.
#
# Pipeline chained by the endpoint (each step incremental):
#   scan → MusicBrainz → Last.fm → Metal Archives → release dates →
#   embeddings → profiles → clusters → banger flags → search vectors
# With skip_audio=false the slow librosa audio analysis is included too.
#
# USAGE
#   ./cron-sync.sh [OPTIONS]
#
#   -h, --help      Show this help and exit
#       --catch-up  Skip the new-file gate; run the pipeline unconditionally
#                   (weekly safety net to clear backlog from failed runs)
#
# BEHAVIOUR
#   * Container down/unhealthy        → log + exit 0, stamp untouched (retry later)
#   * No new files (default mode)     → log + exit 0, backend never touched
#   * Pipeline error / scan running   → log + exit non-zero, stamp untouched
#   * Clean completion                → advance stamp to the run's start time
#
# CRON (in ~/nas crontab, flock-guarded against overlap)
#   15 */6 * * *  flock -n /tmp/nas-playlist-sync.lock <repo>/cron-sync.sh
#   45 3 * * 0    flock -n /tmp/nas-playlist-sync.lock <repo>/cron-sync.sh --catch-up

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

readonly CONTAINER="playlist-generator"
readonly INTERNAL_URL="http://127.0.0.1:8000"
readonly MUSIC_DIR="/mnt/drive/music"
readonly STAMP_FILE="${XDG_STATE_HOME:-${HOME}/.local/state}/playlist-generator/cron-sync.stamp"

# Audio extensions recognised by the scanner (ingestion/scanner.py AUDIO_EXTENSIONS).
readonly -a AUDIO_EXTS=(flac mp3 ogg m4a opus wav aiff aif)

# ─── Logging ─────────────────────────────────────────────────────────────────

_ts() { date '+%Y-%m-%d %H:%M:%S'; }
log_info() { printf '%s [INFO]  %s\n' "$(_ts)" "$*"; }
log_ok() { printf '%s [  OK]  %s\n' "$(_ts)" "$*"; }
log_warn() { printf '%s [WARN]  %s\n' "$(_ts)" "$*" >&2; }
log_err() { printf '%s [ERR]   %s\n' "$(_ts)" "$*" >&2; }

# ─── Options ─────────────────────────────────────────────────────────────────

OPT_CATCH_UP="false"

usage() {
	sed -n 's/^# \{0,1\}//p; /^set -/q' "${BASH_SOURCE[0]}" | head -n -1
	exit 0
}

parse_args() {
	while [[ $# -gt 0 ]]; do
		case "$1" in
		-h | --help) usage ;;
		--catch-up) OPT_CATCH_UP="true" ;;
		*)
			log_err "Unknown option: $1 (try --help)"
			exit 1
			;;
		esac
		shift
	done
}

# ─── Preflight ───────────────────────────────────────────────────────────────

require_command() {
	command -v "$1" >/dev/null 2>&1 || {
		log_err "'$1' not found in PATH."
		exit 1
	}
}

# Verify the container exists, is running, and its backend answers /health.
require_container_healthy() {
	if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
		log_warn "Container '${CONTAINER}' is not running. Skipping this cycle."
		exit 0
	fi
	if ! docker exec "${CONTAINER}" curl -sf "${INTERNAL_URL}/health" >/dev/null 2>&1; then
		log_warn "Backend in '${CONTAINER}' did not answer /health. Skipping this cycle."
		exit 0
	fi
	log_info "Container '${CONTAINER}' is healthy."
}

# ─── New-file gate ───────────────────────────────────────────────────────────

# Build the find expression for audio extensions: \( -iname '*.flac' -o ... \)
_find_audio_predicate() {
	local -a expr=('(')
	local i ext
	for i in "${!AUDIO_EXTS[@]}"; do
		ext="${AUDIO_EXTS[$i]}"
		[[ "${i}" -gt 0 ]] && expr+=(-o)
		expr+=(-iname "*.${ext}")
	done
	expr+=(')')
	printf '%s\n' "${expr[@]}"
}

# Returns 0 (has new work) if any audio file is newer than the stamp, or if no
# stamp exists yet (first run). Returns 1 if nothing changed.
has_new_files() {
	if [[ ! -d "${MUSIC_DIR}" ]]; then
		log_warn "Music directory '${MUSIC_DIR}' not found. Skipping this cycle."
		exit 0
	fi

	local -a predicate
	mapfile -t predicate < <(_find_audio_predicate)

	if [[ ! -f "${STAMP_FILE}" ]]; then
		log_info "No stamp yet (first run) — treating library as new."
		return 0
	fi

	local hit
	hit="$(find "${MUSIC_DIR}" -type f "${predicate[@]}" -newer "${STAMP_FILE}" -print -quit 2>/dev/null)"
	if [[ -n "${hit}" ]]; then
		log_info "New/changed file detected (e.g. ${hit#"${MUSIC_DIR}"/})."
		return 0
	fi
	return 1
}

# ─── Pipeline run ────────────────────────────────────────────────────────────

# POST to /sync/full-pipeline inside the container and parse the SSE stream.
# Exits 0 on a clean completion, non-zero on error / premature close / 409.
run_pipeline() {
	local url="${INTERNAL_URL}/sync/full-pipeline?skip_audio=false"
	log_info "Starting full pipeline (audio included): ${url}"

	# docker exec runs curl inside the container; we parse the SSE stream on the
	# host with python3. set +e so we can capture the pipeline's exit status.
	set +o pipefail
	docker exec "${CONTAINER}" curl -sf -N -X POST "${url}" 2>/dev/null |
		python3 -u -c '
import sys, json

stage_labels = {
    "scan": "Scanning", "musicbrainz": "MusicBrainz", "lastfm": "Last.fm",
    "metal_archives": "Metal Archives", "release_dates": "Release dates",
    "embeddings": "Embeddings", "profiles": "Profiles", "clusters": "Clustering",
    "banger_flags": "Banger detection", "audio": "Audio",
    "search_vectors": "Search vectors", "complete": "Complete", "error": "Error",
}
prev = None
got_done = False
for raw in sys.stdin:
    raw = raw.strip()
    if not raw.startswith("data:"):
        continue
    try:
        d = json.loads(raw[5:].strip())
    except json.JSONDecodeError:
        continue
    stage = d.get("stage", "")
    msg = d.get("message", "")
    progress = d.get("progress", "")
    err = d.get("error", "")
    label = stage_labels.get(stage, stage)
    if stage != prev and stage not in ("complete", "error"):
        print("  [%s]" % label, flush=True)
        prev = stage
    if msg:
        pct = "[%3d%%] " % progress if isinstance(progress, int) else ""
        print("    %s%s" % (pct, msg), flush=True)
    if d.get("done"):
        got_done = True
        if err:
            print("  ERROR: %s" % err, file=sys.stderr, flush=True)
            sys.exit(1)
        stats = d.get("stats", {})
        if stats:
            print("  Pipeline stats:", flush=True)
            for step, s in stats.items():
                if isinstance(s, dict):
                    summary = ", ".join("%s=%s" % (k, v) for k, v in s.items() if v)
                    if summary:
                        print("    %s: %s" % (step, summary), flush=True)
        sys.exit(0)
if not got_done:
    print("Stream closed without a completion signal.", file=sys.stderr, flush=True)
    sys.exit(2)
'
	local rc="${PIPESTATUS[1]}"
	local curl_rc="${PIPESTATUS[0]}"
	set -o pipefail

	# curl -f returns 22 on HTTP >=400 (e.g. 409 scan already running).
	if [[ "${curl_rc}" -eq 22 ]]; then
		log_warn "Backend returned an HTTP error (likely 409: scan already running). Skipping."
		return 1
	fi
	return "${rc}"
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
	parse_args "$@"

	require_command docker
	require_command python3
	require_container_healthy

	if [[ "${OPT_CATCH_UP}" == "true" ]]; then
		log_info "Catch-up mode: running pipeline unconditionally."
	elif ! has_new_files; then
		log_ok "No new or changed files since last sync — nothing to do."
		exit 0
	fi

	# Capture the run's start time; promote it to the stamp only on success so
	# files arriving mid-run are still caught next cycle.
	mkdir -p "$(dirname "${STAMP_FILE}")"
	local pending="${STAMP_FILE}.pending"
	: >"${pending}"

	local start end elapsed
	start="$(date +%s)"

	if run_pipeline; then
		end="$(date +%s)"
		elapsed=$((end - start))
		mv -f "${pending}" "${STAMP_FILE}"
		log_ok "Sync complete in $((elapsed / 60))m $((elapsed % 60))s. Stamp advanced."
	else
		rm -f "${pending}"
		log_err "Pipeline did not complete cleanly. Stamp left unchanged (will retry)."
		exit 1
	fi
}

main "$@"
