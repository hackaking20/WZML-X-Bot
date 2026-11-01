"""Change the password for the /links page from Telegram.

    /setwebpass <new password>

The value is written to MongoDB (collection `webpass`, document
`web_access_password`) so the web process picks it up within five seconds,
without a restart and without touching the repository.

A GitHub secret still wins: if WEB_ACCESS_PASSWORD or WEBDL_PASS is set in the
environment, that is used instead of the stored value. Set them and this command
has no effect; leave them unset and this is the password.
"""

from __future__ import annotations

import os

from bot import LOGGER
from bot.core.plugin_manager import PluginBase, PluginInfo

DEFAULT = "joshi"
MIN_LEN = 4


def _db():
    from pymongo import MongoClient

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    return MongoClient(url, serverSelectionTimeoutMS=6000)


def _current() -> str:
    for name in ("WEB_ACCESS_PASSWORD", "WEBDL_PASS"):
        value = os.environ.get(name, "").strip()
        if value:
            return f"{value} (from {name})"
    try:
        client = _db()
        if client is None:
            return f"{DEFAULT} (default, no DATABASE_URL)"
        with client:
            doc = client["webpass"]["config"].find_one({"_id": "web_access_password"})
        return (doc or {}).get("value") or f"{DEFAULT} (default)"
    except Exception:
        return f"{DEFAULT} (default, database unreachable)"


async def setwebpass_command(client, message):
    from bot.helper.telegram_helper.message_utils import send_message

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await send_message(
            message,
            "<b>Usage:</b> <code>/setwebpass &lt;new password&gt;</code>\n\n"
            f"Current: <code>{_current()}</code>\n"
            "This is the password for the <code>/links</code> page.",
        )
        return

    value = parts[1].strip()
    if len(value) < MIN_LEN:
        await send_message(message, f"Too short — use at least {MIN_LEN} characters.")
        return

    try:
        db = _db()
        if db is None:
            await send_message(message, "No <code>DATABASE_URL</code> configured, so there is nowhere to store it.")
            return
        with db:
            db["webpass"]["config"].update_one(
                {"_id": "web_access_password"},
                {"$set": {"value": value}},
                upsert=True,
            )
    except Exception as error:
        await send_message(message, f"Could not save: <code>{error}</code>")
        return

    # if a secret is set it wins, so say so plainly
    override = next(
        (n for n in ("WEB_ACCESS_PASSWORD", "WEBDL_PASS") if os.environ.get(n, "").strip()),
        "",
    )
    note = (
        f"\n\n<b>Note:</b> <code>{override}</code> is set in the environment and "
        "takes priority — remove that secret for this value to apply."
        if override
        else "\n\nTakes effect within five seconds."
    )
    LOGGER.info("[webpass] /links password changed")
    await send_message(message, f"<b>/links password saved.</b>{note}")


class WebPassPlugin(PluginBase):
    PLUGIN_INFO = PluginInfo(
        name="webpass",
        version="1.0.0",
        author="harness",
        description="Change the /links page password",
        commands=["setwebpass"],
    )

    async def on_load(self) -> bool:
        LOGGER.info("[webpass] loaded — /setwebpass available")
        return True

    async def on_unload(self) -> bool:
        return True
