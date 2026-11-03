#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/.deps/pycliques-project"
PIN="$(tr -d '[:space:]' < "$ROOT/config/pycliques_commit.txt")"
[[ "$PIN" =~ ^[[:xdigit:]]{40}$ ]] || { echo "Invalid 40-character Git pin" >&2; exit 2; }
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null || [[ "$(uv --version)" != 'uv 0.9.26' ]]; then
  python3 -m pip install --user --upgrade 'uv==0.9.26'
fi
if [[ ! -d "$SOURCE/.git" ]]; then
  mkdir -p "$(dirname "$SOURCE")"
  git clone --filter=blob:none https://github.com/rvf0068/pycliques-project.git "$SOURCE"
fi
[[ -z "$(git -C "$SOURCE" status --porcelain)" ]] || { echo "Dirty upstream checkout" >&2; exit 2; }
if [[ "$(git -C "$SOURCE" rev-parse HEAD)" != "$PIN" ]]; then
  git -C "$SOURCE" fetch --no-tags origin "$PIN"
  git -C "$SOURCE" checkout --detach "$PIN"
fi
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$PIN" ]] || { echo "Upstream pin mismatch" >&2; exit 2; }
(cd "$SOURCE" && uv sync --frozen --no-dev --python 3.11)
if [[ ! -e "$ROOT/.venv" ]]; then
  ln -s .deps/pycliques-project/.venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" - <<'PY'
import pycliques, pycombtop, pyg6data
print("Pinned pycliques:", pycliques.__file__)
print("Pinned pycombtop:", pycombtop.__file__)
print("Pinned pyg6data:", pyg6data.__file__)
PY
