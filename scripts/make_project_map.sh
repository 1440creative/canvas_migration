#!/usr/bin/env bash
set -euo pipefail

# Find repo root (falls back to current dir if not in a git repo)
if ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  cd "$ROOT"
fi

OUT_FILE="${1:-structure.txt}"

EXCLUDES='.git|.pytest_cache|__pycache__|*.egg-info|node_modules|.DS_Store|export/data|export/test_data'

# Ensure tree exists
command -v tree >/dev/null 2>&1 || { echo "Error: 'tree' not found. Try: brew install tree"; exit 1; }

# Generate the map
tree -a --prune --dirsfirst \
  -I "$EXCLUDES" \
  -L "${DEPTH:-5}" \
  > "$OUT_FILE"

echo "Wrote project map to $OUT_FILE"
