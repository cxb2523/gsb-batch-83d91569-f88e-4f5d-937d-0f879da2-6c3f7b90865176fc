#!/bin/sh
# Single entry point for every task in this repo.
#
#   ./scripts/run.sh collect [args…]   snapshot ccusage output into data/
#   ./scripts/run.sh render  [args…]   regenerate charts/
#
# Why a wrapper: the interpreter you get from an interactive shell and the one a
# scheduler gets are often different builds. On the machine this was written on,
# `python3` was Anaconda 3.11 in the terminal but /usr/bin/python3 3.9 under
# launchd — the classic "works when I test it, misbehaves at 00:30" split.
#
# So: prefer `uv run` in project mode, which provisions the interpreter pinned
# by .python-version (via pyproject.toml + uv.lock) and is identical on every
# machine. Fall back to a plain python3 when uv is absent — the scripts are
# standard-library-only and 3.9-compatible, so the fallback is a real path, not
# a courtesy. Nobody is forced to install uv to use a fork.
set -eu

HERE=$(cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname -- "$HERE")

case "${1:-}" in
    collect|render) TASK="$1"; shift ;;
    ""|-h|--help)
        echo "usage: $0 {collect|render} [args…]" >&2
        exit "$([ -z "${1:-}" ] && echo 1 || echo 0)" ;;
    *)  echo "unknown task: $1 (expected 'collect' or 'render')" >&2; exit 1 ;;
esac

SCRIPT="$REPO/scripts/$TASK.py"

# launchd hands over a minimal PATH, so look in the usual install spots too.
UV=""
for candidate in "${UV_BIN:-}" "$(command -v uv 2>/dev/null || true)" \
                 "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then UV="$candidate"; break; fi
done

if [ -n "$UV" ]; then
    # Project mode: `--project` points uv at pyproject.toml, so it provisions
    # the .python-version interpreter and syncs .venv on its own. (This is why
    # the scripts carry no PEP 723 header — with one, uv would switch to script
    # mode, which ignores .python-version; verified on uv 0.6.5.)
    exec "$UV" run --quiet --project "$REPO" "$SCRIPT" "$@"
fi

PY=""
for candidate in "${PYTHON_BIN:-}" "$(command -v python3 2>/dev/null || true)" /usr/bin/python3; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then PY="$candidate"; break; fi
done
[ -n "$PY" ] || { echo "no uv and no python3 found" >&2; exit 1; }

echo "note: uv not found, falling back to $PY ($("$PY" --version 2>&1))" >&2
exec "$PY" "$SCRIPT" "$@"
