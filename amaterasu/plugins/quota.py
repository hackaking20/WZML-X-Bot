"""Per-user daily bandwidth quota and a small download library.

Ported from the r1_core module in vot1122/Kaggle-auto, which existed because
that bot runs on a free Kaggle notebook with ~20 GB of disk: without a quota
one user can fill the box and take the bot down for everyone.

That risk applies here too — a GitHub Actions runner has less disk than a
VPS — so the quota is enforced *before* a task starts, and usage is recorded
when the download completes.

How it hooks in without patching any source files: the plugin wraps three
existing methods at load time and unwraps them on unload.

    Mirror.new_event / YtDlp.new_event   refuse the task when over quota
    TaskListener.on_download_complete    record the bytes that landed
    TaskListener.on_upload_complete      record the finished file for /find

Every hook is wrapped in try/except: a broken database or a changed upstream
signature must never stop a download from working.

Config (env or config.py)
    DAILY_QUOTA_GB    default 15, 0 disables enforcement entirely
    QUOTA_ENFORCE     default true
    LIBRARY_MAX       default 20000 entries, oldest pruned

Commands
    /usage              today's usage for you
    /quota <id> <gb>    set a per-user limit (sudo)
    /quotareset <id>    zero today's usage (sudo)
    /find <text>        search the download library
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from pyrogram import Client
from pyrogram.types import Message

from bot import LOGGER
from bot.core.plugin_manager import PluginBase, PluginInfo
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.telegram_helper.message_utils import send_message

_GB = 1024 ** 3
_PATCHED = False
_ORIGINALS = []  # (cls, attr, original), unwound LIFO


def _log(msg: str) -> None:
    try:
        LOGGER.info(f"[quota] {msg}")
    except Exception:
        print(f"[quota] {msg}")


# ─────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────


def _default_gb() -> float:
    try:
        return max(0.0, float(os.environ.get("DAILY_QUOTA_GB", "") or 15))
    except (TypeError, ValueError):
        return 15.0


def _enforcing() -> bool:
    raw = str(os.environ.get("QUOTA_ENFORCE", "true")).strip().lower()
    return raw in {"1", "true", "yes", "on"} and _default_gb() > 0


_SETTINGS = {"at": 0.0, "gb": None}
_SETTINGS_TTL = 60.0


async def default_gb() -> float:
    """The global cap: whatever /botcap last stored, else the env default."""
    now = time.time()
    if _SETTINGS["gb"] is not None and now - _SETTINGS["at"] < _SETTINGS_TTL:
        return float(_SETTINGS["gb"])
    value = _default_gb()
    col = _quota_col()
    if col is not None:
        try:
            doc = await col.find_one({"_id": "settings"})
            if doc and doc.get("default_gb") is not None:
                value = float(doc["default_gb"])
        except Exception as error:
            _log(f"settings read failed: {error}")
    _SETTINGS.update(at=now, gb=value)
    return value


async def set_default_gb(gb: float) -> None:
    col = _quota_col()
    if col is not None:
        try:
            await col.update_one(
                {"_id": "settings"}, {"$set": {"default_gb": float(gb)}}, upsert=True
            )
        except Exception as error:
            _log(f"settings write failed: {error}")
    _SETTINGS.update(at=time.time(), gb=float(gb))


async def enforcing() -> bool:
    raw = str(os.environ.get("QUOTA_ENFORCE", "true")).strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return False
    return (await default_gb()) > 0


def _library_max() -> int:
    try:
        return max(100, int(os.environ.get("LIBRARY_MAX", "") or 20000))
    except (TypeError, ValueError):
        return 20000


def _today() -> str:
    try:
        offset = float(os.environ.get("QUOTA_TZ_OFFSET", "5.5"))
    except (TypeError, ValueError):
        offset = 5.5
    return datetime.now(timezone(timedelta(hours=offset))).strftime("%Y-%m-%d")


def _human(num: float) -> str:
    for unit, size in (("GB", _GB), ("MB", 1024 ** 2), ("KB", 1024)):
        if num >= size:
            return f"{num / size:.2f} {unit}"
    return f"{int(num)} B"


# ─────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────


def _db():
    """The bot's own motor database, or None when Mongo is unavailable."""
    try:
        from bot.helper.ext_utils.db_handler import database

        if database.db is None:
            return None
        return database.db
    except Exception:
        return None


def _part() -> str:
    try:
        from bot.core.tg_client import TgClient

        return str(TgClient.PARTITION or "default")
    except Exception:
        return "default"


def _quota_col():
    db = _db()
    return None if db is None else db["quota"][_part()]


def _library_col():
    db = _db()
    return None if db is None else db["library"][_part()]


async def usage_of(user_id: int) -> int:
    col = _quota_col()
    if col is None:
        return 0
    try:
        doc = await col.find_one({"_id": int(user_id)})
    except Exception as error:
        _log(f"usage read failed: {error}")
        return 0
    if not doc or doc.get("day") != _today():
        return 0
    return int(doc.get("used") or 0)


async def limit_of(user_id: int) -> float:
    """Per-user override in GB, else the global default."""
    col = _quota_col()
    if col is None:
        return await default_gb()
    try:
        doc = await col.find_one({"_id": int(user_id)})
    except Exception:
        return await default_gb()
    if doc and doc.get("limit_gb") is not None:
        try:
            return float(doc["limit_gb"])
        except (TypeError, ValueError):
            pass
    return await default_gb()


async def add_usage(user_id: int, num_bytes: int) -> None:
    col = _quota_col()
    if col is None or num_bytes <= 0:
        return
    day = _today()
    try:
        doc = await col.find_one({"_id": int(user_id)})
        if not doc or doc.get("day") != day:
            await col.update_one(
                {"_id": int(user_id)},
                {"$set": {"day": day, "used": int(num_bytes)}},
                upsert=True,
            )
        else:
            await col.update_one(
                {"_id": int(user_id)}, {"$inc": {"used": int(num_bytes)}}
            )
    except Exception as error:
        _log(f"usage write failed: {error}")


async def set_limit(user_id: int, gb: Optional[float]) -> None:
    col = _quota_col()
    if col is None:
        return
    await col.update_one(
        {"_id": int(user_id)}, {"$set": {"limit_gb": gb}}, upsert=True
    )


async def reset_usage(user_id: int) -> None:
    col = _quota_col()
    if col is None:
        return
    await col.update_one(
        {"_id": int(user_id)}, {"$set": {"day": _today(), "used": 0}}, upsert=True
    )


async def remaining(user_id: int) -> float:
    """Bytes left today, or -1 when unlimited."""
    if not await enforcing():
        return -1
    limit_gb = await limit_of(user_id)
    if limit_gb <= 0:
        return -1
    used = await usage_of(user_id)
    return max(0, int(limit_gb * _GB) - used)


# ─────────────────────────────────────────────────────────────────────────
# Library
# ─────────────────────────────────────────────────────────────────────────


async def record_file(user_id: int, name: str, size: int, link: str = "") -> None:
    col = _library_col()
    if col is None or not name:
        return
    try:
        await col.insert_one(
            {
                "user_id": int(user_id),
                "name": str(name)[:200],
                "size": int(size or 0),
                "link": str(link or "")[:300],
                "at": time.time(),
            }
        )
        count = await col.count_documents({})
        if count > _library_max():
            overflow = count - _library_max()
            oldest = col.find({}, {"_id": 1}).sort("at", 1).limit(overflow)
            ids = [doc["_id"] async for doc in oldest]
            if ids:
                await col.delete_many({"_id": {"$in": ids}})
    except Exception as error:
        _log(f"library write failed: {error}")


async def search_files(user_id: int, query: str, limit: int = 10):
    col = _library_col()
    if col is None:
        return []
    pattern = re.escape(query)
    try:
        cursor = (
            col.find(
                {
                    "user_id": int(user_id),
                    "name": {"$regex": pattern, "$options": "i"},
                }
            )
            .sort("at", -1)
            .limit(limit)
        )
        return [doc async for doc in cursor]
    except Exception as error:
        _log(f"library search failed: {error}")
        return []


# ─────────────────────────────────────────────────────────────────────────
# Hooks
# ─────────────────────────────────────────────────────────────────────────


async def _over_quota_notice(listener) -> bool:
    """True when this task must be refused."""
    if not await enforcing():
        return False
    try:
        left = await remaining(listener.user_id)
    except Exception as error:
        _log(f"quota check failed (allowing task): {error}")
        return False
    if left < 0:
        return False
    if left > 0:
        return False
    try:
        limit_gb = await limit_of(listener.user_id)
        used = await usage_of(listener.user_id)
        await send_message(
            listener.message,
            "<b>✦ DAILY QUOTA REACHED</b>\n\n"
            f"╭─ <b>Used</b> : <code>{_human(used)}</code>\n"
            f"├─ <b>Limit</b> : <code>{limit_gb:.1f} GB</code>\n"
            "╰─ <i>Resets at midnight IST. Ask the owner for a raise.</i>",
        )
    except Exception:
        pass
    return True


def _install_hooks() -> bool:
    global _PATCHED
    if _PATCHED:
        return True
    try:
        # bot.modules must be imported first: task_listener imports from it,
        # and going the other way round trips a circular import that leaves
        # TaskListener half-built.
        import bot.modules  # noqa: F401

        from bot.helper.listeners.task_listener import TaskListener
        from bot.modules.mirror_leech import Mirror
        from bot.modules.ytdlp import YtDlp

        # ── refuse before the task starts ───────────────────────────────
        def wrap_new_event(cls):
            original = cls.new_event
            _ORIGINALS.append((cls, "new_event", original))

            async def new_event(self, *args, **kwargs):
                try:
                    if await _over_quota_notice(self):
                        return None
                except Exception as error:
                    _log(f"quota gate error (allowing): {error}")
                return await original(self, *args, **kwargs)

            cls.new_event = new_event

        wrap_new_event(Mirror)
        wrap_new_event(YtDlp)

        # ── record bytes after the download lands ───────────────────────
        original_complete = TaskListener.on_download_complete
        _ORIGINALS.append((TaskListener, "on_download_complete", original_complete))

        async def on_download_complete(self, *args, **kwargs):
            result = await original_complete(self, *args, **kwargs)
            try:
                size = int(getattr(self, "size", 0) or 0)
                if size:
                    await add_usage(self.user_id, size)
            except Exception as error:
                _log(f"usage record failed: {error}")
            return result

        TaskListener.on_download_complete = on_download_complete

        # ── record the finished file for /find ──────────────────────────
        original_upload = TaskListener.on_upload_complete
        _ORIGINALS.append((TaskListener, "on_upload_complete", original_upload))

        async def on_upload_complete(self, *args, **kwargs):
            result = await original_upload(self, *args, **kwargs)
            try:
                link = ""
                try:
                    link = getattr(self.message, "link", "") or ""
                except Exception:
                    link = ""
                await record_file(
                    self.user_id,
                    getattr(self, "name", "") or "",
                    int(getattr(self, "size", 0) or 0),
                    link,
                )
            except Exception as error:
                _log(f"library record failed: {error}")
            return result

        TaskListener.on_upload_complete = on_upload_complete

        _PATCHED = True
        _log("hooks installed (Mirror, YtDlp, TaskListener)")
        return True
    except Exception as error:
        _log(f"hook installation failed: {error}")
        return False


async def _retry_install(attempts: int = 12, delay: float = 10.0) -> None:
    """Plugins can load while bot.helper.listeners.task_listener is still
    being imported, in which case the first install attempt fails on a
    circular import. Keep trying rather than silently leaving quota
    enforcement switched off."""
    for attempt in range(1, attempts + 1):
        await asyncio.sleep(delay)
        if _PATCHED:
            return
        if _install_hooks():
            _log(f"hooks installed on retry {attempt}")
            return
    _log("gave up installing hooks — quota enforcement is OFF")


def _remove_hooks() -> bool:
    """Unwind the patches newest-first, so a class wrapped twice ends up
    with its genuine original rather than the other wrapper."""
    global _PATCHED
    while _ORIGINALS:
        cls, attr, original = _ORIGINALS.pop()
        try:
            setattr(cls, attr, original)
        except Exception as error:
            _log(f"could not restore {cls.__name__}.{attr}: {error}")
    _PATCHED = False
    return True


# ─────────────────────────────────────────────────────────────────────────
# Plugin
# ─────────────────────────────────────────────────────────────────────────


class QuotaPlugin(PluginBase):
    PLUGIN_INFO = PluginInfo(
        name="quota",
        version="1.0.0",
        author="Amaterasu (ported from WZFIX / Kaggle-auto)",
        description="Per-user daily bandwidth quota plus a download library",
        enabled=True,
        handlers=[],
        commands=[
            "usage", "quota", "quotareset", "find",
            "qusers", "addcap", "botcap", "dbstats", "dbclean",
        ],
        dependencies=[],
    )

    async def on_load(self) -> bool:
        from pyrogram.filters import regex
        from pyrogram.handlers import CallbackQueryHandler

        self.PLUGIN_INFO.handlers.append(
            CallbackQueryHandler(admin_callback, filters=regex(r"^qadm:"))
        )
        installed = _install_hooks()
        if not installed:
            _log("hook install failed on first try; retrying in the background")
            try:
                asyncio.create_task(_retry_install())
            except RuntimeError:
                pass
        _log(
            f"loaded — hooks={'on' if installed else 'pending'}, "
            f"daily limit {_default_gb():.0f} GB, "
            f"enforcing={_enforcing()}, partition={_part()}"
        )
        return True

    async def on_unload(self) -> bool:
        _remove_hooks()
        _log("unloaded, hooks removed")
        return True


# ─────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────


def _sudo(message: Message) -> bool:
    try:
        from bot.helper.telegram_helper.filters import CustomFilters
        from bot.core.config_manager import Config

        user_id = getattr(message.from_user, "id", 0)
        if user_id == Config.OWNER_ID:
            return True
        return str(user_id) in str(Config.SUDO_USERS or "").replace(" ", "").split(",")
    except Exception:
        return False


@new_task
async def usage_command(client: Client, message: Message):
    user_id = getattr(message.from_user, "id", 0) or getattr(message, "user_id", 0)
    used = await usage_of(user_id)
    limit_gb = await limit_of(user_id)
    if not await enforcing():
        await send_message(
            message,
            f"<b>✦ USAGE TODAY</b>\n\n╰─ <code>{_human(used)}</code> "
            "<i>(quota disabled)</i>",
        )
        return
    left = max(0, int(limit_gb * _GB) - used)
    bar_total = max(int(limit_gb * _GB), 1)
    filled = int(12 * min(used, bar_total) / bar_total)
    await send_message(
        message,
        "<b>✦ USAGE TODAY</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"├ <b>Used</b>  : <code>{_human(used)}</code>\n"
        f"├ <b>Limit</b> : <code>{limit_gb:.1f} GB</code>\n"
        f"├ <b>Left</b>  : <code>{_human(left)}</code>\n"
        f"├ {'▰' * filled}{'▱' * (12 - filled)}\n"
        f"╰ <i>resets at midnight IST ({_today()})</i>",
    )


@new_task
async def quota_command(client: Client, message: Message):
    if not _sudo(message):
        await send_message(message, "<b>⚑ Owner only.</b>")
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await send_message(
            message,
            "<b>✦ QUOTA</b>\n\n"
            "<code>/quota &lt;user_id&gt; &lt;gb&gt;</code> — set a limit\n"
            "<code>/quota &lt;user_id&gt; 0</code> — unlimited\n\n"
            f"<i>Default for everyone: {_default_gb():.0f} GB/day</i>",
        )
        return
    try:
        target = int(parts[1])
        gb = float(parts[2])
    except ValueError:
        await send_message(message, "<b>⚑ Numbers only:</b> <code>/quota 123456789 25</code>")
        return
    await set_limit(target, gb if gb > 0 else None)
    used = await usage_of(target)
    await send_message(
        message,
        f"<b>✦ QUOTA SET</b>\n\n"
        f"├ <b>User</b>  : <code>{target}</code>\n"
        f"├ <b>Limit</b> : <code>{'unlimited' if gb <= 0 else f'{gb:.1f} GB'}</code>\n"
        f"╰ <b>Used</b>  : <code>{_human(used)}</code>",
    )


@new_task
async def quotareset_command(client: Client, message: Message):
    if not _sudo(message):
        await send_message(message, "<b>⚑ Owner only.</b>")
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await send_message(message, "<b>Usage:</b> <code>/quotareset &lt;user_id&gt;</code>")
        return
    try:
        target = int(parts[1])
    except ValueError:
        await send_message(message, "<b>⚑ That isn't a user id.</b>")
        return
    await reset_usage(target)
    await send_message(
        message, f"<b>✦ Reset</b> — <code>{target}</code> is back to 0 today."
    )


@new_task
async def find_command(client: Client, message: Message):
    parts = (message.text or "").split(None, 1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if not query:
        await send_message(
            message,
            "<b>✦ LIBRARY</b>\n\n<code>/find &lt;text&gt;</code> "
            "— searches files you have already downloaded.",
        )
        return
    user_id = getattr(message.from_user, "id", 0)
    found = await search_files(user_id, query)
    if not found:
        await send_message(message, f"<b>⚑ Nothing matching</b> <i>{query[:50]}</i>")
        return
    lines = [f"<b>✦ LIBRARY — {len(found)} match(es)</b>", ""]
    for doc in found:
        name = str(doc.get("name") or "")[:60]
        size = _human(int(doc.get("size") or 0))
        link = doc.get("link") or ""
        if link:
            lines.append(f'◦ <a href="{link}">{name}</a> — <code>{size}</code>')
        else:
            lines.append(f"◦ {name} — <code>{size}</code>")
    await send_message(message, "\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────
# Owner tooling (ported from the WZFIX admin module)
# ─────────────────────────────────────────────────────────────────────────


async def registry(limit: int = 20):
    """Everyone with a quota document today, busiest first."""
    col = _quota_col()
    if col is None:
        return []
    day = _today()
    try:
        cursor = col.find({}).sort("used", -1).limit(limit)
        docs = [doc async for doc in cursor]
    except Exception as error:
        _log(f"registry read failed: {error}")
        return []
    rows = []
    for doc in docs:
        if not isinstance(doc.get("_id"), int):
            continue  # the settings document
        used = int(doc.get("used") or 0) if doc.get("day") == day else 0
        rows.append(
            {
                "user_id": doc["_id"],
                "used": used,
                "limit_gb": doc.get("limit_gb"),
            }
        )
    rows.sort(key=lambda row: row["used"], reverse=True)
    return rows


async def collection_stats():
    """(name, document count) for every collection in the bot's database."""
    db = _db()
    if db is None:
        return []
    try:
        names = await db.list_collection_names()
    except Exception as error:
        _log(f"collection list failed: {error}")
        return []
    stats = []
    for name in sorted(names):
        try:
            count = await db[name].count_documents({})
        except Exception:
            count = -1
        stats.append((name, count))
    return stats


async def purge_older_than(days: int) -> dict:
    """Delete library entries and stale quota rows older than N days.

    Only ever touches the two collections this plugin owns — never a bot
    collection — and never drops a collection.
    """
    cutoff = time.time() - days * 86400
    removed = {"library": 0, "quota": 0}
    lib = _library_col()
    if lib is not None:
        try:
            result = await lib.delete_many({"at": {"$lt": cutoff}})
            removed["library"] = int(getattr(result, "deleted_count", 0) or 0)
        except Exception as error:
            _log(f"library purge failed: {error}")
    col = _quota_col()
    if col is not None:
        day_cutoff = (
            datetime.now(timezone(timedelta(hours=5.5))) - timedelta(days=days)
        ).strftime("%Y-%m-%d")
        try:
            result = await col.delete_many(
                {"day": {"$lt": day_cutoff}, "_id": {"$ne": "settings"}}
            )
            removed["quota"] = int(getattr(result, "deleted_count", 0) or 0)
        except Exception as error:
            _log(f"quota purge failed: {error}")
    return removed


@new_task
async def qusers_command(client: Client, message: Message):
    if not _sudo(message):
        await send_message(message, "<b>⚑ Owner only.</b>")
        return
    rows = await registry(20)
    if not rows:
        await send_message(message, "<b>✦ No quota records yet.</b>")
        return
    default = await default_gb()
    lines = [
        "<b>✦ USERS TODAY</b>",
        f"<i>global cap: {default:.0f} GB · resets at midnight IST</i>",
        "",
    ]
    for row in rows[:15]:
        cap = row["limit_gb"] if row["limit_gb"] is not None else default
        lines.append(
            f"◦ <code>{row['user_id']}</code> — "
            f"<code>{_human(row['used'])}</code> / {cap:.0f} GB"
        )
    if len(rows) > 15:
        lines.append(f"<i>… and {len(rows) - 15} more</i>")
    await send_message(message, "\n".join(lines))


@new_task
async def addcap_command(client: Client, message: Message):
    if not _sudo(message):
        await send_message(message, "<b>⚑ Owner only.</b>")
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await send_message(
            message,
            "<b>Usage:</b> <code>/addcap &lt;user_id&gt; &lt;gb&gt;</code>\n"
            "<i>Raises that user's cap by GB (negative lowers it).</i>",
        )
        return
    try:
        target = int(parts[1])
        delta = float(parts[2])
    except ValueError:
        await send_message(message, "<b>⚑ Numbers only.</b>")
        return
    current = await limit_of(target)
    new_limit = max(0.0, current + delta)
    await set_limit(target, new_limit if new_limit > 0 else None)
    await send_message(
        message,
        f"<b>✦ Cap adjusted</b>\n\n"
        f"├ <b>User</b> : <code>{target}</code>\n"
        f"├ <b>Was</b>  : <code>{current:.1f} GB</code>\n"
        f"╰ <b>Now</b>  : <code>{new_limit:.1f} GB</code>",
    )


@new_task
async def botcap_command(client: Client, message: Message):
    if not _sudo(message):
        await send_message(message, "<b>⚑ Owner only.</b>")
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await send_message(
            message,
            f"<b>✦ Global cap:</b> <code>{await default_gb():.0f} GB</code>\n\n"
            "<code>/botcap &lt;gb&gt;</code> — change it (<code>0</code> disables the quota)",
        )
        return
    try:
        gb = max(0.0, float(parts[1]))
    except ValueError:
        await send_message(message, "<b>⚑ That isn't a number.</b>")
        return
    await set_default_gb(gb)
    await send_message(
        message,
        f"<b>✦ Global cap set</b> to <code>{gb:.0f} GB</code>"
        + (" <i>(quota disabled)</i>" if gb <= 0 else ""),
    )


@new_task
async def dbstats_command(client: Client, message: Message):
    if not _sudo(message):
        await send_message(message, "<b>⚑ Owner only.</b>")
        return
    stats = await collection_stats()
    if not stats:
        await send_message(message, "<b>⚑ No database configured.</b>")
        return
    total = sum(count for _, count in stats if count > 0)
    lines = ["<b>✦ DATABASE</b>", f"<i>partition {_part()}</i>", ""]
    for name, count in stats[:25]:
        lines.append(f"◦ <code>{name}</code> — {count} doc(s)")
    if len(stats) > 25:
        lines.append(f"<i>… and {len(stats) - 25} more collections</i>")
    lines.append("")
    lines.append(f"<b>Total:</b> <code>{total}</code> documents")
    await send_message(message, "\n".join(lines))


@new_task
async def dbclean_command(client: Client, message: Message):
    if not _sudo(message):
        await send_message(message, "<b>⚑ Owner only.</b>")
        return
    parts = (message.text or "").split()
    days = 30
    if len(parts) > 1:
        try:
            days = max(1, min(3650, int(parts[1])))
        except ValueError:
            await send_message(message, "<b>⚑ Days must be a number.</b>")
            return
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    await send_message(
        message,
        f"<b>✦ PURGE</b>\n\n"
        f"Deletes <b>library</b> entries and stale <b>quota</b> rows older "
        f"than <code>{days}</code> day(s).\n"
        "<i>No bot collection is touched and nothing is dropped.</i>",
        buttons=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"🗑 Delete older than {days}d", callback_data=f"qadm:clean:{days}"
                    )
                ],
                [InlineKeyboardButton("✖ Cancel", callback_data="qadm:cancel")],
            ]
        ),
    )


async def admin_callback(client: Client, query):
    data = (query.data or "").split(":")
    if len(data) < 2:
        await query.answer()
        return
    if data[1] == "cancel":
        await query.answer("Cancelled")
        try:
            await query.message.delete()
        except Exception:
            pass
        return
    if data[1] == "clean":
        try:
            days = int(data[2]) if len(data) > 2 else 30
        except ValueError:
            days = 30
        removed = await purge_older_than(days)
        await query.answer("Purged")
        await query.message.edit_text(
            f"<b>✦ Purged</b>\n\n"
            f"├ library : <code>{removed['library']}</code> removed\n"
            f"╰ quota   : <code>{removed['quota']}</code> removed",
        )
        return
    await query.answer()
