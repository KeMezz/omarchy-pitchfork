#!/usr/bin/env bash

set -euo pipefail

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
target_dir="${1:-}"

if [[ -z "$target_dir" ]]; then
  printf 'Usage: %s <plugin-directory>\n' "${0##*/}" >&2
  exit 1
fi

sync_once() {
  if make --no-print-directory -C "$source_root" check; then
    "$source_root/scripts/sync-dev.sh" "$target_dir"
    omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
  else
    printf 'Checks failed; keeping the last valid development copy.\n' >&2
  fi
}

sync_once
printf 'Watching %s (Ctrl+C to stop)\n' "$source_root"

inotifywait --monitor --recursive \
  --event close_write,create,delete,move \
  --exclude '(^|/)(\.git|\.cache)(/|$)' \
  --format '%w%f' \
  "$source_root" |
  while IFS= read -r changed_file; do
    case "$changed_file" in
      *.qml | *.js | */manifest.json | */assets/* | */scripts/*)
        printf 'Changed: %s\n' "${changed_file#"$source_root"/}"
        sync_once
        ;;
    esac
  done
