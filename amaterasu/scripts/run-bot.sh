#!/usr/bin/env bash
# Supervises the bot for a fixed time budget, then shuts it down cleanly.
#
# Amaterasu installs its own SIGTERM handler, so `timeout` gives us a graceful
# drain: Mongo config is flushed, Telegram clients disconnect, the tunnel child
# is stopped. The loop restarts the bot if it dies early (its own daily 06:00
# restart, a crash, an OOM kill) as long as budget remains.
set -uo pipefail

APP_DIR="${APP_DIR:-${GITHUB_WORKSPACE:-$PWD}/app}"
HARNESS_DIR="${HARNESS_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BOT_MINUTES="${BOT_MINUTES:-290}"
BOT_LOG="$APP_DIR/log.txt"
HARNESS_LOG="${RUNNER_TEMP:-/tmp}/harness.log"

if ! [[ "$BOT_MINUTES" =~ ^[0-9]+$ ]] || [ "$BOT_MINUTES" -gt 330 ]; then
    echo "[harness] BOT_MINUTES must be an integer <= 330, got '$BOT_MINUTES'" >&2
    BOT_MINUTES=290
fi

log() { echo "[harness $(date -u +%H:%M:%S)] $*" | tee -a "$HARNESS_LOG"; }

# ── Preflight ────────────────────────────────────────────────────────────
# The toolchain step costs ~18 minutes; a malformed credential should not
# cost that. Everything checked here is something the bot only discovers
# after it has connected to Telegram.
preflight() {
    local failed=0
    local api="${TELEGRAM_API:-}"

    if [ -z "${BOT_TOKEN:-}" ]; then
        log "FATAL: BOT_TOKEN is empty"
        failed=1
    elif ! printf '%s' "$BOT_TOKEN" | grep -Eq '^[0-9]+:[A-Za-z0-9_-]{20,}$'; then
        log "FATAL: BOT_TOKEN is not in the form <digits>:<string> — copy it from @BotFather again"
        failed=1
    fi

    case "$api" in
        "")
            log "FATAL: TELEGRAM_API is empty"
            failed=1
            ;;
        *[!0-9]*)
            log "FATAL: TELEGRAM_API must be digits only, got '$api'"
            failed=1
            ;;
        *)
            # pyrogram packs api_id into a signed 32-bit int
            if [ "${#api}" -gt 10 ] || [ "$api" -gt 2147483647 ]; then
                log "FATAL: TELEGRAM_API=$api exceeds 2147483647, which pyrogram cannot send."
                log "       That is not an api_id — check my.telegram.org → API development tools."
                failed=1
            fi
            ;;
    esac

    case "${OWNER_ID:-}" in
        ""|*[!0-9]*)
            log "FATAL: OWNER_ID must be your numeric Telegram id, got '${OWNER_ID:-<unset>}'"
            failed=1
            ;;
    esac

    if ! printf '%s' "${TELEGRAM_HASH:-}" | grep -Eq '^[0-9a-fA-F]{32}$'; then
        log "FATAL: TELEGRAM_HASH must be 32 hex characters, got a ${#TELEGRAM_HASH} character value"
        failed=1
    fi

    case "${DATABASE_URL:-}" in
        mongodb*) ;;
        "") log "FATAL: DATABASE_URL is empty"; failed=1 ;;
        *) log "FATAL: DATABASE_URL does not start with mongodb"; failed=1 ;;
    esac

    if [ "$failed" -ne 0 ]; then
        log "preflight failed — not starting the bot. Fix the value(s) above and re-run."
        notify "Amaterasu preflight failed" "a credential is malformed; see the run log"
        return 1
    fi
    log "preflight OK (api_id $api, owner ${OWNER_ID}, hash ${TELEGRAM_HASH:0:6}…)"
    return 0
}

# ── Optional notifications ───────────────────────────────────────────────
notify() {
    [ -z "${NTFY_TOPIC:-}" ] && return 0
    curl -fsS -m 15 -H "Title: $1" -d "$2" "https://ntfy.sh/${NTFY_TOPIC}" >/dev/null 2>&1 || true
}

# ── Tunnel URL registration ──────────────────────────────────────────────
# The bot starts cloudflared itself and logs the URL it was given. A quick
# tunnel's hostname changes on every boot, so anything pointing at the bot
# (bookmarks, FileToLink links) needs a stable front door: the Worker keeps
# the current URL in KV and proxies to it. Without a Worker, read the URL
# from the log or from the bot's DM to the owner.
watch_tunnel() {
    local last=""
    while :; do
        local url
        # Ask the bot first: it knows its own public URL. Scraping the log is
        # only a fallback, because the exact wording of that line is not
        # guaranteed and silently stops matching when upstream changes it.
        url=$(curl -sS -m 5 "http://127.0.0.1:${PORT:-8080}/api/tunnel" 2>/dev/null \
            | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("url",""))
except Exception:
    print("")' 2>/dev/null || true)
        url="${url%/}"

        if [ -z "$url" ]; then
            url=$(tail -c 400000 "$BOT_LOG" 2>/dev/null \
                | grep -aoE 'https://[a-z0-9-]+\.trycloudflare\.com' \
                | tail -1)
        fi
        if [ -n "$url" ] && [ "$url" != "$last" ]; then
            last="$url"
            log "tunnel URL is $url"
            if [ "${PAGES_PUBLISH:-1}" = "1" ]; then
                bash "$HARNESS_DIR/scripts/publish-tunnel.sh" "$url" || true
            fi
            if [ -n "${WORKER_URL:-}" ] && [ -n "${WORKER_SECRET:-}" ]; then
                if curl -fsS -m 25 -X POST "${WORKER_URL%/}/update-tunnel" \
                        -H "X-Tunnel-Secret: ${WORKER_SECRET}" \
                        --data-urlencode "url=${url}" >/dev/null; then
                    log "registered tunnel with worker ${WORKER_URL%/}"
                else
                    log "WARNING: worker registration failed; will retry on next change"
                fi
            fi
            notify "Amaterasu tunnel ready" "$url"
        fi
        sleep 20
    done
}

# ── One-shot diagnostics ─────────────────────────────────────────────────
# Two minutes after the bot starts, dump what the supervisor can see — the
# tunnel endpoint, the port, and the tail of the bot log — into the repo so it
# can be read without job-log access.
dump_diagnostics() {
    (
        sleep 120
        repo_root="$(cd "$HARNESS_DIR/.." && pwd)"
        out="$repo_root/diagnostics/runner.log"
        mkdir -p "$repo_root/diagnostics"
        {
            echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
            echo "--- api/tunnel (port ${PORT:-8080}) ---"
            curl -sS -m 5 "http://127.0.0.1:${PORT:-8080}/api/tunnel" 2>&1 || echo "curl failed"
            echo
            echo "--- listening ports ---"
            (ss -ltnp 2>/dev/null || netstat -ltn 2>/dev/null) | head -20
            echo "--- log tail ---"
            tail -150 "$BOT_LOG" 2>/dev/null || echo "no log at $BOT_LOG"
        } > "$out" 2>&1
        cd "$repo_root" || exit 0
        git add diagnostics/runner.log >/dev/null 2>&1 || exit 0
        git diff --cached --quiet && exit 0
        git -c user.name="amaterasu-runner" -c user.email="runner@users.noreply.github.com" \
            commit -q -m "diagnostics: runner log $(date -u +%H:%MZ)" >/dev/null 2>&1 || exit 0
        git push -q origin HEAD >/dev/null 2>&1 || true
    ) &
}

# ── Main supervision loop ────────────────────────────────────────────────
mkdir -p "$APP_DIR" 2>/dev/null || true
cd "$APP_DIR" || { log "missing app dir $APP_DIR"; exit 1; }

# An unset GitHub secret still arrives as an empty string, and Amaterasu's
# env layer is applied AFTER MongoDB — so an empty value would blank a
# setting you keep in the database. Drop the empties and let Mongo win.
_blanked=""
for _key in BOT_TOKEN TELEGRAM_API TELEGRAM_HASH OWNER_ID DATABASE_URL \
            USER_SESSION_STRING WEB_ACCESS_PASSWORD HELPER_TOKENS HELPER_STRINGS \
            LOG_CHAT_ID SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET WORKER_URL \
            WORKER_SECRET NTFY_TOPIC; do
    if [ -z "${!_key:-}" ]; then
        unset "$_key" 2>/dev/null || true
        _blanked="$_blanked $_key"
    fi
done
if [ -n "$_blanked" ]; then
    log "cleared empty config env var(s) so MongoDB values survive:$_blanked"
fi

: > "$HARNESS_LOG"
END_AT=$(( $(date +%s) + BOT_MINUTES * 60 ))
log "starting; budget ${BOT_MINUTES}min; disk $(df -h . | awk 'NR==2{print $4}') free"

WATCHER_PID=""
if [ -n "${WORKER_URL:-}" ] || [ -n "${NTFY_TOPIC:-}" ] || [ "${PAGES_PUBLISH:-1}" = "1" ]; then
    watch_tunnel &
    WATCHER_PID=$!
fi

cleanup() {
    [ -n "$WATCHER_PID" ] && kill "$WATCHER_PID" 2>/dev/null || true
    # Do not leave the tunnel or download engines holding the port.
    pkill -f cloudflared 2>/dev/null || true
    pkill -f 'gunicorn .*web.wserver' 2>/dev/null || true
}
trap cleanup EXIT

preflight || exit 1

# Called from the workflow before the ~17 minute toolchain install, so a
# malformed credential costs seconds instead of a full setup.
if [ "${PREFLIGHT_ONLY:-0}" = "1" ]; then
    log "preflight-only run: credentials look sane"
    exit 0
fi

attempt=0
fast_fails=0
while :; do
    remaining=$(( END_AT - $(date +%s) ))
    [ "$remaining" -lt 45 ] && break

    attempt=$(( attempt + 1 ))
    attempt_started=$(date +%s)
    log "attempt $attempt: starting bot with ${remaining}s of budget left"
    notify "Amaterasu starting" "attempt $attempt, ${remaining}s budget"

    [ "$attempt" -eq 1 ] && dump_diagnostics

    # SIGTERM at the deadline, SIGKILL 90s later if it hangs on the way out.
    timeout --signal=TERM --kill-after=90 "$remaining" python -m bot
    rc=$?

    if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
        log "attempt $attempt: budget exhausted (rc=$rc), shutting down"
        break
    fi

    log "attempt $attempt: bot exited with rc=$rc"

    # A bot that dies within two minutes of starting will keep doing it. Six of
    # those in a row means something is broken, and burning the rest of the
    # budget restarting it helps nobody.
    ran_for=$(( $(date +%s) - attempt_started ))
    if [ "$ran_for" -lt 120 ]; then
        fast_fails=$(( fast_fails + 1 ))
        log "attempt $attempt: died after ${ran_for}s (fast fail $fast_fails/6)"
        if [ "$fast_fails" -ge 6 ]; then
            log "FATAL: six fast failures in a row — exiting instead of looping"
            notify "Amaterasu stopped" "6 fast failures in a row; see the log"
            exit 1
        fi
    else
        fast_fails=0
    fi

    notify "Amaterasu restarted" "attempt $attempt exited rc=$rc"

    remaining=$(( END_AT - $(date +%s) ))
    [ "$remaining" -lt 90 ] && break
    sleep 20
done

log "run finished after $attempt attempt(s)"
notify "Amaterasu stopped" "budget exhausted after $attempt attempt(s)"

# ── Log hygiene ──────────────────────────────────────────────────────────
# Amaterasu re-logs "tunnel_monitor: keeping stable ..." every five seconds,
# which is ~17k identical lines a day. Collapse consecutive duplicates so the
# log stays readable and the artifact stays small.
if [ -f "$BOT_LOG" ]; then
    before=$(wc -l < "$BOT_LOG")
    awk '
        { line = $0 }
        line == prev { n++; next }
        { if (n > 0) printf "[%d identical line(s) collapsed]\n", n; print; prev = line; n = 0 }
        END { if (n > 0) printf "[%d identical line(s) collapsed]\n", n }
    ' "$BOT_LOG" > "${BOT_LOG}.dedup" && mv "${BOT_LOG}.dedup" "$BOT_LOG"
    after=$(wc -l < "$BOT_LOG")
    log "log trimmed: $before lines -> $after"
fi
