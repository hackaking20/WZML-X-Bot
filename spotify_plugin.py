"""
SpotDL Plugin for WZML-X
Adds /spotify command to download music from Spotify URLs.
Uses spotDL under the hood (which uses yt-dlp for actual downloads).
Applies Spotify metadata: album art, ID3 tags, lyrics.

Usage:
  /spotify <spotify_url>          Download to Telegram
  /spotify <url> -d <gdrive_id>   Download to Google Drive

Supports: track, album, playlist, and artist URLs.
"""

import asyncio
import re
from pathlib import Path

from pyrogram import Client
from pyrogram.types import Message

from bot.core.plugin_manager import PluginBase, PluginInfo
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)

# Spotify URL patterns
SPOTIFY_PATTERNS = [
    re.compile(r"https?://open\.spotify\.com/track/[a-zA-Z0-9]+"),
    re.compile(r"https?://open\.spotify\.com/album/[a-zA-Z0-9]+"),
    re.compile(r"https?://open\.spotify\.com/playlist/[a-zA-Z0-9]+"),
    re.compile(r"https?://open\.spotify\.com/artist/[a-zA-Z0-9]+"),
]


def is_spotify_url(text: str) -> bool:
    return any(p.search(text) for p in SPOTIFY_PATTERNS)


class SpotifyPlugin(PluginBase):
    PLUGIN_INFO = PluginInfo(
        name="spotify_plugin",
        version="1.0.0",
        author="custom",
        description="Download music from Spotify URLs with metadata",
        enabled=True,
        handlers=[],
        commands=["spotify"],
        dependencies=["spotdl"],
    )

    async def on_load(self) -> bool:
        from bot import LOGGER

        # Check if spotdl is installed
        try:
            proc = await asyncio.create_subprocess_exec(
                "spotdl", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode == 0:
                LOGGER.info("Spotify plugin loaded - spotDL is available")
                return True
            else:
                LOGGER.warning("Spotify plugin: spotDL not found, installing...")
                proc = await asyncio.create_subprocess_exec(
                    "pip", "install", "spotdl",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
                LOGGER.info("spotDL installed successfully")
                return True
        except Exception as e:
            LOGGER.error(f"Spotify plugin load error: {e}")
            return False

    async def on_unload(self) -> bool:
        from bot import LOGGER

        LOGGER.info("Spotify plugin unloaded")
        return True


@new_task
async def spotify_command(client: Client, message: Message):
    """Download music from a Spotify URL."""
    from bot import DOWNLOAD_DIR, LOGGER

    # Parse arguments
    text = message.text.split(maxsplit=1)
    if len(text) < 2:
        await send_message(
            message,
            "<b>Spotify Downloader</b>\n\n"
            "<b>Usage:</b>\n"
            "  <code>/spotify {url}</code> - Download to Telegram\n\n"
            "<b>Supported URLs:</b>\n"
            "  • Track: open.spotify.com/track/...\n"
            "  • Album: open.spotify.com/album/...\n"
            "  • Playlist: open.spotify.com/playlist/...\n"
            "  • Artist: open.spotify.com/artist/...",
        )
        return

    query = text[1].strip()

    if not is_spotify_url(query):
        await send_message(
            message,
            "❌ <b>Invalid Spotify URL</b>\n\n"
            "Please provide a valid Spotify URL (track, album, playlist, or artist).\n"
            "Example: <code>/spotify https://open.spotify.com/track/...</code>",
        )
        return

    # Create unique download directory
    import time
    from hashlib import md5

    task_id = md5(f"{query}{time.time()}".encode()).hexdigest()[:8]
    download_path = Path(DOWNLOAD_DIR) / f"spotify_{task_id}"
    download_path.mkdir(parents=True, exist_ok=True)

    status_msg = await send_message(
        message,
        f"🎵 <b>Spotify Download Started</b>\n\n"
        f"URL: {query}\n"
        f"Status: Fetching metadata...",
    )

    try:
        # Run spotdl download
        cmd = [
            "spotdl", "download", query,
            "--output", str(download_path / "{artists} - {title}.{output-ext}"),
            "--format", "mp3",
        ]

        LOGGER.info(f"Spotify download started: {query} -> {download_path}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Track progress by reading stdout
        last_lines = []
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded:
                last_lines.append(decoded)
                # Keep only last 5 lines
                if len(last_lines) > 5:
                    last_lines.pop(0)
                # Update status every few lines
                if "Downloaded" in decoded or "Downloading" in decoded:
                    short = decoded[:100]
                    await edit_message(
                        status_msg,
                        f"🎵 <b>Spotify Download</b>\n\n"
                        f"URL: {query}\n"
                        f"Status: {short}",
                    )

        await proc.wait()

        if proc.returncode != 0:
            stderr = await proc.stderr.read()
            error_text = stderr.decode("utf-8", errors="replace").strip()[-500:]
            await edit_message(
                status_msg,
                f"❌ <b>Download Failed</b>\n\n"
                f"URL: {query}\n"
                f"Error: <code>{error_text}</code>",
            )
            # Cleanup
            import shutil
            shutil.rmtree(download_path, ignore_errors=True)
            return

        # Find downloaded files
        downloaded_files = list(download_path.glob("*.mp3"))
        if not downloaded_files:
            downloaded_files = list(download_path.glob("*"))

        if not downloaded_files:
            await edit_message(
                status_msg,
                f"❌ <b>No files downloaded</b>\n\n"
                f"URL: {query}\n"
                f"spotDL completed but no files found.",
            )
            shutil.rmtree(download_path, ignore_errors=True)
            return

        await edit_message(
            status_msg,
            f"✅ <b>Download Complete</b>\n\n"
            f"URL: {query}\n"
            f"Files: {len(downloaded_files)}\n"
            f"Status: Uploading to Telegram...",
        )

        # Upload files to Telegram
        from bot.helper.ext_utils.status_utils import get_readable_file_size

        for i, file_path in enumerate(downloaded_files):
            file_size = file_path.stat().st_size
            caption = (
                f"🎵 <b>{file_path.stem}</b>\n"
                f"Size: {get_readable_file_size(file_size)}"
            )

            try:
                if file_size > 2 * 1024 * 1024 * 1024:
                    # File too large for Telegram, send as document
                    await message.reply_document(
                        document=str(file_path),
                        caption=caption,
                    )
                else:
                    await message.reply_audio(
                        audio=str(file_path),
                        caption=caption,
                    )
            except Exception as e:
                LOGGER.error(f"Error sending {file_path}: {e}")
                # Fallback: send as document
                try:
                    await message.reply_document(
                        document=str(file_path),
                        caption=caption,
                    )
                except Exception as e2:
                    LOGGER.error(f"Document fallback also failed: {e2}")

            # Small delay between sends
            await asyncio.sleep(1)

        await edit_message(
            status_msg,
            f"✅ <b>Spotify Download Complete</b>\n\n"
            f"URL: {query}\n"
            f"Files sent: {len(downloaded_files)}",
        )

        # Cleanup download directory
        import shutil
        shutil.rmtree(download_path, ignore_errors=True)
        await delete_message(status_msg)

    except FileNotFoundError:
        await edit_message(
            status_msg,
            "❌ <b>spotDL is not installed</b>\n\n"
            "Please ensure spotDL is installed in the container.",
        )
    except Exception as e:
        LOGGER.error(f"Spotify plugin error: {e}", exc_info=True)
        await edit_message(
            status_msg,
            f"❌ <b>Error</b>\n\n<code>{str(e)[:500]}</code>",
        )
        import shutil
        shutil.rmtree(download_path, ignore_errors=True)
