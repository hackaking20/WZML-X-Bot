"""Offline tests for plugins/music.py.

The live providers (Deezer, JioSaavn, Spotify) are blocked by this
sandbox's egress proxy, so every network call is mocked here. What this
proves is the logic that sits between the HTTP layer and Telegram:
provider response parsing, catalogue assembly and de-duplication, the
Spotify-no-credentials fallback path, URL routing, and the rendering
helpers.

Run: python3 scripts/test-music-plugin.py
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_PATH = ROOT / "plugins" / "music.py"

results = []


def check(name, condition, detail=""):
    results.append((bool(condition), name, detail))


# ── stub the bot package so the plugin can be imported standalone ────────
def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class _PluginInfo:
    def __init__(self, **kwargs):
        self.handlers = []
        for key, value in kwargs.items():
            setattr(self, key, value)


class _PluginBase:
    pass


async def _noop(*args, **kwargs):
    return None


class _Logger:
    def info(self, *a, **k):
        pass

    error = warning = debug = info


_stub("bot", LOGGER=_Logger())
_stub("bot.core")
_stub("bot.core.plugin_manager", PluginBase=_PluginBase, PluginInfo=_PluginInfo)
_stub("bot.helper")
_stub("bot.helper.ext_utils")
_stub("bot.helper.ext_utils.bot_utils", new_task=lambda fn: fn)
_stub("bot.helper.telegram_helper")
_stub(
    "bot.helper.telegram_helper.message_utils",
    send_message=_noop,
    edit_message=_noop,
    delete_message=_noop,
)

spec = importlib.util.spec_from_file_location("music_plugin", PLUGIN_PATH)
music = importlib.util.module_from_spec(spec)
sys.modules["music_plugin"] = music
spec.loader.exec_module(music)


# ── fixtures ────────────────────────────────────────────────────────────
DEEZER_RESPONSES = {
    "search/artist?q=Arijit%20Singh": {
        "data": [
            {"name": "Arijit Singh", "id": 123, "nb_fan": 9000},
            {"name": "Arijit Singh Tribute", "id": 999, "nb_fan": 5},
        ]
    },
    "artist/123/top": {
        "data": [
            {"title": "Kesariya", "artist": {"name": "Arijit Singh"}, "duration": 268},
            {"title": "Tum Hi Ho (feat. Someone)", "artist": {"name": "Arijit Singh"}},
        ]
    },
    "artist/123/albums": {"data": [{"id": 55, "title": "Brahmastra"}]},
    "album/55/tracks": {
        "data": [{"title": "Deva Deva", "artist": {"name": "Arijit Singh"}}, {"title": "Kesariya"}]
    },
    "album/55": {
        "title": "Brahmastra",
        "artist": {"name": "Arijit Singh"},
        "tracks": {"data": [{"title": "Deva Deva", "artist": {"name": "Arijit Singh"}}]},
    },
    "track/55": {
        "title": "Kesariya",
        "artist": {"name": "Arijit Singh"},
        "duration": 268,
    },
    "search?q=kesariya": {
        "data": [{"title": "Kesariya", "artist": {"name": "Arijit Singh"}}]
    },
}

SAAVN_PAGES = {
    1: {
        "results": [
            {
                "title": "Kesariya",
                "more_info": {"artistMap": {"primary_artists": [{"id": "9", "name": "Arijit Singh"}]}},
            },
            {
                "title": "Some Other Song",
                "more_info": {"artistMap": {"primary_artists": [{"id": "77", "name": "Someone Else"}]}},
            },
        ]
    },
    2: {
        "results": [
            {
                "title": "Apna Bana Le",
                "more_info": {"artistMap": {"primary_artists": [{"id": "9", "name": "Arijit Singh"}]}},
            }
        ]
    },
}


def fake_json(url, headers=None, timeout=15.0):
    for fragment, payload in DEEZER_RESPONSES.items():
        if fragment in url:
            return payload
    if "jiosaavn" in url:
        page = 1
        if "&p=2" in url:
            page = 2
        elif "&p=3" in url:
            return {"results": []}
        return SAAVN_PAGES.get(page, {"results": []})
    raise AssertionError(f"unexpected url: {url}")


async def fake_oembed(url):
    if "/artist/" in url:
        return "Arijit Singh"
    if "/album/" in url:
        return "Brahmastra"
    return "Kesariya"


async def fake_text(url, timeout=15.0):
    return '<meta property="og:title" content="Brahmastra - Album by Arijit Singh">'


music._get_json = fake_json
music.spotify_oembed_title = fake_oembed
music._aget_text = fake_text
music._SP_TOKEN.update(at=0.0, token="")


async def main():
    # ── pure helpers ────────────────────────────────────────────────────
    check("music URL detected", music.is_music_url("https://open.spotify.com/artist/abc123"))
    check("deezer URL detected", music.is_music_url("https://www.deezer.com/album/55"))
    check("plain text is not a music URL", not music.is_music_url("kesariya song"))
    check("youtube detected", music.is_yt_url("https://youtu.be/xyz"))
    check("slug from URL", music._slug_query("https://www.jiosaavn.com/song/kesariya/ABC123") == "kesariya",
          music._slug_query("https://www.jiosaavn.com/song/kesariya/ABC123"))
    check("feat. stripped", music._strip_feat("Tum Hi Ho (feat. Someone)") == "Tum Hi Ho",
          music._strip_feat("Tum Hi Ho (feat. Someone)"))
    check("bar renders full", music._bar(5, 5) == "▰" * 12)

    # ── Deezer catalogue ────────────────────────────────────────────────
    tracks = await music.deezer_artist_catalogue("Arijit Singh", 10)
    titles = [t.title for t in tracks]
    check("deezer picks the exact artist", all(t.artist == "Arijit Singh" for t in tracks),
          str([(t.artist, t.title) for t in tracks]))
    check("deezer takes top tracks then albums", "Kesariya" in titles and "Deva Deva" in titles, str(titles))
    check("deezer de-duplicates", titles.count("Kesariya") == 1, str(titles))
    check("deezer strips feat", "Tum Hi Ho" in titles, str(titles))

    limited = await music.deezer_artist_catalogue("Arijit Singh", 1)
    check("deezer respects the limit", len(limited) == 1, str(len(limited)))

    # ── JioSaavn catalogue ──────────────────────────────────────────────
    saavn = await music.saavn_artist_catalogue("Arijit Singh", 10)
    saavn_titles = [t.title for t in saavn]
    check("saavn keeps only the matching primary artist",
          "Some Other Song" not in saavn_titles, str(saavn_titles))
    check("saavn pages until the limit", len(saavn) >= 2, str(saavn_titles))

    unknown = await music.saavn_artist_catalogue("Nobody At All", 10)
    check("saavn returns nothing for an unknown artist", unknown == [], str(unknown))

    # ── Spotify without credentials ─────────────────────────────────────
    cat = await music.spotify_catalogue("https://open.spotify.com/artist/4uLU6hMCjMI75M1A2tKUQC", 10)
    check("spotify artist without creds keeps the name", cat and cat.title == "Arijit Singh",
          cat.title if cat else "None")
    check("spotify artist without creds has no tracks yet", cat and cat.tracks == [])

    filled = await music._fill_from_artist_name(cat, 10)
    check("name is filled from a catalogue provider", len(filled.tracks) >= 2,
          f"{len(filled.tracks)} tracks via {filled.source}")

    album = await music.spotify_catalogue("https://open.spotify.com/album/1ATL5GLyefJaxhQzSPVrLX", 10)
    check("spotify album without creds explains itself",
          album and "SPOTIFY_CLIENT_ID" in album.note, album.note if album else "None")

    # ── resolve() routing ───────────────────────────────────────────────
    deezer_album = await music.resolve("https://www.deezer.com/album/55", 10)
    check("deezer album route", deezer_album.title == "Brahmastra" and deezer_album.tracks,
          f"{deezer_album.title} / {len(deezer_album.tracks)}")

    deezer_track = await music.resolve("https://www.deezer.com/track/55", 10)
    check("deezer track route falls back to album fixture",
          deezer_track.source in {"Deezer track", "Deezer search"}, deezer_track.source)

    apple = await music.resolve("https://music.apple.com/us/album/brahmastra/123", 10)
    check("apple route reads the page title", apple.title == "Brahmastra", apple.title)

    saavn_url = await music.resolve("https://www.jiosaavn.com/song/kesariya/ABC123", 10)
    check("jiosaavn song route finds the song",
          saavn_url.tracks and saavn_url.tracks[0].title == "Kesariya",
          str([t.title for t in saavn_url.tracks]))

    text = await music.resolve("kesariya", 10)
    check("plain text routes to search", text.source == "search" and text.tracks == [])

    yt = await music.resolve("https://youtu.be/abcdefghijk", 10)
    check("youtube link goes straight to yt-dlp", yt.source == "yt-dlp")

    # ── rendering + zip ─────────────────────────────────────────────────
    card = music._card(filled, 10)
    check("card shows the title and track count", "Arijit Singh" in card and "Tracks:" in card)
    check("card previews tracks", "◦" in card)

    tmp = Path("/tmp/music_test_zip")
    tmp.mkdir(exist_ok=True)
    (tmp / "001_a.mp3").write_bytes(b"x")
    (tmp / "002_b.mp3").write_bytes(b"y")
    archive = music._zip_tracks(sorted(tmp.glob("*.mp3")), "Arijit Singh")
    check("zip created", archive is not None and archive.exists() and archive.stat().st_size > 0,
          str(archive))
    import zipfile

    with zipfile.ZipFile(archive) as zf:
        check("zip contains both tracks", len(zf.namelist()) == 2, str(zf.namelist()))

    # ── limits from env ─────────────────────────────────────────────────
    import os

    os.environ["MUSIC_MAX_TRACKS"] = "999"
    check("track cap clamps to 200", music._max_tracks() == 200, str(music._max_tracks()))
    os.environ["MUSIC_MAX_TRACKS"] = "junk"
    check("junk limit falls back to 25", music._max_tracks() == 25, str(music._max_tracks()))
    os.environ.pop("MUSIC_MAX_TRACKS", None)

    # ── plugin contract ─────────────────────────────────────────────────
    info = music.MusicPlugin.PLUGIN_INFO
    check("plugin declares its commands", set(info.commands) == {"ms", "ld", "msdebug"},
          str(info.commands))
    for name in ("ms_command", "ld_command", "msdebug_command"):
        check(f"{name} exists", callable(getattr(music, name, None)))


asyncio.run(main())

failed = 0
for ok, name, detail in results:
    if not ok:
        failed += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
print(f"\n{len(results) - failed}/{len(results)} passed")
sys.exit(1 if failed else 0)
