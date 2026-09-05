"""
user_stream_module.py — standalone module for user-account stream fallback.

Placed at bot/helper/user_stream_module.py (permanent via UPSTREAM_REPO).
Imported at startup by patched stream_server.py and wserver.py.

All bug fixes from Claude v3 + v4 reviews applied.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import time as _time
from asyncio import (
    FIRST_COMPLETED,
    Lock,
    ensure_future,
    sleep,
    wait,
    wait_for,
)
from collections import OrderedDict
from dataclasses import replace
from hashlib import sha256
from time import monotonic

from pyrogram import raw
from pyrogram.errors import (
    FileMigrate,
    FileReferenceExpired,
    FileReferenceInvalid,
    FloodPremiumWait,
    FloodWait,
)
from pyrogram.file_id import FileId

from bot import LOGGER, bot_loop
from bot.core.config_manager import Config
from bot.core.tg_client import TgClient
from bot.helper.telegram_helper.tg_stream import (
    FULL,
    NoClientAvailable,
    StreamAbort,
    StreamGone,
    plan_chunks,
    profile as _profile,
    purge_fid as _purge_fid,
)
from bot.helper.telegram_helper.tg_transfer import (
    HypertgTransfer,
    media_of,
)


def _debug(msg, *args):
    """Log at DEBUG level only if STREAM_DEBUG is enabled."""
    if getattr(Config, "STREAM_DEBUG", False):
        LOGGER.debug(msg, *args)


_FID_TTL = 1800
_FID_MAX = 512
_fid_cache: OrderedDict = OrderedDict()
_fid_locks: dict = {}


async def get_fid_user(chat_id, msg_id, force=False):
    """Cached file-id decoder using TgClient.user."""
    ci = -1
    key = (ci, chat_id, msg_id)

    if not force:
        hit = _fid_cache.get(key)
        if hit and monotonic() - hit[1] < _FID_TTL:
            _fid_cache.move_to_end(key)
            return hit[0]

    lk = _fid_locks.setdefault(key, Lock())
    async with lk:
        hit = _fid_cache.get(key)
        if hit and not force and monotonic() - hit[1] < _FID_TTL:
            return hit[0]

        client = TgClient.user
        if client is None:
            raise NoClientAvailable(
                "user account is not configured (USER_SESSION_STRING)"
            )

        uname = (
            getattr(getattr(client, "me", None), "username", None)
            or getattr(getattr(client, "me", None), "first_name", None)
            or "user"
        )

        msg = None
        for attempt in range(3):
            try:
                msg = await client.get_messages(chat_id, msg_id)
            except Exception as err:
                LOGGER.warning(
                    f"get_fid_user: (@{uname}) get_messages raised: {err}"
                )
                msg = None
            if msg is not None and not getattr(msg, "empty", False):
                break
            LOGGER.warning(
                f"get_fid_user: (@{uname}) attempt {attempt+1}/3 - msg is None or empty"
            )
            if attempt < 2:
                await sleep(2)

        if msg is None or getattr(msg, "empty", False):
            _fid_cache.pop(key, None)
            _fid_locks.pop(key, None)
            raise StreamGone(
                f"user: msg {msg_id} missing from {chat_id} after 3 attempts"
            )

        media = media_of(msg)
        if media is None:
            _fid_cache.pop(key, None)
            _fid_locks.pop(key, None)
            raise StreamGone(
                f"user: msg {msg_id} in {chat_id} has no streamable media"
            )
        fid = FileId.decode(media.file_id)
        fid.file_size = getattr(media, "file_size", 0)
        fid.mime_type = getattr(media, "mime_type", "") or ""
        fid.file_name = getattr(media, "file_name", "") or ""
        fid.unique_id = getattr(media, "file_unique_id", "") or ""

        _fid_cache[key] = (fid, monotonic())
        if len(_fid_cache) > _FID_MAX:
            old, _ = _fid_cache.popitem(last=False)
            _fid_locks.pop(old, None)

        _debug(
            f"get_fid_user: (@{uname}) success dc={fid.dc_id} size={fid.file_size}"
        )
        return fid


def purge_fid_user(chat_id, msg_id):
    """Evict user-account cache entries for a given (chat, msg)."""
    ci = -1
    key = (ci, chat_id, msg_id)
    _fid_cache.pop(key, None)
    _fid_locks.pop(key, None)


class UserStream:
    """Streams file bytes through the user account's MTProto session."""

    def __init__(self, chat_id, msg_id, prof, viewer=None):
        self.chat_id = chat_id
        self.msg_id = msg_id
        self.prof = prof
        self.viewer = viewer
        self.fid = None
        self.size = 0
        self.name = ""
        self.mime = ""
        self.unique_id = ""
        self._loc = None
        self._dc = None
        self.dead = False
        self._released = False

    async def open(self):
        if TgClient.user is None:
            raise NoClientAvailable(
                "user account is not configured (USER_SESSION_STRING)"
            )
        fid = await get_fid_user(self.chat_id, self.msg_id)
        self._loc = HypertgTransfer._location(fid)
        self._dc = fid.dc_id
        self.fid = fid
        self.size = int(getattr(fid, "file_size", 0) or 0)
        self.mime = getattr(fid, "mime_type", "") or ""
        self.name = getattr(fid, "file_name", "") or ""
        self.unique_id = getattr(fid, "unique_id", "") or ""
        if not self.size:
            raise StreamGone("user: media has no size")
        LOGGER.info(
            f"UserStream: opened {self.chat_id}/{self.msg_id} "
            f"size={self.size} dc={self._dc} mime={self.mime}"
        )
        return self

    async def _release(self):
        if self._released:
            return
        self._released = True

    async def _pull(self, off, lim):
        client = TgClient.user
        if client is None:
            raise StreamAbort("user: client became None mid-stream")
        refreshes = 0
        attempt = 0
        while True:
            if self.dead:
                return b""
            try:
                _debug(f"UserStream: GetFile offset={off} limit={lim} dc={self._dc}")
                r = await wait_for(
                    client.invoke(
                        raw.functions.upload.GetFile(
                            precise=True,
                            cdn_supported=self.prof.cdn,
                            location=self._loc,
                            offset=off,
                            limit=lim,
                        )
                    ),
                    timeout=self.prof.invoke_timeout + 10,
                )
                if isinstance(r, raw.types.upload.File):
                    _debug(f"UserStream: got {len(r.bytes)} bytes at offset {off}")
                    return r.bytes
                if isinstance(r, raw.types.upload.FileCdnRedirect):
                    self.prof = replace(self.prof, cdn=False)
                    continue
                raise StreamAbort(f"user: unexpected GetFile response {type(r)}")

            except (FileReferenceExpired, FileReferenceInvalid):
                if refreshes >= 2:
                    raise StreamAbort("user: file reference kept expiring") from None
                refreshes += 1
                LOGGER.warning(f"UserStream: file reference expired ({refreshes}/2)")
                fid = await get_fid_user(self.chat_id, self.msg_id, force=True)
                self._dc = fid.dc_id
                self._loc = HypertgTransfer._location(fid)

            except FileMigrate as e:
                LOGGER.info(f"UserStream: file migrate to DC {e.value}")
                self._dc = e.value
                fid = await get_fid_user(self.chat_id, self.msg_id, force=True)
                self._loc = HypertgTransfer._location(fid)

            except (FloodWait, FloodPremiumWait) as e:
                if self.dead:
                    raise StreamAbort("user: stream closed") from None
                if e.value > 30:
                    raise StreamAbort(f"user: flood wait {e.value}s") from None
                LOGGER.warning(f"UserStream: flood wait {e.value}s, sleeping...")
                await sleep(e.value + 1)

            except (ConnectionError, OSError, TimeoutError) as e:
                attempt += 1
                LOGGER.warning(
                    f"UserStream: connection error (attempt {attempt}/"
                    f"{self.prof.retries+1}): {e}"
                )
                if attempt > self.prof.retries:
                    raise StreamAbort(
                        f"user: unreachable after {attempt} attempts: {e}"
                    ) from None
                await sleep(1)

            except Exception as e:
                LOGGER.error(
                    f"UserStream: unexpected error at offset {off}: "
                    f"{type(e).__name__}: {e}"
                )
                raise StreamAbort(f"user: {type(e).__name__}: {e}") from None

    async def iter_range(self, start, end_incl):
        end_ex = end_incl + 1
        plan = plan_chunks(start, end_ex, self.prof)
        window = min(self.prof.window, 2)
        inflight = {}
        ready = {}
        nxt = launch = sent = 0

        try:
            while nxt < len(plan):
                while (len(inflight) + len(ready)) < window and launch < len(plan):
                    off, lim = plan[launch]
                    inflight[ensure_future(self._pull(off, lim))] = launch
                    launch += 1

                while nxt not in ready:
                    if not inflight:
                        raise StreamAbort("user: pipeline stalled")
                    done, _ = await wait(set(inflight), return_when=FIRST_COMPLETED)
                    for f in done:
                        ready[inflight.pop(f)] = f.result()

                data = ready.pop(nxt)
                off, lim = plan[nxt]
                nxt += 1

                lo = max(start, off) - off
                hi = min(end_ex, off + lim) - off
                if len(data) < hi:
                    LOGGER.error(f"UserStream short read at {off}: got {len(data)} want {hi}")
                    hi = len(data)
                    if hi <= lo:
                        break
                piece = data if (lo == 0 and hi == len(data)) else data[lo:hi]
                del data
                if piece:
                    sent += len(piece)
                    yield piece
                if hi < min(lim, end_ex - off):
                    break

            if sent != end_ex - start:
                LOGGER.error(f"UserStream length mismatch sent={sent} want={end_ex - start}")
        finally:
            self.dead = True
            if inflight:
                for fut in inflight:
                    if not fut.done():
                        fut.cancel()
            ready.clear()
            await self._release()


async def open_stream_user(chat_id, msg_id, kind, viewer=None):
    return await UserStream(chat_id, msg_id, _profile(kind), viewer=viewer).open()


async def probe_user(chat_id, msg_id):
    if TgClient.user is None:
        raise NoClientAvailable("user account is not configured (USER_SESSION_STRING)")
    fid = await get_fid_user(chat_id, msg_id)
    return {
        "name": getattr(fid, "file_name", "") or "",
        "size": int(getattr(fid, "file_size", 0) or 0),
        "mime": getattr(fid, "mime_type", "") or "",
        "unique_id": getattr(fid, "unique_id", "") or "",
    }


# ─── AUTH LAYER ───────────────────────────────────────────────────

_AUTH_TTL = 24 * 3600


def _get_nonce(password: str) -> str:
    """Stable nonce derived from STREAM_PASS — survives restarts."""
    return sha256(f"wzml-nonce:{password}".encode()).hexdigest()[:16]


def _get_stream_pass() -> str:
    return getattr(Config, "STREAM_PASS", "") or ""


def _sign_token(password: str) -> str:
    ts = int(_time.time())
    nonce = _get_nonce(password)
    msg = f"{ts}:{nonce}".encode()
    sig = hmac.new(password.encode(), msg, sha256).hexdigest()
    return f"{ts}.{sig}"


def _verify_token(token: str, password: str) -> bool:
    if not token or not password:
        return False
    try:
        ts_str, sig = token.split(".", 1)
        ts = int(ts_str)
    except (ValueError, AttributeError):
        return False
    if _time.time() - ts > _AUTH_TTL:
        return False
    nonce = _get_nonce(password)
    msg = f"{ts}:{nonce}".encode()
    expected = hmac.new(password.encode(), msg, sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def check_auth(request) -> bool:
    """Check if request has valid auth for user-account streaming."""
    password = _get_stream_pass()
    if not password:
        return True
    token = request.query.get("auth")
    return _verify_token(token, password)


# ─── HEALTH CHECK ─────────────────────────────────────────────────

_health_task = None
_last_result = None
_health_session = None


async def _get_session():
    global _health_session
    if _health_session is None or _health_session.closed:
        from aiohttp import ClientSession
        _health_session = ClientSession()
    return _health_session


def _aiohttp_timeout(seconds):
    from aiohttp import ClientTimeout
    return ClientTimeout(total=seconds)


async def do_health_check():
    global _last_result
    worker_url = getattr(Config, "BASE_URL", "") or ""
    if not worker_url or "trycloudflare" in worker_url:
        LOGGER.warning("Health check: BASE_URL not a stable Worker URL, skipping")
        return None

    url = f"{worker_url.rstrip('/')}/health"
    try:
        session = await _get_session()
        async with session.get(url, timeout=_aiohttp_timeout(15)) as resp:
            body = await resp.text()
            try:
                data = json.loads(body)
            except Exception:
                data = {}
            _last_result = {"timestamp": int(_time.time()), "status": resp.status, "data": data}
            tunnel_ok = data.get("tunnel_connected", False)
            bot_ok = data.get("bot_responding", False)
            latency = data.get("latency_ms", "?")
            if tunnel_ok and bot_ok:
                LOGGER.info(f"Health check OK: latency {latency}ms")
            else:
                LOGGER.warning(f"Health check DEGRADED: tunnel={tunnel_ok} bot={bot_ok}")
                await _send_ntfy_alert(f"Stream health degraded: tunnel={tunnel_ok} bot={bot_ok}")
            return _last_result
    except asyncio.TimeoutError:
        LOGGER.error("Health check: timed out (15s)")
        _last_result = {"timestamp": int(_time.time()), "status": 0, "data": {}, "error": "timeout"}
    except Exception as e:
        LOGGER.error(f"Health check: failed — {type(e).__name__}: {e}")
        _last_result = {"timestamp": int(_time.time()), "status": 0, "data": {}, "error": str(e)}
    await _send_ntfy_alert("Stream health check failed — chain may be down")
    return _last_result


async def _send_ntfy_alert(message: str):
    topic = getattr(Config, "NTFY_TOPIC", "") or "JAI_HO"
    try:
        session = await _get_session()
        await session.post(
            f"https://ntfy.sh/{topic}",
            headers={"Title": "WZML-X Stream Alert"},
            data=message,
            timeout=_aiohttp_timeout(10),
        )
    except Exception:
        pass


async def _health_loop():
    interval = getattr(Config, "STREAM_HEALTH_INTERVAL", 1800) or 1800
    if interval < 300:
        interval = 300
    LOGGER.info(f"Health check loop started (interval={interval}s)")
    while True:
        try:
            await do_health_check()
        except Exception as e:
            LOGGER.error(f"Health loop error: {e}")
        await asyncio.sleep(interval)


def start_health_check():
    global _health_task
    if _health_task is not None and not _health_task.done():
        return
    _health_task = bot_loop.create_task(_health_loop())


def stop_health_check():
    global _health_task, _health_session
    if _health_task is not None and not _health_task.done():
        _health_task.cancel()
    _health_task = None
    if _health_session is not None and not _health_session.closed:
        try:
            bot_loop.create_task(_health_session.close())
        except Exception:
            pass
    _health_session = None


def get_last_result():
    return _last_result
