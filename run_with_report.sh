#!/usr/bin/env bash
# Run, validate, and write a readable non-Helly report without changing
# the provenance-hashed scripts/ census runner.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if (( $# != 1 )) || [[ ! "${1:-}" =~ ^(through6|7|8|9|10)$ ]]; then
  echo "Usage: bash run_with_report.sh {through6|7|8|9|10}" >&2
  exit 2
fi
bash scripts/run.sh "$1"
.venv/bin/python scripts/validate.py --stage "$1"
.venv/bin/python reports/non_helly.py --stage "$1"
