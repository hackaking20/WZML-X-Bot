#!/usr/bin/env bash
# Publish the current tunnel URL so GitHub Pages can redirect to it.
#
# Writes tunnel.json in the harness checkout and commits it. The Pages site
# reads that file from the API (uncached), so the redirect follows the bot
# without needing a Cloudflare Worker or any token beyond the checkout's own.
#
# Never fatal: if the push fails the bot keeps running, only the redirect is
# stale.
set -uo pipefail

URL="${1:-}"
if [ -z "$URL" ]; then
    echo "[publish] no URL given"
    exit 0
fi

ROOT="${HARNESS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
if [ ! -d "$ROOT/.git" ]; then
    echo "[publish] no git checkout at $ROOT — skipping"
    exit 0
fi

python3 - "$ROOT/tunnel.json" "$URL" <<'PY'
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
print(f"[publish] tunnel.json -> {url} at {stamp}")
PY

cd "$ROOT" || exit 0
git add tunnel.json >/dev/null 2>&1 || { echo "[publish] git add failed"; exit 0; }
if git diff --cached --quiet; then
    echo "[publish] tunnel.json unchanged"
    exit 0
fi

if git -c user.name="amaterasu-runner" \
       -c user.email="runner@users.noreply.github.com" \
       commit -q -m "tunnel: $(date -u +%Y-%m-%dT%H:%MZ)" >/dev/null 2>&1; then
    if git push -q origin HEAD >/dev/null 2>&1; then
        echo "[publish] pushed tunnel.json to the repo"
    else
        echo "[publish] push rejected — the redirect will be stale until the next run"
    fi
else
    echo "[publish] commit failed"
fi
