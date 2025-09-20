#!/usr/bin/env bashio
# shellcheck shell=bash

# Fail fast and loud (but don't print commands unless debug=true)
set -euo pipefail

CONFIG_PATH="/data/options.json"

# Read options from Home Assistant (with sensible fallbacks)
KEEP_DAYS="$(bashio::config 'keep_days' || echo 0)"
MAX_FILES="$(bashio::config 'max_files' || echo 500)"
TIMEOUT="$(bashio::config 'timeout' || echo 40)"
INTERVAL_MINUTES="$(bashio::config 'interval_minutes' || echo 180)"
DEBUG="$(bashio::config 'debug' || echo false)"
MIRROR_MISSING="$(bashio::config 'mirror_missing' || echo false)"
ALBUMS="$(bashio::config 'albums' || echo '')"

# If debug is true, enable shell xtrace; otherwise stay quiet.
if [[ "${DEBUG}" == "true" ]]; then
  set -x
  bashio::log.info "Debug mode enabled for shell wrapper"
fi

# Guard: albums must be provided
if [[ -z "${ALBUMS}" || "${ALBUMS}" == "null" ]]; then
  bashio::log.error "The 'albums' option is empty. Please provide albums YAML in the add-on configuration."
  exit 1
fi

# Convert INTERVAL_MINUTES to a sane integer; treat non-numeric as 0 (run once)
if ! [[ "${INTERVAL_MINUTES}" =~ ^[0-9]+$ ]]; then
  bashio::log.warning "interval_minutes='${INTERVAL_MINUTES}' is not a number. Will run once and exit."
  INTERVAL_MINUTES=0
fi

run_once() {
  # Build CLI args safely (no eval). Preserve whitespace/newlines in --albums with quoting.
  local -a ARGS=(
    --keep-days "${KEEP_DAYS}"
    --max-files "${MAX_FILES}"
    --timeout "${TIMEOUT}"
    --debug "${DEBUG}"
    --mirror-missing "${MIRROR_MISSING}"
    --albums "${ALBUMS}"
  )

  # Hand off to the Python sync
  python3 /app/sync.py "${ARGS[@]}"
}

# Trap termination for clean exits when the add-on stops
term_handler() {
  bashio::log.info "Termination signal received; exiting."
  exit 0
}
trap term_handler SIGTERM SIGINT

if [[ "${INTERVAL_MINUTES}" -le 0 ]]; then
  # Run once and exit
  bashio::log.info "Running one-time sync (interval_minutes=${INTERVAL_MINUTES})."
  run_once
  bashio::log.info "One-time sync complete."
  exit 0
fi

# Recurring loop
bashio::log.info "Starting recurring sync every ${INTERVAL_MINUTES} minute(s)."
while true; do
  run_once
  # Sleep the configured interval
  sleep "$(( INTERVAL_MINUTES * 60 ))" &
  wait $!
done
