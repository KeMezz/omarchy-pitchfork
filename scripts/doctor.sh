#!/usr/bin/env bash

set -euo pipefail

required_commands=(omarchy omarchy-shell qs qmllint qmlformat jq make mkdir rsync inotifywait python3 pw-cat node)
missing=()

for command_name in "${required_commands[@]}"; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    missing+=("$command_name")
  fi
done

if ((${#missing[@]} > 0)); then
  printf 'Missing commands: %s\n' "${missing[*]}" >&2
  exit 1
fi

if ! python3 -c 'import math, sys; raise SystemExit(not (sys.version_info >= (3, 12) and hasattr(math, "sumprod")))'; then
  printf '%s\n' 'Pitchfork requires Python 3.12 or newer with math.sumprod.' >&2
  exit 1
fi

omarchy_root="${OMARCHY_PATH:-/usr/share/omarchy}"
if [[ ! -d "$omarchy_root/shell" ]]; then
  printf 'Omarchy shell imports not found: %s\n' "$omarchy_root/shell" >&2
  exit 1
fi

printf 'Omarchy:   %s\n' "$(omarchy version)"
printf 'Quickshell: %s\n' "$(qs --version | head -n 1)"
printf 'QML tools: %s, %s\n' "$(qmllint --version)" "$(qmlformat --version)"
printf 'Python:    %s\n' "$(python3 --version)"
printf 'Imports:   %s\n' "$omarchy_root/shell"

if omarchy-shell shell ping >/dev/null 2>&1; then
  printf 'Shell:     running\n'
else
  printf 'Shell:     not running (static checks still work)\n'
fi
