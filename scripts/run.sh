#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ $# -ne 1 || ! "\${1:-}" =~ ^(through6|7|8|9|10)$ ]]; then
  echo "Usage: bash scripts/run.sh {through6|7|8|9|10}" >&2
  exit 2
fi
[[ -x .venv/bin/python ]] || { echo "Run bash scripts/bootstrap.sh first" >&2; exit 2; }
exec .venv/bin/python scripts/census.py --stage "$1"
