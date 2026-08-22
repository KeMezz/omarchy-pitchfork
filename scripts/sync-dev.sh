#!/usr/bin/env bash

set -euo pipefail

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
target_dir="${1:-}"
plugin_id="$(jq -r '.id' "$source_root/manifest.json")"
expected_root="${OMARCHY_PLUGIN_DEV_ROOT:-${HOME}/.config/omarchy/plugins}"

if [[ -z "$target_dir" ]]; then
  printf 'Usage: %s <plugin-directory>\n' "${0##*/}" >&2
  exit 1
fi

if [[ "$target_dir" != "$expected_root/$plugin_id" ]]; then
  printf 'Refusing unexpected development target: %s\n' "$target_dir" >&2
  printf 'Expected: %s/%s\n' "$expected_root" "$plugin_id" >&2
  exit 1
fi

marker="$target_dir/.omarchy-plugin-dev-source"
if [[ -e "$target_dir" && ! -f "$marker" ]]; then
  printf 'Refusing to overwrite a plugin not managed by this playground: %s\n' "$target_dir" >&2
  exit 1
fi

if [[ -f "$marker" && "$(<"$marker")" != "$source_root" ]]; then
  printf 'Refusing a target managed by another source tree: %s\n' "$target_dir" >&2
  exit 1
fi

mkdir -p -- "$target_dir"
printf '%s' "$source_root" >"$marker"

rsync -a --delete \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude '.vscode/' \
  --exclude '.omarchy-plugin-dev-source' \
  --exclude '.editorconfig' \
  --exclude '.gitignore' \
  --exclude 'AGENTS.md' \
  --exclude 'CLAUDE.md' \
  --exclude 'LICENSE' \
  --exclude 'Makefile' \
  --exclude 'README.md' \
  --exclude 'docs/' \
  --exclude 'scripts/doctor.sh' \
  --exclude 'scripts/sync-dev.sh' \
  --exclude 'scripts/validate-plugin.sh' \
  --exclude 'scripts/watch-dev.sh' \
  "$source_root/" "$target_dir/"

printf 'Synced %s -> %s\n' "$plugin_id" "$target_dir"
