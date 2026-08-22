#!/usr/bin/env bash

set -euo pipefail

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
stage_root="$(mktemp -d)"

cleanup() {
  rm -rf -- "$stage_root"
}
trap cleanup EXIT

rsync -a \
  --exclude '.git/' \
  --exclude 'CLAUDE.md' \
  "$source_root/" "$stage_root/plugin/"

omarchy plugin validate "$stage_root/plugin"
