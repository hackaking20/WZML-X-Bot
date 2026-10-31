#!/usr/bin/env bash
# Build vault.json in CI from repository secrets.
#
#   LINK_HOUSE_PASS   the passphrase (same one you type into the hub)
#   VAULT_PAYLOAD     the page list as JSON, secrets and all
#
# Both stay in GitHub Secrets. Only the ciphertext is committed. If neither
# is configured the script exits 0 with a warning, so the workflow is never
# red just because you have not set them up yet.
set -uo pipefail

ROOT="${HARNESS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT" || exit 1

PAYLOAD_FILE="$ROOT/vault.payload.json"
TMP_PAYLOAD="$(mktemp)"
trap 'rm -f "$TMP_PAYLOAD"' EXIT

if [ -n "${VAULT_PAYLOAD:-}" ]; then
    printf '%s' "$VAULT_PAYLOAD" > "$TMP_PAYLOAD"
    echo "[vault] payload: from the VAULT_PAYLOAD secret"
elif [ -f "$PAYLOAD_FILE" ]; then
    cp "$PAYLOAD_FILE" "$TMP_PAYLOAD"
    echo "[vault] payload: from vault.payload.json in the repo"
else
    echo "[vault] no payload configured — set the VAULT_PAYLOAD secret (recommended)"
    echo "[vault] or commit a vault.payload.json with the page list"
    echo "[vault] leaving vault.json untouched"
    exit 0
fi

if [ -z "${LINK_HOUSE_PASS:-}" ]; then
    echo "[vault] LINK_HOUSE_PASS is not set — cannot encrypt"
    exit 1
fi

if [ "${#LINK_HOUSE_PASS}" -lt 12 ]; then
    echo "[vault] LINK_HOUSE_PASS is shorter than 12 characters; refusing"
    exit 1
fi

python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$TMP_PAYLOAD" 2>/dev/null \
    || { echo "[vault] payload is not valid JSON"; exit 1; }

VAULT_PASSPHRASE="$LINK_HOUSE_PASS" python3 "$ROOT/scripts/make-vault.py" \
    "$TMP_PAYLOAD" --hint "${VAULT_HINT:-}" --out "$ROOT/vault.json.new" \
    || { echo "[vault] encryption failed"; exit 1; }

# Only rewrite when the ciphertext actually changed (a fresh salt makes every
# run differ, so compare the decrypted payload instead of the file).
python3 - "$ROOT" <<'PY'
import base64
import json
import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
new = root / "vault.json.new"
old = root / "vault.json"

if not old.exists():
    new.replace(old)
    print("[vault] vault.json created")
    sys.exit(0)

old_digest = json.loads(old.read_text(encoding="utf-8")).get("digest", "")
new_digest = json.loads(new.read_text(encoding="utf-8")).get("digest", "")
if old_digest and old_digest == new_digest:
    new.unlink(missing_ok=True)
    print("[vault] unchanged")
    sys.exit(0)

new.replace(old)
print("[vault] vault.json updated")
PY

if [ -f "$ROOT/.git" ] || [ -d "$ROOT/.git" ]; then
    git add vault.json >/dev/null 2>&1 || true
    if git diff --cached --quiet; then
        echo "[vault] nothing to commit"
    else
        git -c user.name="vault-builder" \
            -c user.email="runner@users.noreply.github.com" \
            commit -q -m "vault: rebuild from secrets" \
            && git push -q origin HEAD \
            && echo "[vault] committed and pushed" \
            || echo "[vault] push failed (non-fatal)"
    fi
fi
