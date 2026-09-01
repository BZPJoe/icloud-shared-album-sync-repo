#!/usr/bin/env bashio
# shellcheck shell=bash

set -u -o pipefail

read_option() {
  local path="$1"
  local fallback="$2"
  local legacy_key="${3:-}"
  local value
  value="$(python3 -c '
import json
import sys

try:
    with open("/data/options.json", "r", encoding="utf-8") as handle:
        options = json.load(handle)
except (OSError, ValueError):
    options = {}

value = options
for part in sys.argv[1].split("."):
    if not isinstance(value, dict) or part not in value:
        value = None
        break
    value = value[part]

if value is None and sys.argv[2]:
    value = options.get(sys.argv[2])

if isinstance(value, bool):
    print("true" if value else "false")
elif isinstance(value, (list, dict)):
    print(json.dumps(value, separators=(",", ":")))
elif value is not None:
    print(value)
' "$path" "$legacy_key")"
  if [[ -z "$value" || "$value" == "null" ]]; then
    printf '%s' "$fallback"
  else
    printf '%s' "$value"
  fi
}

INTERVAL_MINUTES="$(read_option interval_minutes 180)"
MIRROR_MISSING="$(read_option mirror_missing true)"
ALBUMS="$(read_option albums '')"
TIMEOUT="$(read_option advanced.timeout 40 timeout)"
KEEP_DAYS="$(read_option advanced.keep_days 0 keep_days)"
MAX_FILES="$(read_option advanced.max_files 500 max_files)"
MINIMUM_FILE_SIZE_KB="$(read_option advanced.minimum_file_size_kb 100 minimum_file_size_kb)"
MINIMUM_LONG_EDGE="$(read_option advanced.minimum_long_edge 1280 minimum_long_edge)"
CATALOG_FILENAME="$(read_option advanced.catalog_filename albums.json catalog_filename)"
DEBUG="$(read_option advanced.debug false debug)"

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
