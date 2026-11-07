#!/usr/bin/env bash
# Run, report, and validate completed stages without modifying old census data.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if (( $# < 1 )) || [[ ! "${1:-}" =~ ^(through6|7|8|9|10)$ ]]; then
  echo "Usage: bash run_with_report.sh {through6|7|8|9|10} [census options]" >&2
  exit 2
fi
STAGE="$1"
shift
bash scripts/run.sh "$STAGE" "$@"

if [[ "$STAGE" == "10" ]]; then
  # The split report can be generated from completed batches while the
  # current batch is still an fsynced, resumable journal.
  .venv/bin/python reports/order10_split.py
  .venv/bin/python reports/order10_progress.py
  # Only ask the full validator to inspect the 11.7M rows when the final
  # batch has a completion marker.
  if [[ -f runs/order10/order10/completed/11700000-11716570.done.json ]]; then
    .venv/bin/python scripts/validate.py --stage 10
  else
    echo "Order 10 paused; run validation only after all 118 batches finish."
  fi
else
  .venv/bin/python scripts/validate.py --stage "$STAGE"
  .venv/bin/python reports/non_helly.py --stage "$STAGE"
fi
