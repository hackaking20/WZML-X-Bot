"""Browser downloader for Amaterasu — backend.

Full version, modelled on the R17 "webdl" module in vot1122/Kaggle-auto but
rebuilt for this bot: it registers on Amaterasu's own FastAPI app, reuses the
bot's cookies and yt-dlp workarounds, and serves a proper front-end that can
also be hosted on GitHub Pages (cross-origin, with header auth).

Routes
    GET    /webdl                    the app
    GET    /webdl/api/info           capabilities + cookie state
    POST   /webdl/api/probe          metadata for a link, before downloading
    POST   /webdl/api/start          begin a job
    GET    /webdl/api/status/{id}    progress
    GET    /webdl/api/jobs           recent jobs
    GET    /webdl/download/{id}      the file
    POST   /webdl/api/cancel/{id}    stop and clean up

Auth
    Same-origin browser use is covered by the bot's own LOGIN_PASS cookie.
    A front-end hosted elsewhere cannot send that cookie, so set WEBDL_PASS
    and the client sends it as the X-Webdl-Pass header. Five wrong attempts
    block that IP for a minute.

CORS
    WEBDL_ORIGINS is a comma-separated allow-list; "*" allows any origin.
    The default is "*" when WEBDL_PASS is set (header auth, no cookies) and
    same-origin only otherwise.
"""

import asyncio
import ipaddress
import os
import re
import shutil
import socket
import time
import uuid
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

JOBS: Dict[str, dict] = {}
_ACTIVE = 0
_STARTED = False
_FAILS: Dict[str, list] = {}
_VERSION = "2.0.0"


# ─────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _max_concurrent() -> int:
    return _int_env("WEBDL_CONC", 2, 1, 8)


def _ttl_seconds() -> int:
    return _int_env("WEBDL_TTL", 6, 1, 72) * 3600


def _max_gb() -> int:
    return _int_env("WEBDL_MAX_GB", 8, 1, 100)


def _work_dir() -> Path:
    path = Path(os.environ.get("WEBDL_DIR", "webdl_downloads"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _password() -> str:
    return os.environ.get("WEBDL_PASS", "").strip()


def _web_password() -> str:
    """Password for the /links page.

    Order: WEB_ACCESS_PASSWORD (the bot's own web login) -> WEBDL_PASS ->
    a value set with /setwebpass in Mongo -> the default "joshi".
    """
    for name in ("WEB_ACCESS_PASSWORD", "WEBDL_PASS"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    stored = _stored_password()
    return stored or "joshi"


def _stored_password() -> str:
    """Password saved by /setwebpass, read from the shared database."""
    now = time.time()
    if _PASS_CACHE["value"] and now - _PASS_CACHE["at"] < 5:
        return _PASS_CACHE["value"]
    try:
        from pymongo import MongoClient

        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            return ""
        with MongoClient(url, serverSelectionTimeoutMS=4000) as client:
            doc = client["webpass"]["config"].find_one({"_id": "web_access_password"})
        value = (doc or {}).get("value", "") or ""
        _PASS_CACHE["value"] = value
        _PASS_CACHE["at"] = now
        return value
    except Exception:
        return ""


_PASS_CACHE = {"value": "", "at": 0.0}


def _origins() -> list:
    raw = os.environ.get("WEBDL_ORIGINS", "").strip()
    if raw:
        return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    return ["*"] if _password() else []


# ─────────────────────────────────────────────────────────────────────────
# Cookies — reuse whatever the bot already has
# ─────────────────────────────────────────────────────────────────────────


def _app_dir() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except Exception:
        return Path.cwd()


def _cookie_bases():
    seen, bases = set(), []
    for base in (Path.cwd(), _app_dir()):
        try:
            key = base.resolve()
        except Exception:
            key = base
        if key not in seen:
            seen.add(key)
            bases.append(base)
    return bases


def cookie_file() -> Optional[Path]:
    """Override, then global cookies.txt, then the freshest per-user file."""
    override = os.environ.get("WEBDL_COOKIE_FILE", "").strip()
    if override:
        path = Path(override)
        if path.is_file() and path.stat().st_size > 0:
            return path
    for base in _cookie_bases():
        global_cookie = base / "cookies.txt"
        try:
            if global_cookie.is_file() and global_cookie.stat().st_size > 0:
                return global_cookie
        except OSError:
            pass
    candidates = []
    for base in _cookie_bases():
        for path in (base / "cookies").glob("*/cookies.txt"):
            try:
                if path.is_file() and path.stat().st_size > 0:
                    candidates.append(path)
            except OSError:
                continue
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def cookie_label() -> str:
    path = cookie_file()
    if path is None:
        return "none"
    try:
        return f"{path.name} ({max(1, path.stat().st_size // 1024)} KB)"
    except OSError:
        return str(path)


# ─────────────────────────────────────────────────────────────────────────
# Safety
# ─────────────────────────────────────────────────────────────────────────

_BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def _host_is_private(host: str) -> bool:
    if not host:
        return True
    if host.lower() in _BLOCKED_HOSTS:
        return True
    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for _family, _, _, _, sockaddr in addresses:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def url_is_allowed(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return not _host_is_private(parsed.hostname or "")


# ─────────────────────────────────────────────────────────────────────────
# Auth + CORS
# ─────────────────────────────────────────────────────────────────────────

_MAX_FAILS = 5
_FAIL_WINDOW = 60


def _client_ip(request) -> str:
    try:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return getattr(request.client, "host", "") or "?"
    except Exception:
        return "?"


def _blocked(ip: str) -> bool:
    now = time.time()
    hits = [stamp for stamp in _FAILS.get(ip, []) if now - stamp < _FAIL_WINDOW]
    _FAILS[ip] = hits
    return len(hits) >= _MAX_FAILS


def _note_failure(ip: str) -> None:
    _FAILS.setdefault(ip, []).append(time.time())


def _pass_ok(request) -> bool:
    """True when the caller may use the API."""
    from hmac import compare_digest

    expected = _password()
    if not expected:
        return True
    supplied = request.headers.get("x-webdl-pass", "") or request.query_params.get("pass", "")
    if supplied and compare_digest(supplied, expected):
        return True
    _note_failure(_client_ip(request))
    return False


def _cookie_ok(request) -> bool:
    """The bot's own login cookie — same-origin browser use."""
    try:
        from web.wserver import _login_pass_configured, _verify_session_cookie
    except Exception:
        return True
    try:
        if not _login_pass_configured():
            return True
        return bool(_verify_session_cookie(request.cookies.get("amaterasu_session")))
    except Exception:
        return True


def _cors_headers(request) -> dict:
    origin = request.headers.get("origin", "")
    allowed = _origins()
    if "*" in allowed:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "content-type, x-webdl-pass",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        }
    if origin and origin.rstrip("/") in allowed:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "content-type, x-webdl-pass",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        }
    return {}


# ─────────────────────────────────────────────────────────────────────────
# yt-dlp plumbing
# ─────────────────────────────────────────────────────────────────────────


def build_options(job_id: str, out_dir: Path, mode: str, quality: str = "") -> dict:
    """Options for one job.

    extractor_args + impersonation are what stop YouTube answering with
    "Sign in to confirm you're not a bot" — Amaterasu's own downloader sets
    the same two, which is why the identical link works in Telegram.
    """
    options = {
        "outtmpl": str(out_dir / "%(title).100s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": _max_gb() * 1024 * 1024 * 1024,
        "progress_hooks": [_progress_hook(job_id)],
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 10,
        "restrictfilenames": True,
        "trim_file_name": 120,
        "usenetrc": True,
        "extractor_args": {
            "youtube": {"skip": ["webpage"]},
            "youtubetab": {"skip": ["webpage", "authcheck"]},
        },
    }
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        options["impersonate"] = ImpersonateTarget.from_str("chrome")
    except Exception:
        pass

    cookie = cookie_file()
    if cookie is not None:
        options["cookiefile"] = str(cookie)

    if mode == "audio":
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            },
            {"key": "FFmpegMetadata"},
        ]
    else:
        height = re.sub(r"\D", "", quality or "")
        if height:
            options["format"] = (
                f"bv*[height<={height}]+ba/b[height<={height}]/bv*+ba/b"
            )
        else:
            options["format"] = "bv*+ba/b"
    return options


def _progress_hook(job_id: str):
    def hook(update):
        job = JOBS.get(job_id)
        if not job:
            return
        status = update.get("status")
        if status == "downloading":
            downloaded = update.get("downloaded_bytes") or 0
            total = update.get("total_bytes") or update.get("total_bytes_estimate") or 0
            job["downloaded"] = int(downloaded)
            job["total"] = int(total)
            job["percent"] = round(downloaded * 100 / total, 1) if total else 0
            speed = update.get("speed")
            if speed:
                job["speed"] = int(speed)
                if total:
                    job["eta"] = int(max(0, (total - downloaded) / speed))
            title = update.get("info_dict", {}).get("title")
            if title and not job.get("title"):
                job["title"] = str(title)[:200]
            job["stage"] = "downloading"
        elif status == "finished":
            job["percent"] = 100
            job["state"] = "processing"
            job["stage"] = "processing"

    return hook


def normalise_url(url: str) -> str:
    """Rewrite a YouTube watch URL into its short form.

    yt-dlp's watch-URL path picks a player client that reports every format as
    DRM-protected on some videos ("This video is DRM protected"), while the
    same video via youtu.be or /shorts/ extracts cleanly. Rewriting the URL
    sidesteps the whole class of failure.

    A URL that explicitly carries list= is left alone, because there the
    playlist is what was asked for.
    """
    try:
        from urllib.parse import parse_qs, urlparse

        parts = urlparse(url)
        host = (parts.hostname or "").lower()
        if not host.endswith("youtube.com") and not host.endswith("youtube-nocookie.com"):
            return url
        if parts.path != "/watch":
            return url
        query = parse_qs(parts.query)
        if "list" in query:
            return url
        video_id = (query.get("v") or [""])[0].strip()
        if not video_id:
            return url
        return f"https://youtu.be/{video_id}"
    except Exception:
        return url


def youtube_id(url: str) -> str:
    """Pull the video id out of any YouTube URL shape."""
    try:
        from urllib.parse import parse_qs, urlparse

        parts = urlparse(url)
        host = (parts.hostname or "").lower()
        if host.endswith("youtu.be"):
            return parts.path.strip("/").split("/")[0]
        if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
            if parts.path == "/watch":
                return (parse_qs(parts.query).get("v") or [""])[0]
            if parts.path.startswith("/shorts/") or parts.path.startswith("/embed/"):
                return parts.path.split("/")[2]
        return ""
    except Exception:
        return ""


def candidate_urls(url: str) -> list:
    """URL forms to try, in order, for one video.

    The watch and youtu.be paths make yt-dlp pick a client that reports
    "This video is DRM protected" for some music videos, while the /shorts/
    form of the same video extracts cleanly. Trying them in turn is cheaper
    than guessing which quirk applies today.
    """
    base = normalise_url(url)
    video_id = youtube_id(url)
    if not video_id:
        return [base]
    forms = [
        base,
        f"https://www.youtube.com/shorts/{video_id}",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    seen, ordered = set(), []
    for form in forms:
        if form not in seen:
            seen.add(form)
            ordered.append(form)
    return ordered


def _probe_blocking(url: str) -> dict:
    import yt_dlp

    last_error = None
    for attempt_url in candidate_urls(url):
        try:
            return _probe_one(yt_dlp, attempt_url)
        except Exception as error:  # try the next URL form
            last_error = error
    raise last_error if last_error else RuntimeError("probe failed")


def _probe_one(yt_dlp, url: str) -> dict:
    options = build_options("probe", _work_dir(), "video")
    options.pop("progress_hooks", None)
    options.pop("outtmpl", None)
    options.pop("max_filesize", None)
    # A watch URL with no list= is a single video. Without this, yt-dlp happily
    # expands it into the 500-entry "Mix" playlist YouTube serves alongside it.
    wants_playlist = "list=" in url
    options["noplaylist"] = not wants_playlist
    options["extract_flat"] = "in_playlist" if wants_playlist else False
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") == "playlist":
        entries = [entry for entry in (info.get("entries") or []) if entry]
        return {
            "playlist": True,
            "title": str(info.get("title") or "Playlist")[:200],
            "count": len(entries),
            "entries": [
                {"title": str(entry.get("title") or "")[:120]} for entry in entries[:20]
            ],
            "thumbnail": info.get("thumbnail") or "",
        }

    formats = []
    for fmt in info.get("formats") or []:
        height = fmt.get("height")
        if fmt.get("vcodec") in (None, "none") or not height:
            continue
        formats.append(
            {
                "height": height,
                "ext": fmt.get("ext") or "",
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx") or 0,
                "fps": fmt.get("fps") or 0,
            }
        )
    heights = sorted({item["height"] for item in formats}, reverse=True)
    return {
        "playlist": False,
        "requested": url,
        "title": str(info.get("title") or "")[:200],
        "duration": int(info.get("duration") or 0),
        "uploader": str(info.get("uploader") or "")[:100],
        "thumbnail": info.get("thumbnail") or "",
        "ext": info.get("ext") or "",
        "filesize": info.get("filesize") or info.get("filesize_approx") or 0,
        "heights": heights[:8],
    }


def _download_blocking(job_id: str, url: str, mode: str, quality: str = "") -> None:
    import yt_dlp

    job = JOBS.get(job_id)
    if not job:
        return
    out_dir = Path(job["dir"])
    options = build_options(job_id, out_dir, mode, quality)
    print(
        f"[webdl] job {job_id} mode={mode} quality={quality or 'best'} "
        f"cookies={options.get('cookiefile') or 'none'}",
        flush=True,
    )

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    job = JOBS.get(job_id)
    if not job or job.get("state") == "cancelled":
        return

    produced: Optional[Path] = None
    try:
        requested = (info or {}).get("requested_downloads") or []
        if requested and requested[0].get("filepath"):
            produced = Path(requested[0]["filepath"])
    except Exception:
        produced = None
    if produced is None or not produced.exists():
        candidates = sorted(
            (p for p in out_dir.glob("**/*") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        produced = candidates[0] if candidates else None
    if produced is None:
        raise RuntimeError("yt-dlp finished but produced no file")

    if job.get("state") == "cancelled":
        return
    job["file"] = str(produced)
    job["filename"] = produced.name
    job["size"] = produced.stat().st_size
    job["title"] = job.get("title") or (info or {}).get("title") or produced.stem
    job["state"] = "done"
    job["percent"] = 100
    job["stage"] = "done"


async def _run_job(job_id: str) -> None:
    global _ACTIVE
    job = JOBS.get(job_id)
    if not job or job.get("state") == "cancelled":
        return
    job["state"] = "running"
    try:
        await asyncio.to_thread(
            _download_blocking, job_id, job["url"], job["mode"], job.get("quality", "")
        )
    except Exception as error:
        job = JOBS.get(job_id)
        if job is not None and job.get("state") != "cancelled":
            text = str(error)
            if "not a bot" in text or "Sign in to confirm" in text:
                found = cookie_file()
                text = (
                    "YouTube wants a sign-in from this server's IP. "
                    + (
                        f"A cookie file was found ({found}) but it was not enough — "
                        "re-export it while logged in."
                        if found
                        else "No cookie file found. Upload one via /us → YT Cookie File."
                    )
                )
            job["state"] = "error"
            job["error"] = text[:400]
    finally:
        _ACTIVE = max(0, _ACTIVE - 1)
        job = JOBS.get(job_id)
        if job is not None:
            job["finished_at"] = time.time()


def _cleanup_once() -> int:
    now = time.time()
    removed = 0
    for job_id in list(JOBS):
        job = JOBS[job_id]
        finished = job.get("finished_at")
        if finished is None:
            finished = job.get("created_at") or now
        if job["state"] in {"done", "error", "cancelled"} and now - finished > _ttl_seconds():
            shutil.rmtree(job.get("dir", ""), ignore_errors=True)
            JOBS.pop(job_id, None)
            removed += 1
    work = _work_dir()
    for child in work.iterdir() if work.exists() else []:
        try:
            if child.is_dir() and now - child.stat().st_mtime > _ttl_seconds():
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(600)
        try:
            _cleanup_once()
        except Exception:
            pass


def _disk_usage_gb() -> float:
    work = _work_dir()
    total = 0
    for path in work.glob("**/*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total / (1024 ** 3)


def _job_view(job_id: str, job: dict) -> dict:
    return {
        "job_id": job_id,
        "state": job["state"],
        "percent": job.get("percent", 0.0),
        "title": job.get("title", ""),
        "size": job.get("size", 0),
        "downloaded": job.get("downloaded", 0),
        "total": job.get("total", 0),
        "speed": job.get("speed", 0),
        "eta": job.get("eta", 0),
        "mode": job.get("mode", ""),
        "quality": job.get("quality", ""),
        "stage": job.get("stage", ""),
        "error": job.get("error", ""),
        "filename": job.get("filename", ""),
    }


# ─────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────


def _page_html() -> str:
    """The front-end. setup-runner.sh drops it at web/webdl_ui.html."""
    for candidate in (
        _app_dir() / "web" / "webdl_ui.html",
        Path.cwd() / "web" / "webdl_ui.html",
    ):
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    return (
        "<!doctype html><meta charset=utf-8><title>Amaterasu</title>"
        "<body style='font:16px system-ui;background:#0d0d10;color:#eee;padding:2rem'>"
        "<h1>Amaterasu downloader</h1>"
        "<p>webdl_ui.html was not installed next to web/wserver.py — "
        "re-run the setup script.</p>"
    )


def register(app) -> None:
    global _STARTED
    from fastapi import Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

    if getattr(app, "_webdl_registered", False):
        return
    app._webdl_registered = True

    def _reply(request, payload, status=200):
        return JSONResponse(payload, status_code=status, headers=_cors_headers(request))

    def _deny(request, reason="auth", status=401):
        return _reply(request, {"detail": reason}, status)

    @app.options("/webdl/api/{rest:path}")
    async def webdl_preflight(request: Request, rest: str):
        return _reply(request, {"ok": True})

    @app.get("/webdl", response_class=HTMLResponse)
    async def webdl_page(request: Request):
        html = _page_html()
        return HTMLResponse(html, headers=_cors_headers(request))

    @app.get("/webdl/api/info")
    async def webdl_info(request: Request):
        if _blocked(_client_ip(request)):
            return _deny(request, "too many attempts, wait a minute", 429)
        return _reply(
            request,
            {
                "version": _VERSION,
                "cookies": cookie_label(),
                "active": _ACTIVE,
                "concurrent": _max_concurrent(),
                "disk_gb": round(_disk_usage_gb(), 2),
                "max_gb": _max_gb(),
                "ttl_hours": _ttl_seconds() // 3600,
                "auth_required": bool(_password()),
                "login_required": not _cookie_ok(request) and not _password(),
            },
        )

    @app.post("/webdl/api/probe")
    async def webdl_probe(request: Request):
        if _blocked(_client_ip(request)):
            return _deny(request, "too many attempts, wait a minute", 429)
        if not _pass_ok(request):
            return _deny(request, "password required")
        if not _cookie_ok(request) and not _password():
            return _deny(request, "login required")
        try:
            body = await request.json()
        except Exception:
            return _reply(request, {"detail": "invalid JSON"}, 400)
        url = str(body.get("url") or "").strip()
        if not url:
            return _reply(request, {"detail": "no URL given"}, 400)
        if not await asyncio.to_thread(url_is_allowed, url):
            return _reply(request, {"detail": "only public http(s) URLs"}, 400)
        try:
            info = await asyncio.to_thread(_probe_blocking, url)
        except Exception as error:
            text = str(error)
            if "not a bot" in text or "Sign in to confirm" in text:
                found = cookie_file()
                text = (
                    "YouTube wants a sign-in from this server's IP. "
                    + (f"Cookie found ({found}) but rejected — re-export it."
                       if found else "No cookie file found — upload one via /us → YT Cookie File.")
                )
            return _reply(request, {"detail": text[:400]}, 422)
        return _reply(request, info)

    @app.post("/webdl/api/start")
    async def webdl_start(request: Request):
        global _ACTIVE
        if _blocked(_client_ip(request)):
            return _deny(request, "too many attempts, wait a minute", 429)
        if not _pass_ok(request):
            return _deny(request, "password required")
        if not _cookie_ok(request) and not _password():
            return _deny(request, "login required")
        try:
            body = await request.json()
        except Exception:
            return _reply(request, {"detail": "invalid JSON"}, 400)

        url = normalise_url(str(body.get("url") or "").strip())
        mode = "audio" if str(body.get("mode") or "").lower() == "audio" else "video"
        quality = str(body.get("quality") or "").strip()

        if not url:
            return _reply(request, {"detail": "no URL given"}, 400)
        if not await asyncio.to_thread(url_is_allowed, url):
            return _reply(request, {"detail": "only public http(s) URLs"}, 400)
        if _ACTIVE >= _max_concurrent():
            return _reply(
                request,
                {"detail": f"already fetching {_ACTIVE} file(s) — wait for one to finish"},
                429,
            )
        if _disk_usage_gb() >= _max_gb():
            _cleanup_once()
            if _disk_usage_gb() >= _max_gb():
                return _reply(request, {"detail": f"disk budget of {_max_gb()} GB is full"}, 507)

        job_id = uuid.uuid4().hex[:12]
        job_dir = _work_dir() / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        JOBS[job_id] = {
            "created_at": time.time(),
            "state": "queued",
            "stage": "queued",
            "url": url,
            "mode": mode,
            "quality": quality,
            "dir": str(job_dir),
            "percent": 0.0,
            "downloaded": 0,
            "total": 0,
            "title": str(body.get("title") or "")[:200],
            "speed": 0,
            "eta": 0,
        }
        _ACTIVE += 1
        asyncio.create_task(_run_job(job_id))
        return _reply(request, {"job_id": job_id})

    @app.get("/webdl/api/status/{job_id}")
    async def webdl_status(request: Request, job_id: str):
        if not _pass_ok(request):
            return _deny(request, "password required")
        job = JOBS.get(job_id)
        if not job:
            return _reply(request, {"detail": "unknown job"}, 404)
        return _reply(request, _job_view(job_id, job))

    @app.get("/webdl/api/jobs")
    async def webdl_jobs(request: Request):
        if not _pass_ok(request):
            return _deny(request, "password required")
        ordered = sorted(
            JOBS.items(), key=lambda item: item[1].get("created_at", 0), reverse=True
        )[:20]
        return _reply(request, {"jobs": [_job_view(job_id, job) for job_id, job in ordered]})

    @app.get("/webdl/download/{job_id}")
    async def webdl_download(request: Request, job_id: str):
        if not _pass_ok(request):
            return _deny(request, "password required")
        job = JOBS.get(job_id)
        if not job or job["state"] != "done" or not job.get("file"):
            return _reply(request, {"detail": "not ready"}, 404)
        path = Path(job["file"])
        if not path.exists():
            return _reply(request, {"detail": "file is gone"}, 410)
        return FileResponse(
            path,
            filename=job.get("filename") or path.name,
            media_type="application/octet-stream",
            headers=_cors_headers(request),
        )

    @app.post("/webdl/api/cancel/{job_id}")
    async def webdl_cancel(request: Request, job_id: str):
        global _ACTIVE
        if not _pass_ok(request):
            return _deny(request, "password required")
        job = JOBS.get(job_id)
        if not job:
            return _reply(request, {"detail": "unknown job"}, 404)
        if job["state"] in {"queued", "running", "processing"}:
            job["state"] = "cancelled"
            shutil.rmtree(job.get("dir", ""), ignore_errors=True)
            _ACTIVE = max(0, _ACTIVE - 1)
        return _reply(request, {"state": job["state"]})

    @app.get("/api/tunnel")
    async def tunnel_info():
        """The bot's own public URL, straight from its config.

        Far more reliable than scraping the log for a hostname, and it is the
        only thing the supervisor needs to keep tunnel.json current.
        """
        import datetime as _dt

        url = ""
        # Amaterasu computes BASE_URL into its config; the environment only has
        # it if the workflow set it explicitly.
        try:
            from bot.core.config_manager import Config

            url = str(getattr(Config, "BASE_URL", "") or "")
        except Exception:
            url = ""
        if not url:
            url = os.environ.get("BASE_URL", "")
        if not url:
            # last resort: the tunnel monitor's own record
            try:
                from bot.core.cloudflare_tunnel import cloudflare_tunnel

                url = str(getattr(cloudflare_tunnel, "tunnel_url", "") or "")
            except Exception:
                url = ""

        return {
            "url": url.strip().rstrip("/"),
            "updated": _dt.datetime.now(_dt.timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        }

    # ── /links: every page this bot serves, with its password ──────────
    def _links_html(unlocked: bool, error: str = "", request=None) -> str:
        import html as _html

        # Prefer the live public URL; fall back to whatever the caller used.
        base = os.environ.get("BASE_URL", "").strip().rstrip("/")
        if not base and request is not None:
            try:
                base = str(request.base_url).rstrip("/")
            except Exception:
                base = ""

        pages = [
            ("Web downloader", "/webdl", "the full downloader app"),
            ("Main web UI", "/", "bot dashboard and login"),
            ("Session generator", "/app/session-generator", "make a user session string"),
            ("FileToLink", "/app/", "stream files by link (needs STREAM_PASS)"),
            ("qBittorrent", "/qbit/", "torrent client (pass is per run, see the log)"),
            ("SABnzbd", "/nzb/", "usenet client (pass is per run, see the log)"),
        ]
        pw = _web_password()
        rows = ""
        for name, path, note in pages:
            url = f"{base}{path}" if base else path
            shown = _html.escape(pw if path not in ("/qbit/", "/nzb/") else "per-run")
            rows += (
                f'<tr><td><a href="{_html.escape(url)}" target="_blank" rel="noopener">'
                f'{_html.escape(name)}</a><div class="note">{_html.escape(note)}</div></td>'
                f'<td class="pw">{shown}</td></tr>'
            )

        if not unlocked:
            return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pages</title><style>
body{{background:#0f1115;color:#e6e6e6;font:15px/1.5 system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0}}
.card{{background:#171a21;padding:28px 30px;border-radius:14px;width:min(360px,92vw);border:1px solid #23262f}}
h1{{font-size:17px;margin:0 0 6px}}p{{color:#8b93a7;margin:0 0 18px;font-size:13px}}
input{{width:100%;padding:11px;border-radius:9px;border:1px solid #2b2f3a;background:#0f1115;color:#e6e6e6;font-size:15px}}
button{{width:100%;margin-top:12px;padding:11px;border:0;border-radius:9px;background:#3b6cf6;color:#fff;font-size:15px;cursor:pointer}}
.err{{color:#ff7a7a;font-size:13px;margin-top:10px}}
</style></head><body><form class="card" method="post" action="/links">
<h1>Pages &amp; passwords</h1><p>Enter the web password.</p>
<input type="password" name="password" autofocus autocomplete="current-password">
<button type="submit">Unlock</button>{f'<div class="err">{_html.escape(error)}</div>' if error else ''}
</form></body></html>"""

        return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pages &amp; passwords</title><style>
body{{background:#0f1115;color:#e6e6e6;font:15px/1.6 system-ui,sans-serif;margin:0;padding:28px 18px}}
.wrap{{max-width:760px;margin:0 auto}}
h1{{font-size:19px;margin:0 0 4px}}p.sub{{color:#8b93a7;font-size:13px;margin:0 0 22px}}
table{{width:100%;border-collapse:collapse;background:#171a21;border-radius:12px;overflow:hidden}}
td{{padding:13px 16px;border-bottom:1px solid #23262f;vertical-align:top}}
tr:last-child td{{border-bottom:0}}
a{{color:#7aa2ff;text-decoration:none}}a:hover{{text-decoration:underline}}
.note{{color:#8b93a7;font-size:12px;margin-top:2px}}
.pw{{font-family:ui-monospace,monospace;color:#8ef0b8;text-align:right;white-space:nowrap}}
</style></head><body><div class="wrap">
<h1>Pages &amp; passwords</h1><p class="sub">Live tunnel: {_html.escape(base) or "unknown"}</p>
<table>{rows}</table></div></body></html>"""

    @app.get("/links", response_class=HTMLResponse)
    async def links_page(request: Request):
        from hmac import compare_digest

        cookie = request.cookies.get("links_session", "")
        unlocked = bool(cookie) and compare_digest(cookie, _web_password())
        return HTMLResponse(_links_html(unlocked, request=request))

    @app.post("/links", response_class=HTMLResponse)
    async def links_login(request: Request):
        from hmac import compare_digest

        # request.form() needs python-multipart; fall back to the raw body so
        # the login works even if that package is missing.
        supplied = ""
        try:
            form = await request.form()
            supplied = str(form.get("password", "")).strip()
        except Exception:
            from urllib.parse import parse_qs

            raw = (await request.body()).decode("utf-8", "replace")
            supplied = (parse_qs(raw).get("password") or [""])[0].strip()
        expected = _web_password()
        if supplied and compare_digest(supplied, expected):
            response = HTMLResponse(_links_html(True, request=request))
            response.set_cookie(
                "links_session", expected, max_age=60 * 60 * 12,
                httponly=True, samesite="lax", secure=True,
            )
            return response
        _note_failure(_client_ip(request))
        return HTMLResponse(_links_html(False, "Wrong password.", request=request), status_code=401)

    if not _STARTED:
        _STARTED = True
        try:
            app.add_event_handler("startup", lambda: asyncio.create_task(_cleanup_loop()))
        except Exception:
            pass
