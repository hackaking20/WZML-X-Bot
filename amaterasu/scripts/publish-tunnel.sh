#!/usr/bin/env bash
# Publish the current tunnel URL so the GitHub Pages homepage can link to it.
#
# Writes tunnel.json in the harness checkout (and docs/tunnel.json for the
# Pages site) and commits them. Never fatal: if the push fails the bot keeps
# running, only the links are stale.
set -uo pipefail

URL="${1:-}"
if [ -z "$URL" ]; then
    echo "[publish] no URL given"
    exit 0
fi

ROOT="${HARNESS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REPO_ROOT="$(cd "$ROOT/.." 2>/dev/null && pwd || echo "$ROOT")"
DOCS="$REPO_ROOT/docs"

if [ ! -d "$ROOT/.git" ]; then
    echo "[publish] no git checkout at $ROOT — skipping"
    exit 0
fi

write_one() {
    python3 - "$1" "$URL" <<'PY'
import datetime
import json
import sys

path, url = sys.argv[1], sys.argv[2]
stamp = (
    datetime.datetime.now(datetime.timezone.utc)
    .isoformat(timespec="seconds")
    .replace("+00:00", "Z")
)
with open(path, "w", encoding="utf-8") as handle:
    json.dump({"url": url, "updated": stamp}, handle, indent=2)
    handle.write("\n")
print(f"[publish] {path} -> {url} at {stamp}")
PY
}

write_one "$ROOT/tunnel.json"
if [ -d "$DOCS" ]; then
    write_one "$DOCS/tunnel.json"
fi

cd "$ROOT" || exit 0
git add tunnel.json >/dev/null 2>&1 || true
if [ -d "$DOCS" ]; then
    git add docs/tunnel.json >/dev/null 2>&1 || true
fi

if git diff --cached --quiet; then
    echo "[publish] tunnel.json unchanged"
    exit 0
fi

if git -c user.name="amaterasu-runner" \
       -c user.email="runner@users.noreply.github.com" \
       commit -q -m "tunnel: $(date -u +%Y-%m-%dT%H:%MZ)" >/dev/null 2>&1; then
    # another workflow may be pushing to main at the same moment
    pushed=0
    for attempt in 1 2 3 4 5; do
        git pull --rebase --autostash origin HEAD >/dev/null 2>&1 || true
        if git push -q origin HEAD >/dev/null 2>&1; then
            pushed=1
            echo "[publish] pushed tunnel.json on attempt $attempt"
            break
        fi
        sleep $(( attempt * 3 ))
    done
    if [ "$pushed" = "0" ]; then
        echo "[publish] push rejected 5 times — links stay stale until the next run"
    fi
else
    echo "[publish] commit failed"
fi
