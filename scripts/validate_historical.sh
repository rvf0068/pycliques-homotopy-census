#!/usr/bin/env bash
# Validate previous stages without switching the current dependency version.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"
if (( $# != 1 )) || [[ ! "${1:-}" =~ ^(through6|7|8|9|10)$ ]]; then
  echo 'Usage: bash scripts/validate_historical.sh {through6|7|8|9|10}' >&2
  exit 2
fi
exec python3 scripts/historical_validate.py --stage "$1"
