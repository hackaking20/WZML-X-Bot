#!/usr/bin/env bash
# Installs everything Amaterasu expects to find on PATH, then clones the bot
# and builds a virtualenv for it.
#
# Set SKIP_APT=1 / SKIP_TOOLS=1 to test the Python half locally without sudo.
set -euo pipefail

AMATERASU_REPO="${AMATERASU_REPO:-https://github.com/Zan-getsu/Amaterasu}"
AMATERASU_REF="${AMATERASU_REF:-main}"
APP_DIR="${APP_DIR:-${GITHUB_WORKSPACE:-$PWD}/app}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-${RUNNER_TEMP:-/tmp}/amaterasu-venv}"

echo "[setup] repo=$AMATERASU_REPO ref=$AMATERASU_REF app=$APP_DIR venv=$VENV_DIR"

# ── 1. System packages ───────────────────────────────────────────────────
# Mirrors the apt list in Amaterasu's Dockerfile.base, trimmed to what the
# bot actually shells out to at runtime (the build-only -dev packages are
# only needed to compile ffmpeg from source, which we do not do).
if [ "${SKIP_APT:-0}" != "1" ]; then
    echo "[setup] installing apt packages"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
        ffmpeg \
        aria2 \
        qbittorrent-nox \
        p7zip-full \
        unrar-free \
        rclone \
        mkvtoolnix \
        mediainfo \
        libmagic1 \
        python3-venv \
        python3-dev \
        fonts-dejavu-core \
        curl \
        unzip \
        jq \
        xz-utils \
        libfuse2
fi

# ── 2. cloudflared ───────────────────────────────────────────────────────
# The bot launches this itself when CLOUDFLARE_TUNNEL_ENABLED=True.
if [ "${SKIP_TOOLS:-0}" != "1" ]; then
    if ! command -v cloudflared >/dev/null 2>&1; then
        echo "[setup] installing cloudflared"
        curl -fsSL -o /tmp/cloudflared \
            https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
        sudo install -m 0755 /tmp/cloudflared /usr/local/bin/cloudflared
    fi
    cloudflared --version

    # ── 3. Deno ──────────────────────────────────────────────────────────
    # yt-dlp needs a JS runtime to solve YouTube's n-sig challenge. Without
    # it every YouTube format comes back unavailable.
    if ! command -v deno >/dev/null 2>&1; then
        echo "[setup] installing deno"
        curl -fsSL https://deno.land/install.sh | DENO_INSTALL="$HOME/.deno" sh -s -- -y >/dev/null
        echo "$HOME/.deno/bin" >> "${GITHUB_PATH:-/dev/null}"
        export PATH="$HOME/.deno/bin:$PATH"
    fi
    deno --version | head -1
fi

# ── 4. Clone the bot ─────────────────────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    echo "[setup] reusing existing checkout"
else
    rm -rf "$APP_DIR"
    git clone --depth 1 --branch "$AMATERASU_REF" "$AMATERASU_REPO" "$APP_DIR"
fi
echo "[setup] $(git -C "$APP_DIR" log -1 --format='%h %ad %s' --date=short)"

# ── 4b. Harness plugins ──────────────────────────────────────────────────
# Files under plugins/ in this repo are copied into the bot's plugin
# directory. Upstream has no plugin autoload, so a two-line hook is patched
# into bot/__main__.py — otherwise every 5-hourly restart would need a
# manual /plugins tap to bring the commands back.
if [ -d "$REPO_ROOT/plugins" ]; then
    mkdir -p "$APP_DIR/plugins"
    cp -f "$REPO_ROOT"/plugins/*.py "$APP_DIR/plugins/" 2>/dev/null || true
    echo "[setup] plugins copied: $(ls "$APP_DIR/plugins" | tr '\n' ' ')"

    python3 - "$APP_DIR" <<'PY_PLUGIN_PATCH'
import pathlib
import sys

app = pathlib.Path(sys.argv[1])
main = app / "bot" / "__main__.py"
marker = "# harness: autoload repo plugins"
block = (
    marker + "\n"
    "for _plugin_name in plugin_manager.discover_plugins():\n"
    "    bot_loop.run_until_complete("
    "plugin_manager.load_plugin(_plugin_name))\n"
)

if not main.exists():
    print("[setup] WARNING: bot/__main__.py missing; skipping plugin autoload")
    sys.exit(0)

text = main.read_text(encoding="utf-8")
if marker in text:
    print("[setup] plugin autoload already present")
elif "register_plugin_commands()" in text:
    text = text.replace(
        "register_plugin_commands()", "register_plugin_commands()\n\n" + block, 1
    )
    main.write_text(text, encoding="utf-8")
    print("[setup] plugin autoload patched into bot/__main__.py")
else:
    print(
        "[setup] WARNING: autoload anchor missing in bot/__main__.py — "
        "load plugins with /plugins after boot"
    )
PY_PLUGIN_PATCH

    python3 -m py_compile "$APP_DIR/bot/__main__.py" \
        && echo "[setup] bot/__main__.py compiles after the plugin patch"
fi

# ── 4c. Web modules ──────────────────────────────────────────────────────
# web/ modules register extra routes on the bot's own FastAPI app. The web
# server runs in its own gunicorn process, so a plugin cannot do this — the
# registration has to live in web/wserver.py itself.
if [ -d "$REPO_ROOT/web" ]; then
    cp -f "$REPO_ROOT"/web/*.py "$APP_DIR/web/" 2>/dev/null || true
    echo "[setup] web modules copied: $(ls "$REPO_ROOT"/web/*.py | xargs -n1 basename | tr '\n' ' ')"

    # the downloader front-end, served by /webdl and also publishable on Pages
    if [ -f "$REPO_ROOT/webdl.html" ]; then
        cp -f "$REPO_ROOT/webdl.html" "$APP_DIR/web/webdl_ui.html"
        echo "[setup] webdl UI installed at web/webdl_ui.html ($(wc -c < "$APP_DIR/web/webdl_ui.html") bytes)"
    fi

    python3 - "$APP_DIR" <<'PY_WEB_PATCH'
import pathlib
import sys

app_dir = pathlib.Path(sys.argv[1])
wserver = app_dir / "web" / "wserver.py"
marker = "# harness: web modules"

modules = []
web_dir = app_dir / "web"
for candidate in sorted(web_dir.glob("*.py")):
    if candidate.name in {"__init__.py", "wserver.py", "security.py"}:
        continue
    # only modules that actually expose register(app); the bot ships several
    # helper modules in web/ that must not be imported here
    try:
        source = candidate.read_text(encoding="utf-8")
    except OSError:
        continue
    if "\ndef register(" in source or source.startswith("def register("):
        modules.append(candidate.stem)

if not wserver.exists():
    print("[setup] WARNING: web/wserver.py missing; skipping web modules")
    sys.exit(0)
if not modules:
    print("[setup] no web modules to register")
    sys.exit(0)

text = wserver.read_text(encoding="utf-8")
if marker in text:
    print("[setup] web modules already registered")
    sys.exit(0)

block = [marker]
for stem in modules:
    block.append(
        "try:\n"
        f"    from web.{stem} import register as _register_{stem}\n"
        f"    _register_{stem}(app)\n"
        f"    print('[harness] web module {stem} registered')\n"
        "except Exception as _web_error:\n"
        f"    print(f'[harness] web module {stem} failed: {{_web_error}}')\n"
    )
text = text.rstrip("\n") + "\n\n\n" + "\n".join(block) + "\n"
wserver.write_text(text, encoding="utf-8")
print(f"[setup] web modules registered in web/wserver.py: {', '.join(modules)}")
PY_WEB_PATCH

    python3 -m py_compile "$APP_DIR/web/wserver.py" \
        && echo "[setup] web/wserver.py compiles after the web module patch"
fi

# ── 4d. Container paths ──────────────────────────────────────────────────
# The bot is written for /usr/src/app (its Docker WORKDIR) and hardcodes it
# in three places. On a runner that directory does not exist and is not
# writable, so clean_all() fails and every download would be written to a
# path that cannot be created. Repoint them at the real checkout.
python3 - "$APP_DIR" <<'PY_PATH_PATCH'
import pathlib
import sys

app = pathlib.Path(sys.argv[1]).resolve()
targets = ["bot/__init__.py", "bot/core/tg_client.py", "bot/modules/restart.py"]
old = "/usr/src/app"
changed = []

for rel in targets:
    path = app / rel
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    if old not in text:
        continue
    path.write_text(text.replace(old, str(app)), encoding="utf-8")
    changed.append(rel)

if changed:
    print(f"[setup] repointed {old} -> {app} in: {', '.join(changed)}")
else:
    print("[setup] no container paths needed repointing")
PY_PATH_PATCH

for _f in bot/__init__.py bot/core/tg_client.py bot/modules/restart.py; do
    if [ -f "$APP_DIR/$_f" ]; then
        python3 -m py_compile "$APP_DIR/$_f"
    fi
done
# ── 4f. Health with lazy connections ─────────────────────────────────────
# /health counts a stream client as ready only when its media pool is
# pre-warmed. With LAZY_CONNECTIONS that never happens until /wake, so the bot
# would report itself degraded (503) while working perfectly.
python3 - "$APP_DIR" <<'PY_HEALTH'
import pathlib
import sys

target = pathlib.Path(sys.argv[1]) / "bot" / "helper" / "health.py"
if not target.exists():
    print("[setup] health.py not found; skipping")
    raise SystemExit(0)

text = target.read_text(encoding="utf-8")
if "LAZY_HEALTH_PATCH" in text:
    print("[setup] health lazy patch already present")
    raise SystemExit(0)

old = "    healthy = crypto_active and bot_connected and stream_pool_ready"
new = (
    "    # LAZY_HEALTH_PATCH: with lazy connections the media pool is opened on\n"
    "    # demand, so its absence is not a fault.\n"
    "    import os as _os\n"
    "    if _os.environ.get(\"LAZY_CONNECTIONS\", \"0\").strip().lower() in {\"1\", \"true\", \"yes\", \"on\"}:\n"
    "        stream_pool_ready = (\n"
    "            configured_stream_clients == 0\n"
    "            or active_stream_clients >= configured_stream_clients\n"
    "        )\n"
    "    healthy = crypto_active and bot_connected and stream_pool_ready"
)
if old not in text:
    print("[setup] WARNING: health.py anchor not found")
else:
    text = text.replace(old, new, 1)
    target.write_text(text, encoding="utf-8")
    print("[setup] patched health.py for lazy connections")
PY_HEALTH
python3 -m py_compile "$APP_DIR/bot/helper/health.py" \
    && echo "[setup] health.py compiles after the lazy patch"

echo "[setup] path patch verified: $(grep -h 'DOWNLOAD_DIR = ' "$APP_DIR/bot/__init__.py" | head -1)"

# ── 4e. Lazy connections ─────────────────────────────────────────────────
# Amaterasu pre-warms a FileToLink media-DC session pool for every stream
# client at boot, and starts a client per STREAM_TOKENS entry. With
# LAZY_CONNECTIONS=1 both are skipped until /wake asks for them.
python3 - "$APP_DIR" <<'PY_LAZY'
import pathlib
import sys

app = pathlib.Path(sys.argv[1])
target = app / "bot" / "core" / "tg_client.py"
if not target.exists():
    print("[setup] tg_client.py not found; skipping lazy patch")
    raise SystemExit(0)

text = target.read_text(encoding="utf-8")
MARK = "LAZY_CONNECTIONS: skipping"

if MARK in text:
    print("[setup] lazy-connection patch already present")
    raise SystemExit(0)

guard = (
    '        import os as _os\n'
    '        if _os.environ.get("LAZY_CONNECTIONS", "0").strip().lower() in {"1", "true", "yes", "on"}:\n'
    '            LOGGER.info("LAZY_CONNECTIONS: skipping FileToLink stream pre-warm")\n'
    '            cls.stream_prewarm = {}\n'
    '            return\n'
)

anchor_doc = '        """Verify every stream bot has a live API connection before serving."""\n'
if anchor_doc in text:
    text = text.replace(anchor_doc, anchor_doc + guard, 1)
    print("[setup] patched prewarm_stream_clients")
else:
    print("[setup] WARNING: prewarm docstring not found")

anchor_start = '        cls.stream_prewarm = {}\n        cls.stream_clients[0] = cls.bot\n'
if anchor_start in text:
    text = text.replace(
        anchor_start,
        '        import os as _os2\n'
        '        if _os2.environ.get("LAZY_CONNECTIONS", "0").strip().lower() in {"1", "true", "yes", "on"}:\n'
        '            LOGGER.info("LAZY_CONNECTIONS: skipping stream client startup")\n'
        '            cls.stream_prewarm = {}\n'
        '            cls.stream_clients[0] = cls.bot\n'
        '            cls.stream_loads[0] = 0\n'
        '            return\n'
        + anchor_start,
        1,
    )
    print("[setup] patched start_stream_clients")
else:
    print("[setup] WARNING: start_stream_clients anchor not found")

target.write_text(text, encoding="utf-8")
PY_LAZY
python3 -m py_compile "$APP_DIR/bot/core/tg_client.py" \
    && echo "[setup] tg_client.py compiles after the lazy patch"

# ── 5. Python environment ────────────────────────────────────────────────
echo "[setup] building virtualenv"
# Some images export PIP_USER=1, which makes every venv install abort with
# "Can not perform a '--user' install". Neutralise it.
export PIP_USER=0
export PIP_DISABLE_PIP_VERSION_CHECK=1
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip wheel setuptools
"$VENV_DIR/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# Amaterasu's vendored sabnzbdapi imports `niquests.packages.urllib3`, which
# only exists in newer niquests. pip's resolver happily settles on 3.3.4 and
# the bot then dies on import. Pin the floor explicitly.
"$VENV_DIR/bin/pip" install -q "niquests>=3.21"

# The bot shells out to `gunicorn` by name for its web server, so the venv
# has to be ahead of the system PATH.
echo "$VENV_DIR/bin" >> "${GITHUB_PATH:-/dev/null}"

# ── 6. Smoke test ────────────────────────────────────────────────────────
# Proves the import chain works without needing a bot token.
cd "$APP_DIR"
"$VENV_DIR/bin/python" - <<'PY'
import pyrogram
from niquests.packages.urllib3 import disable_warnings  # noqa: F401
import bot  # noqa: F401  full package import chain
from bot.core.config_manager import Config

assert pyrogram.__version__ == "3.1.5", f"expected WZGram 3.1.5, got {pyrogram.__version__}"
try:
    Config.load()
except ValueError as error:
    # Expected: no BOT_TOKEN in this step. Anything else means a real problem.
    assert "BOT_TOKEN" in str(error), error
else:
    raise SystemExit("Config.load() should have failed without BOT_TOKEN")
print(f"[setup] smoke test OK — WZGram {pyrogram.__version__}, imports clean")
PY
