#!/usr/bin/env bash
# Recalculate only the six historical order-9 timeouts in a separate venv.
# The original census dependency pin, venv, chunks, and manifests are untouched.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

SOURCE="$ROOT/.deps/pycliques-project"
PIN="$ROOT/config/pycliques_commit.txt"
[[ -d "$SOURCE/.git" && -x "$ROOT/.venv/bin/python" ]] || {
  echo "Bootstrap the original pinned census first: bash scripts/bootstrap.sh" >&2
  exit 2
}
OLD="$(tr -d '[:space:]' < "$PIN")"
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$OLD" ]] || {
  echo "Original census checkout is not at the recorded pin; refusing to continue" >&2
  exit 2
}
[[ -z "$(git -C "$SOURCE" status --porcelain)" ]] || {
  echo "Original census checkout has uncommitted changes" >&2
  exit 2
}
[[ -z "$(git status --porcelain -- "$PIN")" ]] || {
  echo "Commit or restore changes to the original census pin before proceeding" >&2
  exit 2
}

git -C "$SOURCE" fetch --no-tags origin main
NEW="$(git -C "$SOURCE" rev-parse FETCH_HEAD)"
[[ "$NEW" =~ ^[0-9a-f]{40}$ && "$NEW" != "$OLD" ]] || {
  echo "Could not find a newer upstream revision" >&2
  exit 2
}
git -C "$SOURCE" cat-file -e "$NEW:packages/pycombtop/src/pycombtop/morse_certificates.py" || {
  echo "The selected upstream revision has no facet Morse implementation" >&2
  exit 2
}
MORSE="$ROOT/.deps/pycliques-project-order9-morse-${NEW:0:12}"
if [[ ! -e "$MORSE/.git" ]]; then
  [[ ! -e "$MORSE" ]] || {
    echo "Cannot use occupied Morse worktree path: $MORSE" >&2
    exit 2
  }
  git -C "$SOURCE" worktree add --detach "$MORSE" "$NEW"
fi
[[ "$(git -C "$MORSE" rev-parse HEAD)" == "$NEW" ]] || {
  echo "Existing Morse worktree points to the wrong revision" >&2
  exit 2
}
[[ -z "$(git -C "$MORSE" status --porcelain)" ]] || {
  echo "Morse checkout has uncommitted changes" >&2
  exit 2
}

(cd "$MORSE" && uv sync --frozen --no-dev --python 3.11)
echo "Historical census pin retained: $OLD"
echo "Isolated facet Morse revision: $NEW"
PYCLIQUES_MORSE_CHECKOUT="$MORSE" \
  "$MORSE/.venv/bin/python" "$ROOT/audits/resolve_order9_timeouts.py"

echo
echo "Review results in order9_morse_followup.md, then commit separately:"
echo "  git add runs/order9_morse_followup/ order9_morse_followup.md"
echo '  git commit -m "Resolve six order-9 timeouts using facet Morse certificates"'
echo "  git push"
