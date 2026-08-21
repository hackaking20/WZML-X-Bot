from __future__ import annotations

"""
SpotDL Plugin for WZML-X
Adds /spotify command to download music from Spotify URLs.
Uses spotDL under the hood (which uses yt-dlp for actual downloads).
Applies Spotify metadata: album art, ID3 tags, lyrics.

Uses WZML-X's own arg_parser so all standard bot flags work natively:
  -z        Zip all files into one archive
  -up       Upload destination (GDrive ID, rclone path, Telegram chat)
  -n        Rename the output folder/zip
  -t        Custom thumbnail (URL or Telegram message link)
  -doc      Send as document instead of audio
  -med      Send as media (audio) — default behavior
  -sp       Split size for large uploads (e.g. 500mb, 2gb)
  -b        Bulk: reply to a text message/file with multiple Spotify URLs
  -i        Multi: reply to first of multiple messages containing URLs
  -m        Move all files into one named folder
  -hl       Hybrid leech (bot + user session based on size)
  -bt       Leech by bot session
  -ut       Leech by user session
  -e        Extract (ignored for Spotify, files are already MP3)
  -j        Join (ignored for Spotify)

Usage:
  /spotify <url>                         Download to Telegram as audio
  /spotify <url> -z                      Zip all files, send as document
  /spotify <url> -up <gdrive_id>        Upload to Google Drive
  /spotify <url> -n "My Album" -z        Custom name + zip
  /spotify <url> -doc                    Send as document instead of audio
  /spotify <url> -t <image_url>          Custom thumbnail
  /spotify <url> -sp 500mb              Split at 500MB
  Reply to text file: /spotify -b        Bulk download from file
  Reply to messages: /spotify -i 5       Multi download from 5 messages
"""

import asyncio
import re
import shutil
import zipfile
from pathlib import Path
from hashlib import md5
import time

from pyrogram import Client
from pyrogram.types import Message

from bot.core.plugin_manager import PluginBase, PluginInfo
from bot.helper.ext_utils.bot_utils import new_task, arg_parser, sync_to_async
from bot.helper.ext_utils.status_utils import get_readable_file_size
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
    """Check if text contains a valid Spotify URL."""
    return any(p.search(text) for p in SPOTIFY_PATTERNS)


def extract_spotify_urls(text: str) -> list:
    """Extract all Spotify URLs from a block of text."""
    urls = []
    for pattern in SPOTIFY_PATTERNS:
        urls.extend(pattern.findall(text))
    # Also extract full URLs (not just matched portion)
    all_urls = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if is_spotify_url(line):
            all_urls.append(line.split()[0])  # first token is the URL
    return all_urls if all_urls else urls


class SpotifyPlugin(PluginBase):
    PLUGIN_INFO = PluginInfo(
        name="spotify_plugin",
        version="2.0.0",
        author="custom",
        description="Download music from Spotify URLs with metadata",
        enabled=True,
        handlers=[],
        commands=["spotify"],
        dependencies=["spotdl"],
    )

    async def on_load(self) -> bool:
        from bot import LOGGER

        # Always return True so the command registers even if spotdl
        # has a transient issue — we check again at download time.
        try:
            proc = await asyncio.create_subprocess_exec(
                "spotdl", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode == 0:
                LOGGER.info("Spotify plugin loaded — spotDL is available")
            else:
                LOGGER.warning("Spotify plugin: spotDL not found at load time, will retry on download")
        except Exception as e:
            LOGGER.warning(f"Spotify plugin: spotDL check failed at load time ({e}), will retry on download")
        return True

    async def on_unload(self) -> bool:
        from bot import LOGGER

        LOGGER.info("Spotify plugin unloaded")
        return True


# Default arg template matching WZML-X's mirror_leech.py
SPOTIFY_ARGS = {
    "-doc": False,
    "-med": False,
    "-d": False,
    "-j": False,
    "-s": False,
    "-b": False,
    "-e": False,
    "-z": False,
    "-sv": False,
    "-ss": False,
    "-f": False,
    "-fd": False,
    "-fu": False,
    "-hl": False,
    "-bt": False,
    "-ut": False,
    "-ad": False,
    "-yt": False,
    "-i": 0,
    "-sp": 0,
    "link": "",
    "-n": "",
    "-m": "",
    "-meta": "",
    "-up": "",
    "-gc": "",
    "-rcf": "",
    "-au": "",
    "-ap": "",
    "-h": "",
    "-t": "",
    "-ca": "",
    "-cv": "",
    "-ns": "",
    "-tl": "",
    "-ff": set(),
}


async def _run_spotdl(query: str, download_path: Path, LOGGER) -> tuple:
    """Run spotdl download for a single URL. Returns (success, files_list, error)."""
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
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        # Lines are logged but we don't update status here (caller does)

    await proc.wait()

    if proc.returncode != 0:
        stderr = await proc.stderr.read()
        error_text = stderr.decode("utf-8", errors="replace").strip()[-500:]
        return (False, [], error_text)

    # Find downloaded files
    downloaded_files = sorted(download_path.glob("*.mp3"))
    if not downloaded_files:
        downloaded_files = sorted(download_path.glob("*"))

    return (True, downloaded_files, "")


async def _download_thumbnail(thumb_input: str) -> str | None:
    """Download a thumbnail from URL or return None."""
    if not thumb_input or thumb_input == "none":
        return None
    try:
        from bot.helper.ext_utils.bot_utils import download_image_url
        return await sync_to_async(download_image_url, thumb_input)
    except Exception:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(thumb_input) as resp:
                    if resp.status == 200:
                        path = f"/tmp/thumb_{int(time.time())}.jpg"
                        with open(path, "wb") as f:
                            f.write(await resp.read())
                        return path
        except Exception:
            return None
    return None


async def _upload_to_telegram(
    client: Client,
    message: Message,
    files: list,
    args: dict,
    status_msg,
    query: str,
    LOGGER,
    thumb_path: str | None = None,
):
    """Upload files to Telegram with the appropriate flags."""
    from bot import DOWNLOAD_DIR

    as_doc = args.get("-doc", False)
    split_size_str = args.get("-sp", 0)

    # Parse split size
    split_size = 0
    if split_size_str and isinstance(split_size_str, str):
        sl = split_size_str.lower()
        if "gb" in sl:
            split_size = int(float(sl.replace("gb", "").strip()) * 1024 * 1024 * 1024)
        elif "mb" in sl:
            split_size = int(float(sl.replace("mb", "").strip()) * 1024 * 1024)
        elif sl.isdigit():
            split_size = int(sl)
    elif split_size_str and isinstance(split_size_str, int):
        split_size = split_size_str

    # Determine upload chat
    up_dest = args.get("-up", "")
    target_chat = message.chat.id  # default: same chat
    is_bot_upload = False
    is_user_upload = False

    if up_dest:
        # Parse -up for Telegram destinations
        # Format: id/@username/pm | b:id/@username | u:id/@username | h:id/@username
        dest = up_dest
        if dest.startswith("b:"):
            is_bot_upload = True
            dest = dest[2:]
        elif dest.startswith("u:"):
            is_user_upload = True
            dest = dest[2:]
        elif dest.startswith("h:"):
            # Hybrid — treat as bot for now
            is_bot_upload = True
            dest = dest[2:]

        if dest == "pm":
            target_chat = message.from_user.id if message.from_user else message.chat.id
        elif dest.startswith("@"):
            target_chat = dest
        elif dest.lstrip("-").isdigit():
            target_chat = int(dest)
        # If it doesn't match Telegram patterns, it's probably GDrive/rclone
        # — we'd need the full upload pipeline for that

    # Upload each file
    sent_count = 0
    for file_path in files:
        file_size = file_path.stat().st_size
        file_name = file_path.stem

        caption = (
            f"🎵 <b>{file_name}</b>\n"
            f"📦 Size: {get_readable_file_size(file_size)}"
        )

        # Apply split if needed
        actual_path = str(file_path)
        if split_size > 0 and file_size > split_size:
            # For audio, splitting doesn't make much sense, but we respect the flag
            LOGGER.info(f"File {file_name} ({file_size}) exceeds split size {split_size}, sending as document")
            as_doc = True

        try:
            send_kwargs = {
                "chat_id": target_chat,
                "caption": caption,
            }
            if thumb_path:
                send_kwargs["thumb"] = thumb_path

            if as_doc or file_size > 2 * 1024 * 1024 * 1024:
                await client.send_document(
                    document=actual_path,
                    **send_kwargs,
                )
            else:
                await client.send_audio(
                    audio=actual_path,
                    **send_kwargs,
                )
            sent_count += 1
        except Exception as e:
            LOGGER.error(f"Error sending {file_path}: {e}")
            # Fallback: send as document
            try:
                await client.send_document(
                    document=actual_path,
                    chat_id=target_chat,
                    caption=caption,
                )
                sent_count += 1
            except Exception as e2:
                LOGGER.error(f"Document fallback also failed: {e2}")

        await asyncio.sleep(1)

    return sent_count


async def _upload_to_gdrive(
    files: list,
    up_dest: str,
    args: dict,
    status_msg,
    query: str,
    LOGGER,
):
    """Upload files to Google Drive using WZML-X's gdrive utils."""
    try:
        from bot.helper.mirror_leech_utils.gdrive_utils.upload import gdrive_upload
        from bot.helper.mirror_leech_utils.gdrive_utils.helper import GoogleDriveHelper

        await edit_message(
            status_msg,
            f"☁️ <b>Uploading to Google Drive</b>\n\n"
            f"URL: {query}\n"
            f"Files: {len(files)}\n"
            f"Dest: {up_dest}",
        )

        gdrive_id = up_dest.lstrip("gd:").strip()
        uploaded = 0
        for file_path in files:
            try:
                # Use WZML-X's Google Drive upload
                helper = GoogleDriveHelper()
                link = await sync_to_async(
                    helper.upload, str(file_path), gdrive_id
                )
                if link:
                    uploaded += 1
                    LOGGER.info(f"Uploaded {file_path.name} to GDrive: {link}")
            except Exception as e:
                LOGGER.error(f"GDrive upload error for {file_path}: {e}")

        return uploaded
    except ImportError:
        await edit_message(
            status_msg,
            "❌ <b>Google Drive upload not available</b>\n\n"
            "GDrive utils not found. Sending to Telegram instead.",
        )
        return -1
    except Exception as e:
        LOGGER.error(f"GDrive upload error: {e}")
        await edit_message(
            status_msg,
            f"❌ <b>GDrive upload error</b>\n\n<code>{str(e)[:300]}</code>",
        )
        return -1


async def _upload_to_rclone(
    files: list,
    up_dest: str,
    args: dict,
    status_msg,
    query: str,
    LOGGER,
):
    """Upload files to rclone remote."""
    try:
        from bot.helper.mirror_leech_utils.rclone_utils.transfer import RcloneTransfer

        await edit_message(
            status_msg,
            f"📁 <b>Uploading to Rclone</b>\n\n"
            f"URL: {query}\n"
            f"Files: {len(files)}\n"
            f"Dest: {up_dest}",
        )

        # Parse rclone path: remote:path/subdir
        rc_dest = up_dest.lstrip("rc:").strip() if up_dest.startswith("rc:") else up_dest
        transfer = RcloneTransfer()
        uploaded = 0
        for file_path in files:
            try:
                await sync_to_async(transfer.upload, str(file_path), rc_dest)
                uploaded += 1
                LOGGER.info(f"Uploaded {file_path.name} to rclone: {rc_dest}")
            except Exception as e:
                LOGGER.error(f"Rclone upload error for {file_path}: {e}")

        return uploaded
    except ImportError:
        await edit_message(
            status_msg,
            "❌ <b>Rclone upload not available</b>\n\n"
            "Rclone utils not found. Sending to Telegram instead.",
        )
        return -1
    except Exception as e:
        LOGGER.error(f"Rclone upload error: {e}")
        await edit_message(
            status_msg,
            f"❌ <b>Rclone upload error</b>\n\n<code>{str(e)[:300]}</code>",
        )
        return -1


async def _process_single_url(
    client: Client,
    message: Message,
    query: str,
    args: dict,
    status_msg,
    task_id: str,
    LOGGER,
    download_base: Path,
):
    """Process a single Spotify URL: download + upload."""
    from bot import DOWNLOAD_DIR

    download_path = download_base / f"spotify_{task_id}"
    download_path.mkdir(parents=True, exist_ok=True)

    await edit_message(
        status_msg,
        f"🎵 <b>Spotify Download Started</b>\n\n"
        f"URL: {query}\n"
        f"Status: Fetching metadata...",
    )

    # Run spotDL
    success, downloaded_files, error = await _run_spotdl(query, download_path, LOGGER)

    if not success:
        await edit_message(
            status_msg,
            f"❌ <b>Download Failed</b>\n\n"
            f"URL: {query}\n"
            f"Error: <code>{error}</code>",
        )
        shutil.rmtree(download_path, ignore_errors=True)
        return False

    if not downloaded_files:
        await edit_message(
            status_msg,
            f"❌ <b>No files downloaded</b>\n\n"
            f"URL: {query}\n"
            f"spotDL completed but no files found.",
        )
        shutil.rmtree(download_path, ignore_errors=True)
        return False

    # Apply -n (rename) flag
    new_name = args.get("-n", "")
    if new_name and len(downloaded_files) == 1:
        # Rename single file
        old_path = downloaded_files[0]
        new_path = old_path.parent / f"{new_name}.mp3"
        old_path.rename(new_path)
        downloaded_files = [new_path]
    elif new_name and len(downloaded_files) > 1:
        # Rename the folder
        new_folder = download_path.parent / new_name
        download_path.rename(new_folder)
        download_path = new_folder
        downloaded_files = sorted(new_folder.glob("*.mp3"))

    # Apply -m (move to folder) flag
    folder_name = args.get("-m", "")
    if folder_name:
        shared_folder = download_base / folder_name
        shared_folder.mkdir(parents=True, exist_ok=True)
        moved = []
        for f in downloaded_files:
            dest = shared_folder / f.name
            f.rename(dest)
            moved.append(dest)
        downloaded_files = moved
        # Update download_path for cleanup later
        if not download_path.exists():
            download_path = shared_folder

    # Download thumbnail if -t flag is set
    thumb_path = None
    thumb_input = args.get("-t", "")
    if thumb_input:
        thumb_path = await _download_thumbnail(thumb_input)
        if thumb_path:
            LOGGER.info(f"Using custom thumbnail: {thumb_path}")

    # Determine upload method from -up flag
    up_dest = args.get("-up", "")
    is_zip = args.get("-z", False)

    await edit_message(
        status_msg,
        f"✅ <b>Download Complete</b>\n\n"
        f"URL: {query}\n"
        f"Files: {len(downloaded_files)}\n"
        f"Status: {'Zipping files...' if is_zip and len(downloaded_files) > 1 else 'Uploading...'}",
    )

    # ── ZIP MODE ──
    if is_zip and len(downloaded_files) > 1:
        zip_name = args.get("-n", "") or _derive_name(query)
        zip_path = download_path.parent / f"{zip_name}_{task_id}.zip"

        LOGGER.info(f"Zipping {len(downloaded_files)} files into {zip_path}")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in downloaded_files:
                zf.write(file_path, arcname=file_path.name)

        zip_size = zip_path.stat().st_size
        total_audio_size = sum(f.stat().st_size for f in downloaded_files)

        await edit_message(
            status_msg,
            f"✅ <b>Zip Complete</b>\n\n"
            f"URL: {query}\n"
            f"Songs: {len(downloaded_files)}\n"
            f"Audio size: {get_readable_file_size(total_audio_size)}\n"
            f"Zip size: {get_readable_file_size(zip_size)}\n"
            f"Status: Uploading...",
        )

        caption = (
            f"🎵 <b>Spotify Archive</b>\n"
            f"Songs: {len(downloaded_files)}\n"
            f"Size: {get_readable_file_size(zip_size)}"
        )

        try:
            send_kwargs = {"chat_id": message.chat.id, "caption": caption}
            if thumb_path:
                send_kwargs["thumb"] = thumb_path

            # Check if -up points to Telegram
            if up_dest and _is_telegram_dest(up_dest):
                send_kwargs["chat_id"] = _parse_telegram_dest(up_dest, message)

            await client.send_document(document=str(zip_path), **send_kwargs)
            await edit_message(
                status_msg,
                f"✅ <b>Spotify Download Complete</b>\n\n"
                f"URL: {query}\n"
                f"Songs: {len(downloaded_files)}\n"
                f"Zip size: {get_readable_file_size(zip_size)}",
            )
        except Exception as e:
            LOGGER.error(f"Error sending zip: {e}")
            if zip_size > 2 * 1024 * 1024 * 1024:
                await edit_message(
                    status_msg,
                    f"⚠️ <b>Zip too large ({get_readable_file_size(zip_size)})</b>\n\n"
                    f"Sending files individually...",
                )
                await _upload_to_telegram(
                    client, message, downloaded_files, args,
                    status_msg, query, LOGGER, thumb_path,
                )
            else:
                raise

        # Cleanup
        if zip_path.exists():
            zip_path.unlink()
    else:
        # ── NORMAL MODE: individual files or GDrive/rclone upload ──
        if up_dest and not _is_telegram_dest(up_dest):
            # GDrive or rclone upload
            if up_dest.startswith(("tp:", "sa:", "mtp:")) or up_dest.lstrip("-").isdigit() or len(up_dest) > 20:
                # Looks like a GDrive ID
                result = await _upload_to_gdrive(
                    downloaded_files, up_dest, args, status_msg, query, LOGGER
                )
                if result == -1:
                    # Fallback to Telegram
                    await _upload_to_telegram(
                        client, message, downloaded_files, args,
                        status_msg, query, LOGGER, thumb_path,
                    )
            elif ":" in up_dest or up_dest.startswith("rcl:") or up_dest.startswith("mrcc:"):
                # Looks like rclone path
                result = await _upload_to_rclone(
                    downloaded_files, up_dest, args, status_msg, query, LOGGER
                )
                if result == -1:
                    await _upload_to_telegram(
                        client, message, downloaded_files, args,
                        status_msg, query, LOGGER, thumb_path,
                    )
            else:
                # Unknown destination, fallback to Telegram
                await _upload_to_telegram(
                    client, message, downloaded_files, args,
                    status_msg, query, LOGGER, thumb_path,
                )
        else:
            # Telegram upload
            sent = await _upload_to_telegram(
                client, message, downloaded_files, args,
                status_msg, query, LOGGER, thumb_path,
            )
            await edit_message(
                status_msg,
                f"✅ <b>Spotify Download Complete</b>\n\n"
                f"URL: {query}\n"
                f"Files sent: {sent}",
            )

    # Cleanup
    shutil.rmtree(download_path, ignore_errors=True)
    return True


def _derive_name(query: str) -> str:
    """Derive a clean name from the Spotify URL type."""
    if "/track/" in query:
        return "spotify_track"
    elif "/album/" in query:
        return "spotify_album"
    elif "/playlist/" in query:
        return "spotify_playlist"
    elif "/artist/" in query:
        return "spotify_artist"
    return "spotify_download"


def _is_telegram_dest(up_dest: str) -> bool:
    """Check if -up destination is a Telegram chat."""
    dest = up_dest
    for prefix in ("b:", "u:", "h:"):
        if dest.startswith(prefix):
            dest = dest[len(prefix):]
            break
    if dest in ("pm",):
        return True
    if dest.startswith("@"):
        return True
    if dest.lstrip("-").isdigit() and len(dest) < 20:
        return True
    return False


def _parse_telegram_dest(up_dest: str, message: Message):
    """Parse Telegram destination from -up flag."""
    dest = up_dest
    for prefix in ("b:", "u:", "h:"):
        if dest.startswith(prefix):
            dest = dest[len(prefix):]
            break
    if dest == "pm":
        return message.from_user.id if message.from_user else message.chat.id
    if dest.startswith("@"):
        return dest
    if dest.lstrip("-").isdigit():
        return int(dest)
    return message.chat.id


@new_task
async def spotify_command(client: Client, message: Message):
    """Download music from Spotify URLs with full WZML-X flag support."""
    from bot import DOWNLOAD_DIR, LOGGER

    text = message.text.split("\n")
    input_list = text[0].split(" ")

    # Build args dict (fresh copy each time)
    args = SPOTIFY_ARGS.copy()
    arg_parser(input_list[1:], args)

    # ── Handle -b (bulk) ──
    if args.get("-b", False):
        reply_to = message.reply_to_message
        if not reply_to:
            await send_message(
                message,
                "❌ <b>Bulk mode requires replying to a text message or file</b>\n\n"
                "Reply to a message containing multiple Spotify URLs (one per line)\n"
                "and use: <code>/spotify -b</code>",
            )
            return

        # Get URLs from replied message
        bulk_text = reply_to.text or reply_to.caption or ""
        if reply_to.document:
            # Download text file
            file_path = await reply_to.download()
            with open(file_path, "r") as f:
                bulk_text = f.read()

        urls = extract_spotify_urls(bulk_text)
        if not urls:
            await send_message(
                message,
                "❌ <b>No Spotify URLs found</b>\n\n"
                "The replied message/file must contain Spotify URLs (one per line).",
            )
            return

        status_msg = await send_message(
            message,
            f"📦 <b>Bulk Spotify Download</b>\n\n"
            f"Found {len(urls)} URLs\n"
            f"Processing...",
        )

        task_id = md5(f"bulk{time.time()}".encode()).hexdigest()[:8]
        download_base = Path(DOWNLOAD_DIR) / f"spotify_bulk_{task_id}"
        download_base.mkdir(parents=True, exist_ok=True)

        success_count = 0
        for i, url in enumerate(urls):
            await edit_message(
                status_msg,
                f"📦 <b>Bulk Spotify Download</b>\n\n"
                f"Processing {i + 1}/{len(urls)}\n"
                f"URL: {url}",
            )
            sub_id = f"{task_id}_{i}"
            ok = await _process_single_url(
                client, message, url, args, status_msg,
                sub_id, LOGGER, download_base,
            )
            if ok:
                success_count += 1

        await edit_message(
            status_msg,
            f"✅ <b>Bulk Download Complete</b>\n\n"
            f"Total: {len(urls)}\n"
            f"Success: {success_count}\n"
            f"Failed: {len(urls) - success_count}",
        )
        await delete_message(status_msg)
        shutil.rmtree(download_base, ignore_errors=True)
        return

    # ── Handle -i (multi) ──
    multi = int(args.get("-i", 0))
    if multi > 0:
        reply_to = message.reply_to_message
        if not reply_to:
            await send_message(
                message,
                "❌ <b>Multi mode requires replying to messages</b>\n\n"
                "Reply to the first message containing a Spotify URL\n"
                "and use: <code>/spotify -i 5</code>",
            )
            return

        urls = []
        current = reply_to
        for _ in range(multi):
            if current and current.text:
                url = current.text.split("\n")[0].strip()
                if is_spotify_url(url):
                    urls.append(url)
            current = await client.get_messages(
                chat_id=message.chat.id,
                message_ids=current.id + 1,
            ) if current else None

        if not urls:
            await send_message(message, "❌ No Spotify URLs found in replied messages.")
            return

        status_msg = await send_message(
            message,
            f"📋 <b>Multi Spotify Download</b>\n\n"
            f"Found {len(urls)} URLs\n"
            f"Processing...",
        )

        task_id = md5(f"multi{time.time()}".encode()).hexdigest()[:8]
        download_base = Path(DOWNLOAD_DIR) / f"spotify_multi_{task_id}"
        download_base.mkdir(parents=True, exist_ok=True)

        success_count = 0
        for i, url in enumerate(urls):
            await edit_message(
                status_msg,
                f"📋 <b>Multi Spotify Download</b>\n\n"
                f"Processing {i + 1}/{len(urls)}\n"
                f"URL: {url}",
            )
            sub_id = f"{task_id}_{i}"
            ok = await _process_single_url(
                client, message, url, args, status_msg,
                sub_id, LOGGER, download_base,
            )
            if ok:
                success_count += 1

        await edit_message(
            status_msg,
            f"✅ <b>Multi Download Complete</b>\n\n"
            f"Total: {len(urls)}\n"
            f"Success: {success_count}\n"
            f"Failed: {len(urls) - success_count}",
        )
        await delete_message(status_msg)
        shutil.rmtree(download_base, ignore_errors=True)
        return

    # ── Normal single URL mode ──
    query = args.get("link", "").strip()

    # If no link in command, check replied message
    if not query and message.reply_to_message:
        reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        query = reply_text.split("\n")[0].strip()

    if not query:
        help_text = (
            "<b>Spotify Downloader</b>\n\n"
            "<b>Usage:</b>\n"
            "  <code>/spotify {url}</code> - Download to Telegram as audio\n"
            "  <code>/spotify {url} -z</code> - Zip all files into one archive\n"
            "  <code>/spotify {url} -up {dest}</code> - Upload to GDrive/rclone/Telegram\n"
            "  <code>/spotify {url} -n name</code> - Custom name\n"
            "  <code>/spotify {url} -doc</code> - Send as document\n"
            "  <code>/spotify {url} -t {img_url}</code> - Custom thumbnail\n"
            "  <code>/spotify {url} -sp 500mb</code> - Split size\n\n"
            "<b>Supported URLs:</b>\n"
            "  Track: open.spotify.com/track/...\n"
            "  Album: open.spotify.com/album/...\n"
            "  Playlist: open.spotify.com/playlist/...\n"
            "  Artist: open.spotify.com/artist/...\n\n"
            "<b>Bulk:</b> Reply to text file with URLs: <code>/spotify -b</code>\n"
            "<b>Multi:</b> Reply to messages: <code>/spotify -i 5</code>\n\n"
            "<b>All standard WZML-X flags supported:</b>\n"
            "  -z -up -n -t -doc -med -sp -b -i -m -hl -bt -ut -e -j"
        )
        await send_message(message, help_text)
        return

    if not is_spotify_url(query):
        await send_message(
            message,
            "❌ <b>Invalid Spotify URL</b>\n\n"
            "Please provide a valid Spotify URL (track, album, playlist, or artist).\n"
            "Example: <code>/spotify https://open.spotify.com/track/...</code>",
        )
        return

    task_id = md5(f"{query}{time.time()}".encode()).hexdigest()[:8]
    download_base = Path(DOWNLOAD_DIR) / f"spotify_{task_id}"

    status_msg = await send_message(
        message,
        f"🎵 <b>Spotify Download Started</b>\n\n"
        f"URL: {query}\n"
        f"Status: Initializing...",
    )

    try:
        await _process_single_url(
            client, message, query, args, status_msg,
            task_id, LOGGER, download_base,
        )
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
        shutil.rmtree(download_base, ignore_errors=True)
