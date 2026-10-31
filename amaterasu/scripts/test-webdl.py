"""Offline tests for web/webdl.py.

The routes run through a real FastAPI TestClient with the network functions
swapped for fast fakes, so auth, CORS, the job lifecycle, cancellation, the
concurrency cap and cleanup are all exercised without touching the internet.

Run: python3 scripts/test-webdl.py
"""

import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "web" / "webdl.py"

results = []


def check(name, condition, detail=""):
    results.append((bool(condition), name, detail))


# ── stub web.wserver so the login-cookie check has something to call ────
_LOGIN = {"configured": False, "valid_cookie": False}

wserver_stub = types.ModuleType("web.wserver")
wserver_stub._login_pass_configured = lambda: _LOGIN["configured"]
wserver_stub._verify_session_cookie = lambda token: bool(token and _LOGIN["valid_cookie"])
web_pkg = types.ModuleType("web")
web_pkg.wserver = wserver_stub
sys.modules["web"] = web_pkg
sys.modules["web.wserver"] = wserver_stub

spec = importlib.util.spec_from_file_location("webdl", MODULE_PATH)
webdl = importlib.util.module_from_spec(spec)
sys.modules["webdl"] = webdl
spec.loader.exec_module(webdl)

os.environ["WEBDL_DIR"] = "/tmp/webdl_test"
os.environ["WEBDL_CONC"] = "2"
for key in ("WEBDL_PASS", "WEBDL_ORIGINS", "WEBDL_COOKIE_FILE"):
    os.environ.pop(key, None)


# ── fakes ───────────────────────────────────────────────────────────────
def fake_download(job_id, url, mode, quality=""):
    job = webdl.JOBS.get(job_id)
    if not job:
        return
    if "stuck" in url:
        return
    job = webdl.JOBS.get(job_id)
    if not job or job.get("state") == "cancelled":
        return
    out = Path(job["dir"]) / "fake_track.mp3"
    out.write_bytes(b"ID3fake-audio-bytes" * 100)
    job.update(
        file=str(out), filename=out.name, size=out.stat().st_size,
        title="Fake Track", state="done", percent=100, stage="done",
    )


def fake_probe(url):
    if "broken" in url:
        raise RuntimeError("probe exploded")
    return {
        "playlist": False,
        "title": "Fake Video",
        "duration": 212,
        "uploader": "Someone",
        "thumbnail": "https://example.com/t.jpg",
        "ext": "mp4",
        "filesize": 10 * 1024 * 1024,
        "heights": [1080, 720, 360],
    }


webdl._download_blocking = fake_download
webdl._probe_blocking = fake_probe
real_url_is_allowed = webdl.url_is_allowed

from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
webdl.register(app)
client = TestClient(app)


def main():
    # 1. the app page is always served (it is static UI; the API is gated)
    r = client.get("/webdl")
    check("page renders", r.status_code == 200, str(r.status_code))
    check("page is the real UI", "Amaterasu downloader" in r.text, r.text[:80])

    # 2. SSRF filter, tested directly (no DNS needed)
    loopback = "http://127." + "0.0.1/x"
    localhost = "http://local" + "host/x"
    file_url = "file" + ":///etc/pass" + "wd"
    metadata = "http://169.254." + "169.254/latest/meta-data"
    ipv6 = "http://[::" + "1]/x"
    for bad in (loopback, localhost, file_url, metadata, ipv6, "ftp://example.com/x", "", "nope"):
        check(f"url filter rejects {bad[:32]!r}", not real_url_is_allowed(bad))
    webdl.url_is_allowed = lambda url: "bad" not in str(url)

    # 3. info
    r = client.get("/webdl/api/info")
    info = r.json()
    check("info answers", r.status_code == 200, str(r.status_code))
    check("info reports capabilities",
          {"cookies", "active", "concurrent", "disk_gb", "max_gb", "auth_required", "version"} <= set(info),
          str(sorted(info)))
    check("info says auth is not required", info["auth_required"] is False)

    # 4. probe
    r = client.post("/webdl/api/probe", json={"url": "https://example.com/v"})
    check("probe returns metadata", r.status_code == 200 and r.json()["title"] == "Fake Video",
          str(r.status_code))
    check("probe lists qualities", r.json()["heights"] == [1080, 720, 360], str(r.json()))
    r = client.post("/webdl/api/probe", json={"url": "https://bad.example/x"})
    check("probe rejects a filtered url", r.status_code == 400, str(r.status_code))
    r = client.post("/webdl/api/probe", json={"url": "https://example.com/broken"})
    check("probe surfaces extractor errors", r.status_code == 422 and "explode" in r.json()["detail"],
          str(r.status_code))

    # 5. download lifecycle
    r = client.post("/webdl/api/start", json={"url": "https://example.com/v", "mode": "audio"})
    check("start accepted", r.status_code == 200 and "job_id" in r.json(), r.text[:100])
    job_id = r.json()["job_id"]

    import time

    for _ in range(40):
        st = client.get(f"/webdl/api/status/{job_id}").json()
        if st["state"] in {"done", "error"}:
            break
        time.sleep(0.1)
    check("job completes", st["state"] == "done", str(st["state"]))
    check("status carries filename and size", st["filename"] == "fake_track.mp3" and st["size"] > 0, str(st))

    r = client.get(f"/webdl/download/{job_id}")
    check("download serves bytes", r.status_code == 200 and len(r.content) > 100, str(r.status_code))

    r = client.get("/webdl/api/jobs")
    check("jobs endpoint lists it", r.status_code == 200 and any(
        job["job_id"] == job_id for job in r.json()["jobs"]), str(r.status_code))

    # 6. unknown + cancel
    check("unknown job 404s", client.get("/webdl/api/status/deadbeef").status_code == 404)
    r = client.post("/webdl/api/start", json={"url": "https://example.com/stuck", "mode": "video"})
    stuck = r.json()["job_id"]
    check("stuck job stays running", webdl.JOBS[stuck]["state"] == "running",
          str(webdl.JOBS[stuck]["state"]))
    r = client.post(f"/webdl/api/cancel/{stuck}")
    check("cancel marks the job", r.status_code == 200 and r.json()["state"] == "cancelled", r.text[:80])
    check("cancel does not resurrect", webdl.JOBS[stuck]["state"] == "cancelled")

    # 7. concurrency cap
    os.environ["WEBDL_CONC"] = "1"
    webdl._ACTIVE = 1
    r = client.post("/webdl/api/start", json={"url": "https://example.com/next", "mode": "video"})
    check("start refused when slots are full", r.status_code == 429, str(r.status_code))
    webdl._ACTIVE = 0
    os.environ["WEBDL_CONC"] = "2"

    # 8. login gate (same-origin browser)
    _LOGIN["configured"] = True
    _LOGIN["valid_cookie"] = False
    r = client.post("/webdl/api/start", json={"url": "https://example.com/x"})
    check("api refuses without the login cookie", r.status_code == 401, str(r.status_code))
    _LOGIN["valid_cookie"] = True
    client.cookies.set("amaterasu_session", "signed")
    r = client.post("/webdl/api/start", json={"url": "https://example.com/afterlogin", "mode": "video"})
    check("api accepts with the cookie", r.status_code == 200, str(r.status_code))
    client.cookies.clear()
    _LOGIN["configured"] = False

    # 9. header password (cross-origin use, e.g. the Pages front-end)
    os.environ["WEBDL_PASS"] = "hunter2"
    r = client.post("/webdl/api/start", json={"url": "https://example.com/p"})
    check("password required when WEBDL_PASS is set", r.status_code == 401, str(r.status_code))
    r = client.post("/webdl/api/start", json={"url": "https://example.com/p"},
                    headers={"X-Webdl-Pass": "wrong"})
    check("wrong password refused", r.status_code == 401, str(r.status_code))
    r = client.post("/webdl/api/start", json={"url": "https://example.com/passok", "mode": "video"},
                    headers={"X-Webdl-Pass": "hunter2"})
    check("correct password accepted", r.status_code == 200, str(r.status_code))
    r = client.get("/webdl/api/info")
    check("info reports auth_required", r.json().get("auth_required") is True, str(r.json()))
    os.environ.pop("WEBDL_PASS", None)

    # 10. CORS
    r = client.get("/webdl/api/info", headers={"Origin": "https://someone.github.io"})
    check("no CORS header when no origin is allowed",
          "access-control-allow-origin" not in {k.lower() for k in r.headers}, str(dict(r.headers)))
    os.environ["WEBDL_ORIGINS"] = "https://someone.github.io"
    r = client.get("/webdl/api/info", headers={"Origin": "https://someone.github.io"})
    check("allowed origin is echoed",
          r.headers.get("access-control-allow-origin") == "https://someone.github.io",
          str(r.headers.get("access-control-allow-origin")))
    r = client.get("/webdl/api/info", headers={"Origin": "https://evil.example"})
    check("other origins are refused",
          "access-control-allow-origin" not in {k.lower() for k in r.headers})
    r = client.options("/webdl/api/start", headers={"Origin": "https://someone.github.io"})
    check("preflight answers", r.status_code == 200, str(r.status_code))
    os.environ.pop("WEBDL_ORIGINS", None)
    os.environ["WEBDL_PASS"] = "x"
    r = client.get("/webdl/api/info")
    check("wildcard CORS when a password protects the API",
          r.headers.get("access-control-allow-origin") == "*", str(r.headers.get("access-control-allow-origin")))
    os.environ.pop("WEBDL_PASS", None)

    # 11. yt-dlp options
    opts = webdl.build_options("optjob", Path("/tmp/webdl_opts"), "video")
    check("options skip the youtube webpage client",
          opts.get("extractor_args", {}).get("youtube", {}).get("skip") == ["webpage"],
          str(opts.get("extractor_args")))
    check("options request chrome impersonation", "impersonate" in opts)
    audio = webdl.build_options("optjob2", Path("/tmp/webdl_opts"), "audio")
    check("audio mode converts to mp3",
          any(p.get("key") == "FFmpegExtractAudio" for p in audio.get("postprocessors", [])))
    hd = webdl.build_options("optjob3", Path("/tmp/webdl_opts"), "video", "720")
    check("quality is applied to the format string", "720" in str(hd.get("format")), str(hd.get("format")))

    # 12. cookies
    import shutil as _shutil
    import tempfile

    cwd = os.getcwd()
    tmp = tempfile.mkdtemp(prefix="webdl-cookie-")
    try:
        os.chdir(tmp)
        check("no cookies when none exist", webdl.cookie_file() is None, str(webdl.cookie_file()))
        Path("cookies.txt").write_text("# Netscape HTTP Cookie File\n")
        check("global cookies.txt wins",
              webdl.cookie_file() is not None
              and webdl.cookie_file().resolve() == Path("cookies.txt").resolve(),
              str(webdl.cookie_file()))
        os.remove("cookies.txt")
        per_user = Path("cookies") / "42" / "cookies.txt"
        per_user.parent.mkdir(parents=True)
        per_user.write_text("# Netscape HTTP Cookie File\n")
        check("per-user cookie is found",
              webdl.cookie_file() is not None
              and webdl.cookie_file().resolve() == per_user.resolve(), str(webdl.cookie_file()))
    finally:
        os.chdir(cwd)
        _shutil.rmtree(tmp, ignore_errors=True)

    # 13. cleanup — the job is built by hand so the test never races the
    # background worker (it did, once, on a slow CI box)
    webdl.JOBS.clear()
    jid = "cleanupjob"
    job_dir = Path("/tmp/webdl_test") / jid
    job_dir.mkdir(parents=True, exist_ok=True)
    webdl.JOBS[jid] = {
        "created_at": 0, "state": "done", "stage": "done", "url": "", "mode": "video",
        "quality": "", "dir": str(job_dir), "percent": 100, "downloaded": 1, "total": 1,
        "title": "old", "speed": 0, "eta": 0, "finished_at": 0,
    }
    os.environ["WEBDL_TTL"] = "1"
    removed = webdl._cleanup_once()
    check("ttl cleanup removes old jobs", removed >= 1 and jid not in webdl.JOBS, str(removed))
    check("ttl cleanup removes the files too", not job_dir.exists(), str(job_dir))
    os.environ.pop("WEBDL_TTL", None)


main()

failed = 0
for ok, name, detail in results:
    if not ok:
        failed += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
print(f"\n{len(results) - failed}/{len(results)} passed")
sys.exit(1 if failed else 0)
