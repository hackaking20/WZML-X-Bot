from __future__ import annotations

"""
Branch Switcher Plugin for WZML-X
Adds /bs command (owner only) to switch between Stable (wzv3) and Plugin-Dev branches.

How it works:
- The workflow builds both images: wzml-bot:stable and wzml-bot:plugindev
- The workflow mounts a shared volume at /bs_signal between the host and container
- When the owner sends /bs, the plugin writes a signal file to /bs_signal/switch
- The workflow's keep-alive loop detects the signal file, stops the current container,
  starts the other image, and the bot restarts on the new branch
- The plugin also shows the current branch via /bs status

Usage:
  /bs              Show current branch + available branches
  /bs stable       Switch to Stable (wzv3) branch
  /bs plugindev    Switch to Plugin-Dev branch
  /bs status       Same as /bs (show current branch)
"""

import os
from pathlib import Path

from pyrogram import Client
from pyrogram.types import Message

from bot.core.plugin_manager import PluginBase, PluginInfo
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.telegram_helper.message_utils import send_message

# Signal file path — shared volume mounted by workflow
SIGNAL_DIR = Path("/bs_signal")
SIGNAL_FILE = SIGNAL_DIR / "switch"
CURRENT_FILE = SIGNAL_DIR / "current"
LOCK_FILE = SIGNAL_DIR / ".switching"


class BranchSwitcherPlugin(PluginBase):
    PLUGIN_INFO = PluginInfo(
        name="branch_switcher",
        version="1.0.0",
        author="custom",
        description="Switch between Stable and Plugin-Dev branches (owner only)",
        enabled=True,
        handlers=[],
        commands=["bs"],
        dependencies=[],
    )

    async def on_load(self) -> bool:
        from bot import LOGGER

        # Ensure signal directory exists
        try:
            SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass  # might not be mounted in some setups, that's ok

        # Write current branch marker
        current_branch = _get_current_branch()
        try:
            CURRENT_FILE.write_text(current_branch)
        except Exception as e:
            LOGGER.debug(f"Branch switcher: could not write current marker ({e})")

        LOGGER.info(f"Branch switcher plugin loaded — running on: {current_branch}")
        return True

    async def on_unload(self) -> bool:
        from bot import LOGGER

        LOGGER.info("Branch switcher plugin unloaded")
        return True


def _get_current_branch() -> str:
    """Read the current branch from the marker file, or detect from environment."""
    try:
        if CURRENT_FILE.exists():
            return CURRENT_FILE.read_text().strip()
    except Exception:
        pass
    # Fallback: check if we're in the plugin-dev image
    # The workflow sets BRANCH_LABEL env var when starting the container
    return os.environ.get("BRANCH_LABEL", "stable")


def _is_switching() -> bool:
    """Check if a switch is already in progress."""
    return LOCK_FILE.exists()


@new_task
async def bs_command(client: Client, message: Message):
    """Handle /bs command — owner only, switch between branches."""
    from bot import LOGGER
    from bot.core.config_manager import Config

    # Owner only
    user_id = message.from_user.id if message.from_user else 0
    if user_id != Config.OWNER_ID:
        await send_message(message, "❌ This command is for the owner only.")
        return

    text = message.text.split("\n")
    args = text[0].split(" ")[1:] if len(text[0].split(" ")) > 1 else []

    current_branch = _get_current_branch()
    current_display = "Stable (wzv3)" if current_branch == "stable" else "Plugin-Dev"

    if not args or args[0].lower() in ("status", "info"):
        status_text = (
            f"🔀 <b>Branch Switcher</b>\n\n"
            f"📍 Current: <b>{current_display}</b>\n"
            f"📝 Branch: <code>{current_branch}</code>\n\n"
            f"Available branches:\n"
            f"  • <code>stable</code> — Default stable release (wzv3)\n"
            f"  • <code>plugindev</code> — Plugin-Dev branch with PluginBase\n\n"
            f"Usage:\n"
            f"  <code>/bs stable</code> — Switch to Stable\n"
            f"  <code>/bs plugindev</code> — Switch to Plugin-Dev\n"
            f"  <code>/bs status</code> — Show this info\n\n"
            f"⚠️ Switching takes ~30 seconds. Bot will restart."
        )
        await send_message(message, status_text)
        return

    target = args[0].lower().strip()

    # Normalize input
    if target in ("stable", "wzv3", "default"):
        target = "stable"
        target_display = "Stable (wzv3)"
    elif target in ("plugindev", "plugin-dev", "dev", "beta"):
        target = "plugindev"
        target_display = "Plugin-Dev"
    else:
        await send_message(
            message,
            f"❌ Unknown branch: <code>{target}</code>\n\n"
            f"Available: <code>stable</code>, <code>plugindev</code>",
        )
        return

    # Check if already on this branch
    if target == current_branch:
        await send_message(
            message,
            f"ℹ️ Already running on <b>{target_display}</b>.\n"
            f"No switch needed.",
        )
        return

    # Check if a switch is already in progress
    if _is_switching():
        await send_message(
            message,
            "⏳ A branch switch is already in progress. Please wait...",
        )
        return

    # Check if signal directory is writable (volume must be mounted)
    try:
        SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
        test_file = SIGNAL_DIR / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
    except Exception as e:
        LOGGER.error(f"Branch switcher: signal dir not writable: {e}")
        await send_message(
            message,
            f"❌ <b>Cannot switch branch</b>\n\n"
            f"The signal directory is not available.\n"
            f"Make sure the workflow is running with the shared volume.\n\n"
            f"Error: <code>{str(e)[:200]}</code>",
        )
        return

    # Write the signal file
    try:
        # Create lock file first
        LOCK_FILE.write_text(target)

        # Write switch signal
        SIGNAL_FILE.write_text(target)

        LOGGER.info(f"Branch switch signal sent: {current_branch} -> {target}")

        await send_message(
            message,
            f"🔀 <b>Switching to {target_display}</b>\n\n"
            f"From: {current_display}\n"
            f"To: {target_display}\n\n"
            f"⏱️ Bot will restart in ~10 seconds.\n"
            f"You'll get a message when it's back online.",
        )

        # Notify via the bot that switch is happening
        try:
            from bot.core.tg_client import TgClient

            await TgClient.bot.send_message(
                chat_id=Config.OWNER_ID,
                text=f"🔄 Branch switch initiated: {current_display} → {target_display}\n"
                f"Bot will restart momentarily...",
            )
        except Exception:
            pass

    except Exception as e:
        LOGGER.error(f"Branch switcher: failed to write signal: {e}")
        # Clean up lock
        try:
            LOCK_FILE.unlink()
        except Exception:
            pass
        await send_message(
            message,
            f"❌ <b>Switch failed</b>\n\nError: <code>{str(e)[:300]}</code>",
        )


# Plugin instance (required for the plugin system)
plugin_instance = BranchSwitcherPlugin()
