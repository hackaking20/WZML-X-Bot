"""Music catalogue downloader + lyrics grabber for Amaterasu.

Ported from the WZFIX music stack that ships inside vot1122/Kaggle-auto
(bot/helper/wzfix/r3_music.py + r4_music_cmds.py), rewritten as a
self-contained Amaterasu plugin. The provider endpoints and the catalogue
assembly logic come from that code; the download path does not — WZFIX
re-dispatched everything through the bot's own task pipeline, whereas this
plugin fetches audio itself with yt-dlp and uploads it, so it needs no
hooks in the bot core and cannot interfere with mirror/leech tasks.

Commands
    /ms <link or text>   artist / album / playlist / track, any provider
    /ld <song name>      search for a song and grab its lyrics video audio
    /msdebug             probe every provider and report what answers

What /ms accepts
    Spotify   track, album, artist, playlist
    Apple     album, playlist, song
    JioSaavn  song, album, artist
    Deezer    track, album, artist, playlist
    YouTube / SoundCloud links pass straight to yt-dlp
    plain text is searched across Deezer and JioSaavn

Catalogue discovery and audio are separate concerns, on purpose. Spotify,
Apple and Deezer hand back metadata only — none of them will give you a
full-length audio file. So the flow is: read the catalogue from whichever
provider the link points at, then fetch each track's audio from YouTube
(or a JioSaavn direct URL when the API hands one over). That is also what
WZFIX does, and it is why an artist link works for any artist on earth.

Config (env or config.py, all optional)
    SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET   real catalogue access
    MUSIC_MAX_TRACKS    default 25, hard cap 200
    MUSIC_QUALITY       default 320 (mp3 kbps)
    MUSIC_DIR           default "music_downloads"
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.handlers import CallbackQueryHandler
from pyrogram.types import CallbackQuery, Message

from bot import LOGGER
from bot.core.plugin_manager import PluginBase, PluginInfo
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)

# ─────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

_MUSIC_HOSTS = (
    "open.spotify.com",
    "spotify.com",
    "music.apple.com",
    "itunes.apple.com",
    "jiosaavn.com",
    "saavn.com",
    "deezer.com",
    "deezer.page.link",
)

_YT_HOSTS = ("youtube.com", "youtu.be", "music.youtube.com", "soundcloud.com")

# never accept these as a song title or artist (site chrome)
_STOP = {
    "jiosaavn", "saavn", "song", "songs", "home", "music", "album",
    "artist", "playlist", "download", "spotify", "deezer", "apple",
}

_FEAT_PAT = re.compile(r"\s*[(\[](?:feat\.?|ft\.?|featuring|with)\b[^)\]]*[)\]]", re.I)

_SESSIONS: Dict[str, dict] = {}
_SESSION_TTL = 3600
_PICKERS: Dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────


def _log(msg: str) -> None:
    try:
        LOGGER.info(f"[music] {msg}")
    except Exception:
        print(f"[music] {msg}")


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        val = int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        val = default
    return max(low, min(high, val))


def _max_tracks() -> int:
    return _env_int("MUSIC_MAX_TRACKS", 25, 1, 200)


def _quality() -> str:
    return str(_env_int("MUSIC_QUALITY", 320, 96, 320))


def _music_dir() -> Path:
    path = Path(os.environ.get("MUSIC_DIR", "music_downloads"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _norm(text: str) -> str:
    """Comparison key: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _host_of(url: str) -> str:
    match = re.match(r"https?://([^/]+)/", (url or "") + "/")
    return (match.group(1) if match else "").lower()


def _host_matches(host: str, candidates: Tuple[str, ...]) -> bool:
    return any(host == c or host.endswith("." + c) for c in candidates)


def is_music_url(url: str) -> bool:
    return _host_matches(_host_of(url), _MUSIC_HOSTS)


def is_yt_url(url: str) -> bool:
    return _host_matches(_host_of(url), _YT_HOSTS)


def _strip_feat(title: str) -> str:
    return _clean(_FEAT_PAT.sub("", title or ""))


def _slug_query(url: str) -> Optional[str]:
    """Search terms straight from a URL slug — the last-resort fallback."""
    try:
        path = (url or "").split("?")[0].split("#")[0]
        for seg in reversed([p for p in path.split("/") if p]):
            seg = seg.strip()
            if not seg or not re.search(r"[A-Za-z]", seg):
                continue
            if re.fullmatch(r"[0-9a-zA-Z]{10,}", seg):
                continue  # opaque id, not a name
            if re.search(r"\d", seg) and not re.search(r"[-_]", seg):
                continue  # short opaque token (jiosaavn ABC123)
            return seg.replace("-", " ").replace("_", " ").strip()
    except Exception:
        pass
    return None


def _get_json(url: str, headers: Optional[dict] = None, timeout: float = 15.0):
    """Blocking JSON GET. Callers run it in a thread."""
    request = urllib.request.Request(url, headers=headers or _UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


async def _ajson(url: str, headers: Optional[dict] = None, timeout: float = 15.0):
    return await asyncio.to_thread(_get_json, url, headers, timeout)


async def _aget_text(url: str, timeout: float = 15.0) -> str:
    def _read():
        request = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")

    return await asyncio.to_thread(_read)


@dataclass
class Track:
    artist: str
    title: str
    album: str = ""
    duration: int = 0
    direct_url: str = ""  # a real audio file, when a provider hands one over

    @property
    def query(self) -> str:
        return _clean(f"{self.artist} - {self.title}")

    @property
    def label(self) -> str:
        return self.query if self.artist else self.title


@dataclass
class Catalogue:
    title: str
    source: str
    tracks: List[Track] = field(default_factory=list)
    note: str = ""


# ─────────────────────────────────────────────────────────────────────────
# Deezer — public API, no auth, best for international catalogues
# ─────────────────────────────────────────────────────────────────────────

_DEEZER = "https://api.deezer.com"


def _deezer_track(item: dict, album: str = "", fallback_artist: str = "") -> Track:
    return Track(
        artist=_clean((item.get("artist") or {}).get("name") or "") or fallback_artist,
        title=_strip_feat(_clean(item.get("title") or "")),
        album=album or _clean((item.get("album") or {}).get("title") or ""),
        duration=int(item.get("duration") or 0),
    )


async def deezer_search_artist(name: str) -> Optional[dict]:
    data = await _ajson(f"{_DEEZER}/search/artist?q={urllib.parse.quote(name)}&limit=10")
    best = None
    for artist in data.get("data") or []:
        if _norm(artist.get("name")) != _norm(name):
            continue
        fans = int(artist.get("nb_fan") or 0)
        if best is None or fans > best[1]:
            best = (artist, fans)
    return best[0] if best else None


async def deezer_artist_catalogue(name: str, limit: int) -> List[Track]:
    """Top tracks first, then newest albums until the limit is reached."""
    artist = await deezer_search_artist(name)
    if not artist:
        return []
    aid = artist["id"]
    tracks: List[Track] = []
    seen = set()

    def _take(items, album=""):
        for item in items:
            if len(tracks) >= limit:
                return
            track = _deezer_track(item, album, name)
            if not track.title:
                continue
            key = _norm(f"{track.artist} {track.title}")
            if key in seen:
                continue
            seen.add(key)
            tracks.append(track)

    try:
        top = await _ajson(f"{_DEEZER}/artist/{aid}/top?limit=50")
        _take(top.get("data") or [])
    except Exception as error:
        _log(f"deezer top failed: {error}")

    albums_used = 0
    try:
        albums = await _ajson(f"{_DEEZER}/artist/{aid}/albums?limit=100")
    except Exception as error:
        _log(f"deezer albums failed: {error}")
        return tracks

    for album in albums.get("data") or []:
        if len(tracks) >= limit or albums_used >= 60:
            break
        albums_used += 1
        await asyncio.sleep(0.6)
        try:
            album_tracks = await _ajson(f"{_DEEZER}/album/{album['id']}/tracks")
        except Exception:
            continue
        _take(album_tracks.get("data") or [], _clean(album.get("title") or ""))
    return tracks


async def deezer_album_catalogue(album_id: str) -> Catalogue:
    meta = await _ajson(f"{_DEEZER}/album/{album_id}")
    artist = _clean((meta.get("artist") or {}).get("name") or "")
    album_name = _clean(meta.get("title") or "")
    tracks = [
        _deezer_track(item, album_name, artist)
        for item in (meta.get("tracks") or {}).get("data") or []
    ]
    return Catalogue(
        title=_clean(meta.get("title") or "Album"),
        source=f"Deezer album — {artist}",
        tracks=[t for t in tracks if t.title],
    )


async def deezer_playlist_catalogue(playlist_id: str) -> Catalogue:
    meta = await _ajson(f"{_DEEZER}/playlist/{playlist_id}")
    tracks = [
        _deezer_track(item) for item in (meta.get("tracks") or {}).get("data") or []
    ]
    return Catalogue(
        title=_clean(meta.get("title") or "Playlist"),
        source="Deezer playlist",
        tracks=[t for t in tracks if t.title],
    )


async def deezer_search_tracks(query: str, limit: int = 8) -> List[Track]:
    data = await _ajson(f"{_DEEZER}/search?q={urllib.parse.quote(query)}&limit={limit}")
    return [
        _deezer_track(item)
        for item in data.get("data") or []
        if _clean(item.get("title") or "")
    ]


# ─────────────────────────────────────────────────────────────────────────
# JioSaavn — the Indian catalogue, unofficial endpoint, no keys
# ─────────────────────────────────────────────────────────────────────────

_SAAVN_API = "https://www.jiosaavn.com/api.php"


def _saavn_get(call: str, **params) -> str:
    query = {
        "__call": call,
        "_format": "json",
        "_marker": "0",
        "api_version": "4",
        "ctx": "web6dot0",
        **params,
    }
    return _SAAVN_API + "?" + urllib.parse.urlencode(query)


def _saavn_primary(song: dict) -> List[dict]:
    return ((song.get("more_info") or {}).get("artistMap") or {}).get(
        "primary_artists"
    ) or []


def _saavn_track(song: dict) -> Track:
    title = _clean(song.get("title") or "")
    artist = ""
    primary = _saavn_primary(song)
    if primary:
        artist = _clean(primary[0].get("name") or "")
    if not artist:
        artist = _clean(
            (song.get("subtitle") or "").split(" - ")[0] or song.get("singers") or ""
        )
    direct = (
        (song.get("more_info") or {}).get("media_url")
        or song.get("media_url")
        or ""
    )
    return Track(
        artist=artist,
        title=_strip_feat(title),
        album=_clean(song.get("album") or ""),
        duration=int(song.get("duration") or 0),
        direct_url=direct if str(direct).startswith("http") else "",
    )


async def saavn_search(query: str, pages: int = 1) -> List[Track]:
    tracks: List[Track] = []
    seen = set()
    for page in range(1, pages + 1):
        url = _saavn_get("search.getResults", q=query, n="40", p=str(page))
        try:
            data = await _ajson(url)
        except Exception as error:
            _log(f"saavn search failed (page {page}): {error}")
            break
        results = data.get("results") or []
        if not results:
            break
        for song in results:
            track = _saavn_track(song)
            if not track.title:
                continue
            key = _norm(f"{track.artist} {track.title}")
            if key in seen:
                continue
            seen.add(key)
            tracks.append(track)
        await asyncio.sleep(0.5)
    return tracks


async def saavn_artist_catalogue(name: str, limit: int) -> List[Track]:
    """Search the artist by name, keep only songs whose primary artist is
    that exact artist, and page until the limit is reached."""
    tracks: List[Track] = []
    seen = set()
    artist_ids: Dict[str, int] = {}
    first_page: List[dict] = []

    for page in range(1, 6):
        if len(tracks) >= limit:
            break
        url = _saavn_get("search.getResults", q=name, n="40", p=str(page))
        try:
            data = await _ajson(url)
        except Exception as error:
            _log(f"saavn artist page {page} failed: {error}")
            break
        results = data.get("results") or []
        if not results:
            break
        if page == 1:
            first_page = results
            for song in results:
                for primary in _saavn_primary(song):
                    if _norm(primary.get("name")) == _norm(name):
                        aid = str(primary.get("id") or "")
                        if aid:
                            artist_ids[aid] = artist_ids.get(aid, 0) + 1
            if not artist_ids:
                return []
        target = max(artist_ids, key=artist_ids.get) if artist_ids else ""
        for song in results:
            if len(tracks) >= limit:
                break
            if target and not any(
                str(p.get("id") or "") == target for p in _saavn_primary(song)
            ):
                continue
            track = _saavn_track(song)
            if not track.title:
                continue
            key = _norm(f"{name} {track.title}")
            if key in seen:
                continue
            seen.add(key)
            track.artist = track.artist or name
            tracks.append(track)
        await asyncio.sleep(0.5)
    _log(f"saavn: {len(tracks)} track(s) for {name} (pages used)")
    return tracks


# ─────────────────────────────────────────────────────────────────────────
# Spotify — metadata only. Real API with app credentials, else oEmbed.
# ─────────────────────────────────────────────────────────────────────────

_SP_TOKEN = {"at": 0.0, "token": ""}
_SPOTIFY_ID = re.compile(
    r"/(?:intl-[a-z-]+/)?(track|album|artist|playlist)/([A-Za-z0-9]{16,})"
)


def _spotify_creds() -> Optional[Tuple[str, str]]:
    cid = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
    secret = (os.environ.get("SPOTIFY_CLIENT_SECRET") or "").strip()
    if cid and secret and "PLACEHOLDER" not in cid + secret:
        return cid, secret
    return None


def _spotify_app_token(creds: Tuple[str, str]) -> str:
    import base64

    cid, secret = creds
    request = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": "Basic "
            + base64.b64encode(f"{cid}:{secret}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())["access_token"]


async def _spotify_token() -> str:
    now = time.time()
    if _SP_TOKEN["token"] and now - _SP_TOKEN["at"] < 3000:
        return _SP_TOKEN["token"]
    creds = _spotify_creds()
    if not creds:
        return ""
    try:
        token = await asyncio.to_thread(_spotify_app_token, creds)
    except Exception as error:
        _log(f"spotify app token failed: {error}")
        return ""
    _SP_TOKEN.update(at=now, token=token)
    return token


def _sp_get(url: str, token: str):
    request = urllib.request.Request(
        url,
        headers={
            **_UA,
            "Authorization": f"Bearer {token}",
            "app-platform": "WebPlayer",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


async def _sp(url: str, token: str):
    return await asyncio.to_thread(_sp_get, url, token)


async def spotify_oembed_title(url: str) -> str:
    """No-key fallback: the public oEmbed endpoint gives a display name."""
    try:
        data = await _ajson(
            "https://open.spotify.com/oembed?url=" + urllib.parse.quote(url, safe="")
        )
        return _clean(data.get("title") or "")
    except Exception as error:
        _log(f"spotify oembed failed: {error}")
        return ""


async def _spotify_artist_name(url: str) -> str:
    match = re.search(r"/artist/([A-Za-z0-9]+)", url)
    token = await _spotify_token()
    if match and token:
        try:
            data = await _sp(f"https://api.spotify.com/v1/artists/{match.group(1)}", token)
            name = _clean(data.get("name") or "")
            if name:
                return name
        except Exception as error:
            _log(f"spotify artist lookup failed: {error}")
    title = await spotify_oembed_title(url)
    # oEmbed for an artist returns just the name
    return _strip_feat(re.sub(r"\s*[|–-]\s*(Songs|Spotify).*$", "", title))


async def spotify_catalogue(url: str, limit: int) -> Optional[Catalogue]:
    """Spotify gives us names, not audio. With app credentials we read the
    real catalogue; without them we take the artist/album name from oEmbed
    and let Deezer and JioSaavn supply the tracks."""
    match = _SPOTIFY_ID.search(url)
    if not match:
        return None
    kind, spotify_id = match.group(1), match.group(2)
    token = await _spotify_token()

    if token:
        try:
            if kind == "artist":
                artist = await _sp(f"https://api.spotify.com/v1/artists/{spotify_id}", token)
                name = _clean(artist.get("name") or "")
                tracks: List[Track] = []
                seen = set()

                def _take(items, album=""):
                    for item in items:
                        if len(tracks) >= limit:
                            return
                        title = _strip_feat(_clean(item.get("name") or ""))
                        if not title:
                            continue
                        main = _clean(
                            ((item.get("artists") or [{}])[0].get("name") or name)
                        )
                        key = _norm(f"{main} {title}")
                        if key in seen:
                            continue
                        seen.add(key)
                        tracks.append(
                            Track(
                                artist=main,
                                title=title,
                                album=album,
                                duration=int((item.get("duration_ms") or 0) / 1000),
                            )
                        )

                top = await _sp(
                    f"https://api.spotify.com/v1/artists/{spotify_id}/top-tracks?market=US",
                    token,
                )
                _take(top.get("tracks") or [])
                albums_url = (
                    f"https://api.spotify.com/v1/artists/{spotify_id}/albums"
                    "?include_groups=album,single&limit=50"
                )
                albums: List[dict] = []
                for _ in range(2):
                    page = await _sp(albums_url, token)
                    albums.extend(page.get("items") or [])
                    albums_url = page.get("next")
                    if not albums_url:
                        break
                    await asyncio.sleep(1.0)
                for album in albums:
                    if len(tracks) >= limit:
                        break
                    await asyncio.sleep(0.8)
                    try:
                        album_tracks = await _sp(
                            f"https://api.spotify.com/v1/albums/{album['id']}/tracks?limit=50",
                            token,
                        )
                    except Exception:
                        continue
                    _take(album_tracks.get("items") or [], _clean(album.get("name") or ""))
                if tracks:
                    return Catalogue(
                        title=name or "Artist",
                        source="Spotify catalogue",
                        tracks=tracks,
                    )
            elif kind == "album":
                meta = await _sp(f"https://api.spotify.com/v1/albums/{spotify_id}", token)
                artist = _clean(((meta.get("artists") or [{}])[0]).get("name") or "")
                tracks = [
                    Track(
                        artist=_clean(((item.get("artists") or [{}])[0]).get("name") or artist),
                        title=_strip_feat(_clean(item.get("name") or "")),
                        album=_clean(meta.get("name") or ""),
                        duration=int((item.get("duration_ms") or 0) / 1000),
                    )
                    for item in (meta.get("tracks") or {}).get("items") or []
                ]
                return Catalogue(
                    title=_clean(meta.get("name") or "Album"),
                    source=f"Spotify album — {artist}",
                    tracks=[t for t in tracks if t.title][:limit],
                )
            elif kind == "playlist":
                meta = await _sp(
                    f"https://api.spotify.com/v1/playlists/{spotify_id}", token
                )
                tracks = []
                for item in (meta.get("tracks") or {}).get("items") or []:
                    song = item.get("track") or {}
                    if not song.get("name"):
                        continue
                    tracks.append(
                        Track(
                            artist=_clean(((song.get("artists") or [{}])[0]).get("name") or ""),
                            title=_strip_feat(_clean(song.get("name") or "")),
                            album=_clean((song.get("album") or {}).get("name") or ""),
                        )
                    )
                return Catalogue(
                    title=_clean(meta.get("name") or "Playlist"),
                    source="Spotify playlist",
                    tracks=tracks[:limit],
                )
            elif kind == "track":
                meta = await _sp(f"https://api.spotify.com/v1/tracks/{spotify_id}", token)
                artist = _clean(((meta.get("artists") or [{}])[0]).get("name") or "")
                title = _strip_feat(_clean(meta.get("name") or ""))
                if title:
                    return Catalogue(
                        title=title,
                        source="Spotify track",
                        tracks=[Track(artist=artist, title=title)],
                    )
        except Exception as error:
            _log(f"spotify catalogue failed ({kind}): {error}")

    # ── no credentials, or the API refused: names only, catalogue elsewhere
    name = await spotify_oembed_title(url)
    name = _strip_feat(re.sub(r"\s*[|–]\s*Spotify.*$", "", name))
    if not name:
        name = _slug_query(url) or ""
    if not name:
        return None
    if kind == "track":
        artist, title = name, ""
        if " - " in name:
            parts = name.split(" - ", 1)
            artist, title = parts[0], parts[1]
        return Catalogue(
            title=title or name,
            source="Spotify track (name from oEmbed)",
            tracks=[Track(artist=artist if title else "", title=title or name)],
            note="Spotify gave us only the name — audio comes from YouTube.",
        )
    if kind == "artist":
        return Catalogue(
            title=name,
            source="Spotify artist (name from oEmbed)",
            note=(
                "Spotify catalogue needs SPOTIFY_CLIENT_ID/SECRET; "
                "tracks are being resolved from Deezer and JioSaavn instead."
            ),
        )
    # album / playlist without a token: we know the name, not the contents
    return Catalogue(
        title=name,
        source=f"Spotify {kind} (name from oEmbed)",
        note=(
            f"Without Spotify app credentials only the {kind} name is "
            "readable. Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET, or "
            "send an artist link instead."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# Apple Music — embed page carries the album/playlist name
# ─────────────────────────────────────────────────────────────────────────


async def apple_catalogue(url: str, limit: int) -> Optional[Catalogue]:
    html = ""
    try:
        html = await _aget_text(url)
    except Exception as error:
        _log(f"apple page failed: {error}")
    name = ""
    match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if match:
        name = _clean(match.group(1))
    if not name:
        match = re.search(r"<title>([^<]+)</title>", html)
        if match:
            name = re.sub(r"\s*on Apple Music.*$", "", _clean(match.group(1)))
    if not name:
        name = _slug_query(url) or ""
    if not name:
        return None
    name = re.sub(r"\s*[–-]\s*(Album|Playlist|Song|Single).*$", "", name).strip()
    if "/song/" in url:
        parts = [p for p in name.split(" - ") if p]
        if len(parts) >= 2:
            return Catalogue(
                title=parts[0],
                source="Apple Music song",
                tracks=[Track(artist=parts[1], title=parts[0])],
            )
        return Catalogue(
            title=name, source="Apple Music song", tracks=[Track(artist="", title=name)]
        )
    return Catalogue(
        title=name,
        source="Apple Music (name from page)",
        note=(
            "Apple Music exposes no track list without a developer token; "
            "the album name is being looked up on Deezer and JioSaavn."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# Resolver — URL in, catalogue out
# ─────────────────────────────────────────────────────────────────────────


async def _fill_from_artist_name(cat: Catalogue, limit: int) -> Catalogue:
    """A catalogue with a title but no tracks: look the name up."""
    if cat.tracks or not cat.title:
        return cat
    name = cat.title
    notes = [cat.note] if cat.note else []
    try:
        tracks = await saavn_artist_catalogue(name, limit)
        if tracks:
            cat.tracks = tracks
            cat.source += " → JioSaavn catalogue"
            cat.note = " ".join(notes)
            return cat
    except Exception as error:
        _log(f"saavn fill failed: {error}")
        notes.append(f"JioSaavn: {error}")
    try:
        tracks = await deezer_artist_catalogue(name, limit)
        if tracks:
            cat.tracks = tracks
            cat.source += " → Deezer catalogue"
            cat.note = " ".join(notes)
            return cat
    except Exception as error:
        _log(f"deezer fill failed: {error}")
        notes.append(f"Deezer: {error}")
    cat.note = " ".join(notes)
    return cat


async def resolve(url_or_query: str, limit: int) -> Catalogue:
    text = (url_or_query or "").strip()
    if not text:
        raise ValueError("Nothing to resolve")

    if is_yt_url(text):
        return Catalogue(
            title="Direct link", source="yt-dlp", tracks=[Track(artist="", title=text)]
        )

    if is_music_url(text):
        host = _host_of(text)
        if "spotify" in host:
            cat = await spotify_catalogue(text, limit)
            if cat is None:
                raise ValueError("That Spotify link isn't a track, album, artist or playlist")
            if not cat.tracks:
                cat = await _fill_from_artist_name(cat, limit)
            return cat
        if "apple" in host:
            cat = await apple_catalogue(text, limit)
            if cat is None:
                raise ValueError("Couldn't read that Apple Music link")
            if not cat.tracks:
                cat = await _fill_from_artist_name(cat, limit)
            return cat
        if "jiosaavn" in host or "saavn" in host:
            return await _saavn_url(text, limit)
        if "deezer" in host:
            return await _deezer_url(text, limit)

    # plain text → search both catalogues and let the user pick
    return Catalogue(title=text, source="search", tracks=[])


async def _saavn_url(url: str, limit: int) -> Catalogue:
    if "/artist/" in url:
        slug = _slug_query(url) or ""
        tracks = await saavn_artist_catalogue(slug, limit) if slug else []
        return Catalogue(
            title=slug or "Artist",
            source="JioSaavn artist",
            tracks=tracks,
            note="" if tracks else "JioSaavn had no songs for that artist name.",
        )
    if "/album/" in url:
        slug = _slug_query(url) or ""
        tracks = await saavn_search(slug, pages=2) if slug else []
        return Catalogue(
            title=slug or "Album", source="JioSaavn album (via search)", tracks=tracks[:limit]
        )
    if "/song/" in url:
        slug = _slug_query(url) or ""
        tracks = await saavn_search(slug, pages=1)
        if tracks:
            return Catalogue(title=tracks[0].title, source="JioSaavn song", tracks=tracks[:1])
    slug = _slug_query(url)
    if not slug:
        raise ValueError("Couldn't read that JioSaavn link")
    tracks = await saavn_search(slug, pages=1)
    return Catalogue(title=slug, source="JioSaavn search", tracks=tracks[:limit])


async def _deezer_url(url: str, limit: int) -> Catalogue:
    match = re.search(r"/(album|playlist|track|artist)/(\d+)", url)
    if not match:
        slug = _slug_query(url)
        if not slug:
            raise ValueError("Couldn't read that Deezer link")
        tracks = await deezer_search_tracks(slug, limit)
        return Catalogue(title=slug, source="Deezer search", tracks=tracks[:limit])
    kind, deezer_id = match.group(1), match.group(2)
    if kind == "album":
        return await deezer_album_catalogue(deezer_id)
    if kind == "playlist":
        return await deezer_playlist_catalogue(deezer_id)
    if kind == "track":
        data = await _ajson(f"{_DEEZER}/track/{deezer_id}")
        track = _deezer_track(data)
        return Catalogue(title=track.title, source="Deezer track", tracks=[track])
    data = await _ajson(f"{_DEEZER}/artist/{deezer_id}")
    name = _clean(data.get("name") or "")
    tracks = await deezer_artist_catalogue(name, limit) if name else []
    return Catalogue(title=name or "Artist", source="Deezer artist", tracks=tracks)


# ─────────────────────────────────────────────────────────────────────────
# Audio acquisition
# ─────────────────────────────────────────────────────────────────────────


def _ytdlp_search_flat(query: str, count: int = 5) -> List[dict]:
    """Cheap flat search — titles and ids, no media fetched."""
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 20,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
    entries = info.get("entries") or []
    return [
        {
            "id": entry.get("id") or "",
            "title": _clean(entry.get("title") or ""),
            "duration": int(entry.get("duration") or 0),
        }
        for entry in entries
        if entry.get("id")
    ]


def _ytdlp_download_audio(
    query: str, out_dir: Path, index: int, title: str = "", artist: str = ""
) -> Optional[Path]:
    """Download one track as mp3, tagged, with cover art when available."""
    import yt_dlp

    prefix = f"{index:03d}"
    for stale in out_dir.glob(f"{prefix}_*"):
        try:
            stale.unlink()
        except OSError:
            pass

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / f"{prefix}_%(title).60s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "default_search": "ytsearch",
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 5,
        "writethumbnail": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": _quality(),
            },
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ],
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([f"ytsearch1:{query}"])

    found = sorted(out_dir.glob(f"{prefix}_*.mp3"))
    if not found:
        return None
    path = found[0]
    if title or artist:
        _retag(path, title, artist)
    return path


def _retag(path: Path, title: str, artist: str) -> None:
    """Overwrite the YouTube-derived tags with the catalogue's metadata."""
    try:
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, ID3NoHeaderError

        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
        if title:
            tags.setall("TIT2", [TIT2(encoding=3, text=title)])
        if artist:
            tags.setall("TPE1", [TPE1(encoding=3, text=artist)])
        tags.save(str(path))
    except Exception as error:  # tagging is cosmetic, never fatal
        _log(f"retag skipped: {error}")


def _zip_tracks(paths: List[Path], name: str) -> Optional[Path]:
    try:
        archive = paths[0].parent / f"{re.sub(r'[^A-Za-z0-9]+', '_', name)[:50]}.zip"
        import zipfile

        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
            for path in paths:
                zf.write(path, arcname=path.name)
        return archive
    except Exception as error:
        _log(f"zip failed: {error}")
        return None


def _cleanup(paths: List[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except OSError:
            pass
        for thumb in path.parent.glob(path.stem + ".*"):
            if thumb.suffix.lower() in {".webp", ".jpg", ".png"}:
                try:
                    thumb.unlink()
                except OSError:
                    pass


# ─────────────────────────────────────────────────────────────────────────
# Telegram plumbing
# ─────────────────────────────────────────────────────────────────────────


def _bar(done: int, total: int, width: int = 12) -> str:
    filled = int(width * done / max(total, 1))
    return "▰" * filled + "▱" * (width - filled)


def _card(cat: Catalogue, limit: int) -> str:
    count = len(cat.tracks)
    lines = [
        f"<b>♪ {cat.title}</b>",
        f"<i>{cat.source}</i>",
        "",
        f"<b>Tracks:</b> <code>{count}</code>"
        + (f" of {limit} requested" if count >= limit else ""),
    ]
    preview = cat.tracks[:5]
    for track in preview:
        lines.append(f"  ◦ {track.label[:60]}")
    if count > len(preview):
        lines.append(f"  <i>… and {count - len(preview)} more</i>")
    if cat.note:
        lines.append("")
        lines.append(f"<i>{cat.note}</i>")
    return "\n".join(lines)


def _session_key(message) -> str:
    return f"{message.chat.id}:{getattr(message.from_user, 'id', 0)}"


def _gc_sessions() -> None:
    now = time.time()
    for key in [k for k, v in _SESSIONS.items() if now - v["at"] > _SESSION_TTL]:
        _SESSIONS.pop(key, None)
    for key in [k for k, v in _PICKERS.items() if now - v["at"] > _SESSION_TTL]:
        _PICKERS.pop(key, None)


async def _send_track(client: Client, chat_id: int, path: Path, track: Track) -> None:
    thumb = None
    for candidate in path.parent.glob(path.stem + ".*"):
        if candidate.suffix.lower() in {".webp", ".jpg", ".png"}:
            thumb = str(candidate)
            break
    kwargs = {
        "chat_id": chat_id,
        "audio": str(path),
        "title": (track.title or path.stem)[:64],
        "performer": (track.artist or "Unknown")[:64],
        "file_name": f"{track.label[:60]}.mp3",
    }
    if thumb:
        kwargs["thumb"] = thumb
    if track.duration:
        kwargs["duration"] = track.duration
    try:
        await client.send_audio(**kwargs)
    except Exception as error:
        _log(f"send_audio failed ({error}); sending as document")
        kwargs.pop("thumb", None)
        await client.send_document(
            chat_id=chat_id, document=str(path), file_name=kwargs["file_name"]
        )


async def _download_all(client, status, chat_id: int, cat: Catalogue, make_zip: bool):
    """Sequential download + upload, one status message the whole way."""
    out_dir = _music_dir() / re.sub(r"[^A-Za-z0-9]+", "_", cat.title)[:40]
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(cat.tracks)
    done: List[Path] = []
    failures: List[str] = []

    for index, track in enumerate(cat.tracks, start=1):
        await edit_message(
            status,
            f"<b>♪ {cat.title}</b>\n"
            f"{_bar(index - 1, total)} <code>{index - 1}/{total}</code>\n"
            f"<i>Fetching:</i> {track.label[:70]}",
        )
        try:
            path = await asyncio.to_thread(
                _ytdlp_download_audio,
                track.query,
                out_dir,
                index,
                track.title,
                track.artist,
            )
        except Exception as error:
            _log(f"download failed for {track.label}: {error}")
            failures.append(track.label)
            continue
        if not path:
            failures.append(track.label)
            continue
        try:
            await _send_track(client, chat_id, path, track)
            done.append(path)
        except Exception as error:
            _log(f"upload failed for {track.label}: {error}")
            failures.append(track.label)

    summary = [
        f"<b>♪ {cat.title}</b>",
        f"{_bar(total, total)} <code>{len(done)}/{total}</code>",
    ]
    if failures:
        summary.append("")
        summary.append(f"<b>Failed:</b> <code>{len(failures)}</code>")
        for label in failures[:8]:
            summary.append(f"  ◦ {label[:60]}")
        if len(failures) > 8:
            summary.append(f"  <i>… and {len(failures) - 8} more</i>")

    if make_zip and len(done) > 1:
        await edit_message(status, "\n".join(summary) + "\n\n<i>Zipping…</i>")
        archive = await asyncio.to_thread(_zip_tracks, done, cat.title)
        if archive:
            await client.send_document(
                chat_id=chat_id, document=str(archive), file_name=archive.name
            )
            try:
                archive.unlink()
            except OSError:
                pass

    await edit_message(status, "\n".join(summary))
    await asyncio.to_thread(_cleanup, done)


# ─────────────────────────────────────────────────────────────────────────
# Plugin class
# ─────────────────────────────────────────────────────────────────────────


class MusicPlugin(PluginBase):
    PLUGIN_INFO = PluginInfo(
        name="music",
        version="1.0.0",
        author="Amaterasu (ported from WZFIX / Kaggle-auto)",
        description=(
            "Download an artist, album or playlist catalogue from "
            "Spotify / Apple / Deezer / JioSaavn, plus a lyrics grabber"
        ),
        enabled=True,
        handlers=[],
        commands=["ms", "ld", "msdebug"],
        dependencies=[],
    )

    async def on_load(self) -> bool:
        self.PLUGIN_INFO.handlers.append(
            CallbackQueryHandler(
                music_callback, filters=__import__("pyrogram").filters.regex(r"^ms:")
            )
        )
        LOGGER.info("Music plugin loaded (/ms /ld /msdebug)")
        return True

    async def on_unload(self) -> bool:
        LOGGER.info("Music plugin unloaded")
        return True


# ─────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────


@new_task
async def ms_command(client: Client, message: Message):
    """/ms <spotify|apple|deezer|jiosaavn|youtube link, or a song name>"""
    parts = (message.text or "").split(None, 1)
    target = parts[1].strip() if len(parts) > 1 else ""
    if not target:
        await send_message(
            message,
            "<b>♪ Music catalogue</b>\n\n"
            "<code>/ms &lt;link&gt;</code> — artist, album, playlist or track\n"
            "<code>/ms &lt;song name&gt;</code> — search and pick\n\n"
            "<i>Spotify, Apple Music, Deezer, JioSaavn, YouTube and "
            "SoundCloud links all work.</i>",
        )
        return

    status = await send_message(message, "<i>◷ Reading the catalogue…</i>")
    limit = _max_tracks()
    try:
        catalogue = await resolve(target, limit)
    except Exception as error:
        await edit_message(status, f"<b>⚑ Couldn't read that:</b> <i>{error}</i>")
        return

    # Plain-text or unresolved: search and let the user pick a track
    if not catalogue.tracks:
        if is_music_url(target):
            await edit_message(
                status,
                _card(catalogue, limit)
                + "\n\n<b>⚑ No tracks found.</b> <i>Try the artist name as text.</i>",
            )
            return
        await _show_search_results(client, status, message, target)
        return

    _gc_sessions()
    key = _session_key(message)
    _SESSIONS[key] = {
        "at": time.time(),
        "catalogue": catalogue,
        "chat_id": message.chat.id,
    }
    buttons = __import__("pyrogram").types.InlineKeyboardMarkup(
        [
            [
                __import__("pyrogram").types.InlineKeyboardButton(
                    f"⬇ Download {len(catalogue.tracks)}", callback_data="ms:go:0"
                ),
                __import__("pyrogram").types.InlineKeyboardButton(
                    "📦 Download + zip", callback_data="ms:go:1"
                ),
            ],
            [
                __import__("pyrogram").types.InlineKeyboardButton(
                    "✖ Cancel", callback_data="ms:cancel"
                )
            ],
        ]
    )
    await edit_message(status, _card(catalogue, limit), buttons=buttons)


async def _show_search_results(client, status, message, query: str):
    """Search Deezer and JioSaavn, then offer the top matches."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    tracks: List[Track] = []
    seen = set()
    for finder in (deezer_search_tracks, saavn_search):
        try:
            found = await finder(query) if finder is deezer_search_tracks else await finder(
                query, pages=1
            )
        except Exception as error:
            _log(f"search via {finder.__name__} failed: {error}")
            continue
        for track in found:
            key = _norm(f"{track.artist} {track.title}")
            if not track.title or key in seen:
                continue
            seen.add(key)
            tracks.append(track)
        if len(tracks) >= 8:
            break

    if not tracks:
        await edit_message(
            status,
            f"<b>⚑ Nothing found for</b> <i>{query[:60]}</i>\n\n"
            "<i>Both Deezer and JioSaavn came back empty.</i>",
        )
        return

    _gc_sessions()
    pick_id = str(int(time.time() * 1000))[-8:]
    _PICKERS[pick_id] = {"at": time.time(), "tracks": tracks[:8], "chat_id": message.chat.id}

    rows = [
        [
            InlineKeyboardButton(
                f"{index}. {track.label[:44]}", callback_data=f"ms:pick:{pick_id}:{index - 1}"
            )
        ]
        for index, track in enumerate(tracks[:8], start=1)
    ]
    rows.append([InlineKeyboardButton("✖ Cancel", callback_data="ms:cancel")])
    await edit_message(
        status,
        f"<b>♪ Results for</b> <i>{query[:60]}</i>\n\n<i>Pick a track:</i>",
        buttons=InlineKeyboardMarkup(rows),
    )


@new_task
async def ld_command(client: Client, message: Message):
    """/ld <song name> — search for a song and grab its lyrics video audio."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    parts = (message.text or "").split(None, 1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if not query:
        await send_message(
            message,
            "<b>♪ Lyrics</b>\n\n"
            "<code>/ld &lt;song name&gt;</code>\n\n"
            "<i>Finds the song, downloads the audio, tags it, uploads it.</i>",
        )
        return

    status = await send_message(message, f"<i>◷ Searching for</i> <b>{query[:60]}</b><i>…</i>")
    try:
        results = await asyncio.to_thread(_ytdlp_search_flat, f"{query} lyrics", 6)
    except Exception as error:
        await edit_message(status, f"<b>⚑ Search failed:</b> <i>{error}</i>")
        return
    if not results:
        await edit_message(status, "<b>⚑ Nothing found.</b>")
        return

    _gc_sessions()
    pick_id = str(int(time.time() * 1000))[-8:]
    _PICKERS[pick_id] = {
        "at": time.time(),
        "tracks": [
            Track(
                artist="",
                title=item["title"],
                duration=item["duration"],
                direct_url=f"https://www.youtube.com/watch?v={item['id']}",
            )
            for item in results
        ],
        "chat_id": message.chat.id,
    }
    rows = [
        [
            InlineKeyboardButton(
                f"{index}. {track.title[:44]}", callback_data=f"ms:ld:{pick_id}:{index - 1}"
            )
        ]
        for index, track in enumerate(_PICKERS[pick_id]["tracks"], start=1)
    ]
    rows.append([InlineKeyboardButton("✖ Cancel", callback_data="ms:cancel")])
    await edit_message(
        status,
        f"<b>♪ Lyrics — </b><i>{query[:50]}</i>\n\n<i>Pick one:</i>",
        buttons=InlineKeyboardMarkup(rows),
    )


@new_task
async def msdebug_command(client: Client, message: Message):
    """/msdebug — probe every provider and report what answers."""
    status = await send_message(message, "<i>◷ Probing providers…</i>")
    lines = ["<b>♪ Provider health</b>", ""]

    checks = (
        ("Deezer", lambda: _ajson(f"{_DEEZER}/search/artist?q=test&limit=1")),
        ("JioSaavn", lambda: _ajson(_saavn_get("search.getResults", q="test", n="1", p="1"))),
        ("Spotify app token", _spotify_token),
        (
            "Spotify oEmbed",
            lambda: spotify_oembed_title("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"),
        ),
        ("yt-dlp search", lambda: asyncio.to_thread(_ytdlp_search_flat, "test", 1)),
    )
    for name, probe in checks:
        try:
            result = await probe()
            if name == "Spotify app token":
                ok = bool(result)
                detail = "configured" if ok else "not set (optional)"
            elif name == "Spotify oEmbed":
                ok = bool(result)
                detail = result[:40]
            elif name == "yt-dlp search":
                ok = bool(result)
                detail = f"{len(result)} result(s)" if ok else "empty"
            else:
                ok = bool(result)
                detail = "answers" if ok else "empty response"
            lines.append(f"{'✅' if ok else '❌'} <b>{name}</b> — <i>{detail}</i>")
        except Exception as error:
            lines.append(f"❌ <b>{name}</b> — <i>{str(error)[:60]}</i>")

    lines.append("")
    lines.append(
        f"<i>Max tracks: {_max_tracks()} · quality: {_quality()} kbps · "
        f"ffmpeg: {'yes' if shutil.which('ffmpeg') else 'MISSING'}</i>"
    )
    await edit_message(status, "\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────
# Callback handler
# ─────────────────────────────────────────────────────────────────────────


async def music_callback(client: Client, query: CallbackQuery):
    data = (query.data or "").split(":")
    action = data[1] if len(data) > 1 else ""

    if action == "cancel":
        await delete_message(query.message)
        await query.answer("Cancelled")
        return

    chat_id = query.message.chat.id

    if action == "go":
        key = f"{query.message.chat.id}:{getattr(query.from_user, 'id', 0)}"
        session = _SESSIONS.get(key)
        if not session:
            await query.answer("This expired — send the link again.", show_alert=True)
            return
        catalogue = session["catalogue"]
        make_zip = bool(int(data[2] if len(data) > 2 else "0"))
        _SESSIONS.pop(key, None)
        await query.answer("Starting")
        await _download_all(client, query.message, chat_id, catalogue, make_zip)
        return

    if action in {"pick", "ld"}:
        pick_id = data[2] if len(data) > 2 else ""
        index = int(data[3]) if len(data) > 3 else 0
        picker = _PICKERS.get(pick_id)
        if not picker or index >= len(picker["tracks"]):
            await query.answer("This expired — search again.", show_alert=True)
            return
        track = picker["tracks"][index]
        _PICKERS.pop(pick_id, None)
        await query.answer("Downloading")
        single = Catalogue(
            title=track.title,
            source="pick",
            tracks=[track],
        )
        await _download_all(client, query.message, chat_id, single, False)
        return

    await query.answer()
