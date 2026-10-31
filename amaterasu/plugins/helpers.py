"""Helper-bot connection governor.

Amaterasu starts every helper bot in HELPER_TOKENS at boot and keeps them
connected for the life of the process. On a shared runner that means one
long-lived Telegram connection per helper, all day, whether or not anything
is being uploaded — which is both wasteful and, on a free CI runner, a lot of
persistent sessions from a single IP.

This plugin inverts that: helpers stay **down** by default, are brought up
when a task actually starts, and are dropped again after a few idle minutes.

    /helpers            status, with buttons to raise, drop or toggle auto
    HELPER_AUTO         "1" (default) manages connections automatically
    HELPER_IDLE_MINUTES minutes with no task before helpers are dropped (10)

Everything is best-effort: if the bot core changes shape, the plugin logs and
stays out of the way rather than breaking uploads.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List

from bot import LOGGER
from bot.core.plugin_manager import PluginBase, PluginInfo

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

_state = {
    "auto": True,
    "up": False,
    "started_at": 0.0,
    "last_activity": time.time(),
    "raised": 0,
    "dropped": 0,
    "error": "",
}
_originals: List[tuple] = []
_patched = False
_loop_task = None


# ─────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────


def _auto_default() -> bool:
    return str(os.environ.get("HELPER_AUTO", "1")).strip().lower() in {"1", "true", "yes", "on"}


def _idle_minutes() -> int:
    try:
        return max(1, min(720, int(os.environ.get("HELPER_IDLE_MINUTES", "10"))))
    except (TypeError, ValueError):
        return 10


def _tokens() -> List[str]:
    try:
        from bot.core.config_manager import Config

        return list(Config.helper_bot_tokens() or [])
    except Exception:
        return []


def _tg():
    from bot.core.tg_client import TgClient

    return TgClient


def _active_tasks() -> int:
    try:
        from bot import task_dict

        return len(task_dict)
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────
# Connection control
# ─────────────────────────────────────────────────────────────────────────


async def stop_all(reason: str = "") -> int:
    """Disconnect every helper bot. Returns how many were closed."""
    TgClient = _tg()
    closed = 0
    for no, client in list(getattr(TgClient, "helper_bots", {}).items()):
        try:
            await client.stop()
            closed += 1
        except Exception as error:
            LOGGER.debug(f"[helpers] stop {no} failed: {error}")
        finally:
            TgClient.helper_bots.pop(no, None)
            TgClient.helper_loads.pop(no, None)
    for token in list(getattr(TgClient, "helper_bot_clients", {}).keys()):
        TgClient.helper_bot_clients.pop(token, None)
    _state["up"] = False
    _state["started_at"] = 0.0
    if closed:
        _state["dropped"] += 1
        LOGGER.info(f"[helpers] dropped {closed} helper connection(s){' — ' + reason if reason else ''}")
    return closed


async def start_all() -> int:
    """Connect the configured helpers. Returns how many are up afterwards."""
    TgClient = _tg()
    tokens = _tokens()
    if not tokens:
        _state["up"] = False
        return 0
    existing = getattr(TgClient, "helper_bots", {})
    started = 0
    for no, token in enumerate(tokens, start=1):
        if no in existing:
            started += 1
            continue
        try:
            await TgClient.start_hclient(no, token)
        except Exception as error:
            LOGGER.warning(f"[helpers] start {no} failed: {error}")
        if no in getattr(TgClient, "helper_bots", {}):
            started += 1
    _state["up"] = started > 0
    _state["started_at"] = time.time() if started else 0.0
    if started:
        _state["raised"] += 1
        LOGGER.info(f"[helpers] raised {started} helper connection(s)")
    return started


async def ensure_up() -> int:
    if not _state["auto"]:
        return 0
    if _state["up"]:
        _state["last_activity"] = time.time()
        return len(_tokens())
    return await start_all()


# ─────────────────────────────────────────────────────────────────────────
# Hooks: raise helpers when a task begins
# ─────────────────────────────────────────────────────────────────────────


def _wrap_new_event(cls, label: str) -> None:
    original = getattr(cls, "new_event", None)
    if original is None or getattr(original, "_helpers_wrapped", False):
        return

    async def wrapper(self, *args, **kwargs):
        _state["last_activity"] = time.time()
        try:
            await ensure_up()
        except Exception as error:
            LOGGER.debug(f"[helpers] raise before {label} failed: {error}")
        return await original(self, *args, **kwargs)

    wrapper._helpers_wrapped = True
    setattr(cls, "new_event", wrapper)
    _originals.append((cls, original))


def install_hooks() -> bool:
    global _patched
    if _patched:
        return True
    try:
        import bot.modules  # noqa: F401  (upstream import cycle)
        from bot.modules.mirror_leech import Mirror
        from bot.modules.ytdlp import YtDlp

        _wrap_new_event(Mirror, "mirror")
        _wrap_new_event(YtDlp, "ytdlp")
        _patched = True
        LOGGER.info("[helpers] task hooks installed")
        return True
    except Exception as error:
        LOGGER.warning(f"[helpers] hooks unavailable: {error}")
        return False


def remove_hooks() -> bool:
    global _patched
    for cls, original in reversed(_originals):
        try:
            setattr(cls, "new_event", original)
        except Exception:
            pass
    _originals.clear()
    _patched = False
    return True


# ─────────────────────────────────────────────────────────────────────────
# Idle governor
# ─────────────────────────────────────────────────────────────────────────


async def idle_tick() -> bool:
    """Drop helpers if nothing has happened for a while. True if it acted."""
    if not _state["auto"] or not _state["up"]:
        return False
    if _active_tasks() > 0:
        _state["last_activity"] = time.time()
        return False
    idle = time.time() - _state["last_activity"]
    if idle >= _idle_minutes() * 60:
        await stop_all(f"idle {int(idle // 60)} min")
        return True
    return False


async def governor() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await idle_tick()
        except Exception as error:
            _state["error"] = str(error)[:120]
            LOGGER.debug(f"[helpers] governor: {error}")


def _human_uptime() -> str:
    if not _state["up"] or not _state["started_at"]:
        return "down"
    seconds = int(time.time() - _state["started_at"])
    if seconds < 60:
        return f"up {seconds}s"
    return f"up {seconds // 60}m"


# ─────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────


def _card() -> str:
    tokens = _tokens()
    lines = [
        "<b>Helper connections</b>",
        "",
        f"configured: {len(tokens)}",
        f"state: {_human_uptime()}",
        f"auto: {'on' if _state['auto'] else 'off'} (idle {_idle_minutes()} min)",
        f"active tasks: {_active_tasks()}",
        f"raised {_state['raised']}× · dropped {_state['dropped']}×",
    ]
    if not tokens:
        lines += ["", "No helper tokens configured — the bot runs on its own connection."]
    if _state["error"]:
        lines += ["", f"last error: {_state['error']}"]
    return "\n".join(lines)


async def helpers_command(client, message):
    from bot.helper.telegram_helper.button_build import ButtonMaker
    from bot.helper.telegram_helper.message_utils import send_message

    buttons = ButtonMaker()
    buttons.data_button("Bring up", "hlp:up")
    buttons.data_button("Drop", "hlp:down")
    buttons.data_button(
        "Auto off" if _state["auto"] else "Auto on", "hlp:auto"
    )
    await send_message(message, _card(), buttons.build_menu(3))


async def admin_callback(client, query):
    from bot.helper.telegram_helper.message_utils import edit_message

    data = query.data or ""
    if data == "hlp:up":
        count = await start_all()
        note = f"\n\nraised {count} connection(s)"
    elif data == "hlp:down":
        count = await stop_all("manual")
        note = f"\n\ndropped {count} connection(s)"
    elif data == "hlp:auto":
        _state["auto"] = not _state["auto"]
        _state["last_activity"] = time.time()
        note = f"\n\nauto {'on' if _state['auto'] else 'off'}"
    else:
        note = ""
    try:
        await edit_message(query.message, _card() + note)
    except Exception:
        pass
    try:
        await query.answer()
    except Exception:
        pass


class HelpersPlugin(PluginBase):
    PLUGIN_INFO = PluginInfo(
        name="helpers",
        version="1.0.0",
        author="harness",
        description="Connect helper bots only while a task needs them",
        commands=["helpers"],
    )

    async def on_load(self) -> bool:
        global _loop_task
        _state["auto"] = _auto_default()
        tokens = _tokens()
        if not tokens:
            LOGGER.info("[helpers] no helper tokens configured — nothing to govern")
            return True

        install_hooks()

        # the core already started them at boot; put them back down
        if _state["auto"]:
            try:
                await stop_all("startup")
            except Exception as error:
                LOGGER.warning(f"[helpers] startup drop failed: {error}")

        try:
            from pyrogram import filters as pyrogram_filters
            from pyrogram.handlers import CallbackQueryHandler

            self.PLUGIN_INFO.handlers.append(
                CallbackQueryHandler(admin_callback, pyrogram_filters.regex(r"^hlp:"))
            )
        except Exception as error:
            LOGGER.debug(f"[helpers] callback handler: {error}")

        if _loop_task is None or _loop_task.done():
            try:
                _loop_task = asyncio.get_event_loop().create_task(governor())
            except Exception:
                _loop_task = None

        LOGGER.info(
            f"[helpers] loaded — {len(tokens)} helper(s), auto={_state['auto']}, "
            f"idle drop after {_idle_minutes()} min"
        )
        return True

    async def on_unload(self) -> bool:
        global _loop_task
        if _loop_task is not None:
            _loop_task.cancel()
            _loop_task = None
        remove_hooks()
        return True
