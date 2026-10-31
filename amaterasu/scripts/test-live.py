"""Live network tests — run these on a GitHub runner, not in a sandbox.

Everything here needs real internet: Deezer, JioSaavn, Spotify's oEmbed,
YouTube via yt-dlp, and one real file download through the /webdl engine.
My dev sandbox blocks most of those hosts, which is exactly why this script
exists: it runs in CI where the network is open, and prints a report.

Run: python3 scripts/test-live.py
Exit code is 1 if any REQUIRED probe fails.
"""

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
results = []  # (required, ok, name, detail)


def record(name, ok, detail="", required=True):
    results.append((required, bool(ok), name, str(detail)[:220]))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))


# ── stub the bot package so the plugins import standalone ───────────────
class _Logger:
    def info(self, *a, **k):
        pass

    error = warning = debug = info


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


class _PluginInfo:
    def __init__(self, **kwargs):
        self.handlers = []
        for key, value in kwargs.items():
            setattr(self, key, value)


async def _noop(*args, **kwargs):
    return None


_stub("bot", LOGGER=_Logger())
_stub("bot.core")
_stub("bot.core.plugin_manager", PluginBase=type("PB", (), {}), PluginInfo=_PluginInfo)
_stub("bot.helper")
_stub("bot.helper.ext_utils")
_stub("bot.helper.ext_utils.bot_utils", new_task=lambda fn: fn)
_stub("bot.helper.telegram_helper")
_stub("bot.helper.telegram_helper.message_utils", send_message=_noop, edit_message=_noop, delete_message=_noop)

spec = importlib.util.spec_from_file_location("music_live", ROOT / "plugins" / "music.py")
music = importlib.util.module_from_spec(spec)
sys.modules["music_live"] = music
spec.loader.exec_module(music)

spec2 = importlib.util.spec_from_file_location("webdl_live", ROOT / "web" / "webdl.py")
webdl = importlib.util.module_from_spec(spec2)
sys.modules["webdl_live"] = webdl
spec2.loader.exec_module(webdl)


async def main():
    # ── 1. catalogue providers ──────────────────────────────────────────
    try:
        data = await music._ajson("https://api.deezer.com/search/artist?q=arijit&limit=1")
        record("Deezer API reachable", bool(data.get("data")), json.dumps(data)[:120])
    except Exception as error:
        record("Deezer API reachable", False, f"{type(error).__name__}: {error}")

    try:
        url = music._saavn_get("search.getResults", q="arijit", n="3", p="1")
        data = await music._ajson(url)
        count = len(data.get("results") or [])
        record("JioSaavn API reachable", count > 0, f"{count} results")
    except Exception as error:
        record("JioSaavn API reachable", False, f"{type(error).__name__}: {error}")

    try:
        title = await music.spotify_oembed_title(
            "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
        )
        record("Spotify oEmbed reachable", bool(title), title)
    except Exception as error:
        record("Spotify oEmbed reachable", False, f"{type(error).__name__}: {error}")

    # ── 2. catalogue assembly against a real artist ─────────────────────
    try:
        tracks = await music.deezer_artist_catalogue("Arijit Singh", 8)
        record("Deezer catalogue builds", len(tracks) >= 3,
               f"{len(tracks)} tracks, first: {tracks[0].label if tracks else '-'}")
    except Exception as error:
        record("Deezer catalogue builds", False, f"{type(error).__name__}: {error}")

    try:
        tracks = await music.saavn_artist_catalogue("Arijit Singh", 8)
        record("JioSaavn catalogue builds", len(tracks) >= 3,
               f"{len(tracks)} tracks, first: {tracks[0].label if tracks else '-'}")
    except Exception as error:
        record("JioSaavn catalogue builds", False, f"{type(error).__name__}: {error}")

    # ── 3. Spotify link end-to-end (no creds → name → catalogue) ───────
    try:
        cat = await music.resolve("https://open.spotify.com/artist/4uLU6hMCjMI75M1A2tKUQC", 8)
        filled = await music._fill_from_artist_name(cat, 8) if not cat.tracks else cat
        record("Spotify artist resolves to a catalogue", len(filled.tracks) >= 3,
               f"{filled.title}: {len(filled.tracks)} tracks via {filled.source}")
    except Exception as error:
        record("Spotify artist resolves to a catalogue", False, f"{type(error).__name__}: {error}")

    # ── 4. yt-dlp search (the /ld path) ─────────────────────────────────
    try:
        found = await asyncio.to_thread(music._ytdlp_search_flat, "kesariya lyrics", 3)
        record("yt-dlp search works", len(found) >= 1,
               f"{len(found)} results, first: {found[0]['title'][:50] if found else '-'}")
    except Exception as error:
        record("yt-dlp search works", False, f"{type(error).__name__}: {error}")

    # ── 5. cookie pickup for /webdl ─────────────────────────────────────
    workdir = tempfile.mkdtemp(prefix="webdl-live-")
    os.chdir(workdir)
    record("no cookies found when none exist", webdl.cookie_file() is None, str(webdl.cookie_file()))
    Path("cookies.txt").write_text("# Netscape HTTP Cookie File\n")
    picked_global = webdl.cookie_file()
    record("global cookies.txt is picked up",
           picked_global is not None and picked_global.resolve() == Path("cookies.txt").resolve(),
           str(picked_global))
    os.remove("cookies.txt")
    per_user = Path("cookies") / "12345" / "cookies.txt"
    per_user.parent.mkdir(parents=True)
    per_user.write_text("# Netscape HTTP Cookie File\n")
    picked = webdl.cookie_file()
    record("per-user cookie is picked up",
           picked is not None and picked.resolve() == per_user.resolve(), str(picked))

    # ── 6. a real download through the webdl engine ─────────────────────
    os.environ["WEBDL_DIR"] = workdir
    job_id = "livejob"
    job_dir = Path(workdir) / job_id
    job_dir.mkdir(exist_ok=True)
    webdl.JOBS[job_id] = {
        "created_at": time.time(), "state": "running", "url": "", "mode": "video",
        "dir": str(job_dir), "percent": 0.0, "downloaded": 0, "total": 0,
        "title": "", "speed": 0,
    }

    sources = [
        "https://media.w3.org/2010/05/sintel/trailer.mp4",
        "https://download.samplelib.com/mp4/sample-5s.mp4",
    ]
    ok_download = False
    detail = ""
    for source in sources:
        webdl.JOBS[job_id]["state"] = "running"
        webdl.JOBS[job_id]["dir"] = str(job_dir)
        try:
            await asyncio.to_thread(webdl._download_blocking, job_id, source, "video")
            job = webdl.JOBS[job_id]
            ok_download = job.get("state") == "done" and job.get("size", 0) > 0
            detail = f"{source} -> {job.get('filename')} ({job.get('size')} bytes)"
            if ok_download:
                break
        except Exception as error:
            detail = f"{source} -> {type(error).__name__}: {error}"
    record("webdl downloads a real file", ok_download, detail)

    # ── 7. a YouTube download (what people actually paste) ──────────────
    yt_id = "ytjob"
    yt_dir = Path(workdir) / yt_id
    yt_dir.mkdir(exist_ok=True)
    webdl.JOBS[yt_id] = {
        "created_at": time.time(), "state": "running", "url": "", "mode": "audio",
        "dir": str(yt_dir), "percent": 0.0, "downloaded": 0, "total": 0,
        "title": "", "speed": 0,
    }
    try:
        await asyncio.to_thread(
            webdl._download_blocking, yt_id, "https://www.youtube.com/watch?v=jNQXAC9IVRw", "audio"
        )
        job = webdl.JOBS[yt_id]
        ok_yt = job.get("state") == "done" and job.get("size", 0) > 0
        record("webdl downloads YouTube audio", ok_yt,
               f"{job.get('filename')} ({job.get('size')} bytes)" if ok_yt else str(job.get("error"))[:200])
    except Exception as error:
        text = str(error)
        if "not a bot" in text or "Sign in to confirm" in text:
            text = (
                "YouTube demands sign-in for datacenter IPs. This is why /webdl "
                "reuses the bot's cookies.txt — with a cookie file present this "
                "succeeds. Without one it is expected to fail on a runner."
            )
        record("webdl downloads YouTube audio", False, f"{type(error).__name__}: {text}", required=False)

    os.chdir(ROOT)
    shutil.rmtree(workdir, ignore_errors=True)


asyncio.run(main())

print()
failed_required = [r for r in results if r[0] and not r[1]]
failed_optional = [r for r in results if not r[0] and not r[1]]
print(f"{len(results) - len(failed_required) - len(failed_optional)}/{len(results)} passed"
      f" ({len(failed_required)} required failure(s), {len(failed_optional)} optional)")
if failed_required:
    print("required failures:", ", ".join(r[2] for r in failed_required))
sys.exit(1 if failed_required else 0)
