#!/usr/bin/env bashio
# shellcheck shell=bash

set -u -o pipefail

read_option() {
  local key="$1"
  local fallback="$2"
  local value
  value="$(python3 -c '
import json
import sys

try:
    with open("/data/options.json", "r", encoding="utf-8") as handle:
        value = json.load(handle).get(sys.argv[1])
except (OSError, ValueError):
    value = None

if isinstance(value, bool):
    print("true" if value else "false")
elif value is not None:
    print(value)
' "$key")"
  if [[ -z "$value" || "$value" == "null" ]]; then
    printf '%s' "$fallback"
  else
    printf '%s' "$value"
  fi
}

INTERVAL_MINUTES="$(read_option interval_minutes 180)"
TIMEOUT="$(read_option timeout 40)"
KEEP_DAYS="$(read_option keep_days 0)"
MAX_FILES="$(read_option max_files 500)"
MIRROR_MISSING="$(read_option mirror_missing true)"
MINIMUM_FILE_SIZE_KB="$(read_option minimum_file_size_kb 100)"
MINIMUM_LONG_EDGE="$(read_option minimum_long_edge 1280)"
CATALOG_FILENAME="$(read_option catalog_filename albums.json)"
DEBUG="$(read_option debug false)"
ALBUMS="$(read_option albums '')"

if [[ -z "$ALBUMS" ]]; then
  bashio::log.error "No albums are configured. Add at least one public iCloud Shared Album URL."
  exit 1
fi

if ! [[ "$INTERVAL_MINUTES" =~ ^[0-9]+$ ]]; then
  bashio::log.error "interval_minutes must be a non-negative integer."
  exit 1
fi

run_once() {
  local -a args=(
    --albums "$ALBUMS"
    --timeout "$TIMEOUT"
    --keep-days "$KEEP_DAYS"
    --max-files "$MAX_FILES"
    --mirror-missing "$MIRROR_MISSING"
    --minimum-file-size-kb "$MINIMUM_FILE_SIZE_KB"
    --minimum-long-edge "$MINIMUM_LONG_EDGE"
    --catalog-filename "$CATALOG_FILENAME"
    --debug "$DEBUG"
  )

  if ! python3 /app/sync.py "${args[@]}"; then
    bashio::log.warning "One or more albums failed. Existing media and indexes were preserved."
    return 1
  fi
}

term_handler() {
  bashio::log.info "Stopping iCloud Shared Album Sync."
  exit 0
}
trap term_handler SIGTERM SIGINT

if [[ "$INTERVAL_MINUTES" -eq 0 ]]; then
  bashio::log.info "Running a one-time sync."
  run_once
  exit $?
fi

bashio::log.info "Sync interval: every ${INTERVAL_MINUTES} minute(s)."
while true; do
  run_once || true
  sleep "$((INTERVAL_MINUTES * 60))" &
  wait $!
done
