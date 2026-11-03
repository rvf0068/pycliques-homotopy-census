#!/usr/bin/env bash
# Change pycliques-project only between fully completed, validated census runs.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SOURCE="$ROOT/.deps/pycliques-project"
PIN="$ROOT/config/pycliques_commit.txt"
export PATH="$HOME/.local/bin:$PATH"

[[ -x .venv/bin/python && -d "$SOURCE/.git" ]] || {
  echo "Bootstrap the pinned environment first: bash scripts/bootstrap.sh" >&2
  exit 2
}
OLD="$(tr -d '[:space:]' < "$PIN")"
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$OLD" ]] || {
  echo "Installed pycliques-project differs from the recorded pin" >&2
  exit 2
}
[[ -z "$(git -C "$SOURCE" status --porcelain)" ]] || {
  echo "Uncommitted changes in the pycliques-project checkout" >&2
  exit 2
}
if ! git diff --quiet -- "$PIN" || ! git diff --cached --quiet -- "$PIN"; then
  echo "Commit/discard previous changes to the dependency pin first" >&2
  exit 2
fi

# No data, manifest, or partial computation can be silently reinterpreted.
.venv/bin/python scripts/versioning.py

git -C "$SOURCE" fetch --no-tags origin main
NEW="$(git -C "$SOURCE" rev-parse FETCH_HEAD)"
[[ "$NEW" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Malformed upstream SHA" >&2
  exit 2
}
if [[ "$NEW" == "$OLD" ]]; then
  echo "Already using pycliques-project origin/main at $NEW"
  exit 0
fi

TMP="$PIN.tmp"
printf '%s\n' "$NEW" > "$TMP"
mv "$TMP" "$PIN"
if ! bash scripts/bootstrap.sh; then
  echo "Install failed; restoring previous pin and environment" >&2
  printf '%s\n' "$OLD" > "$TMP"
  mv "$TMP" "$PIN"
  bash scripts/bootstrap.sh || true
  exit 1
fi
printf 'Updated pycliques-project\nold: %s\nnew: %s\n' "$OLD" "$NEW"
echo "Commit the updated pin before starting the next stage:"
echo '  git add config/pycliques_commit.txt && git commit -m "Update pycliques-project pin" && git push'
echo "For old completed stages: bash scripts/validate_historical.sh STAGE"
