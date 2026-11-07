#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if (( $# < 1 )) || [[ ! "${1:-}" =~ ^(through6|7|8|9|10)$ ]]; then
  echo "Usage: bash scripts/run.sh {through6|7|8|9|10} [census options]" >&2
  exit 2
fi
STAGE="$1"
shift
[[ -x .venv/bin/python ]] || { echo "Run bash scripts/bootstrap.sh first" >&2; exit 2; }
exec .venv/bin/python scripts/census.py --stage "$STAGE" "$@"
