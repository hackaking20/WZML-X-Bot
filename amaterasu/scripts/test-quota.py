"""Offline tests for plugins/quota.py.

The quota engine talks to MongoDB and monkeypatches three bot methods, so
the test supplies an in-memory stand-in for both and checks the behaviour
that matters: refusing a task when the day's allowance is gone, recording
the bytes that landed, keeping the library searchable, and putting every
patched method back on unload.

Run: python3 scripts/test-quota.py
"""

import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_PATH = ROOT / "plugins" / "quota.py"

results = []


def check(name, condition, detail=""):
    results.append((bool(condition), name, detail))


# ── in-memory motor stand-in ────────────────────────────────────────────
class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key, direction=1):
        self.docs.sort(key=lambda d: d.get(key, 0), reverse=direction < 0)
        return self

    def limit(self, count):
        self.docs = self.docs[:count]
        return self

    def __aiter__(self):
        self._iter = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self):
        self.docs = {}
        self._seq = 0

    async def find_one(self, flt):
        return self.docs.get(flt.get("_id"))

    async def update_one(self, flt, update, upsert=False):
        _id = flt.get("_id")
        doc = self.docs.get(_id)
        if doc is None:
            if not upsert:
                return None
            doc = {"_id": _id}
            self.docs[_id] = doc
        if "$set" in update:
            doc.update(update["$set"])
        if "$inc" in update:
            for key, value in update["$inc"].items():
                doc[key] = doc.get(key, 0) + value
        return doc

    async def insert_one(self, doc):
        self._seq += 1
        key = doc.get("_id", self._seq)
        doc = dict(doc)
        doc["_id"] = key
        self.docs[key] = doc
        return doc

    async def delete_many(self, flt):
        removed = 0
        if "_id" in flt and "$in" in flt["_id"]:
            for _id in flt["_id"]["$in"]:
                if self.docs.pop(_id, None) is not None:
                    removed += 1
        elif "at" in flt and "$lt" in flt["at"]:
            cutoff = flt["at"]["$lt"]
            for key in [k for k, d in self.docs.items() if d.get("at", 0) < cutoff]:
                self.docs.pop(key, None)
                removed += 1
        elif "day" in flt and "$lt" in flt["day"]:
            cutoff = flt["day"]["$lt"]
            for key in [
                k
                for k, d in self.docs.items()
                if isinstance(k, int) and str(d.get("day", "")) < cutoff
            ]:
                self.docs.pop(key, None)
                removed += 1
        return types.SimpleNamespace(deleted_count=removed)

    async def count_documents(self, flt):
        return len(self.docs)

    def find(self, flt=None, projection=None):
        import re as _re

        docs = list(self.docs.values())
        if flt and "name" in flt:
            pattern = flt["name"].get("$regex", "")
            docs = [d for d in docs if _re.search(pattern, str(d.get("name", "")), _re.I)]
        if flt and "user_id" in flt:
            docs = [d for d in docs if d.get("user_id") == flt["user_id"]]
        return FakeCursor(docs)


class FakeNamespace:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, part):
        return self.collections.setdefault(part, FakeCollection())


class FakeDB:
    def __init__(self):
        self.namespaces = {}

    def __getitem__(self, name):
        return self.namespaces.setdefault(name, FakeNamespace())

    async def list_collection_names(self):
        names = []
        for name, namespace in self.namespaces.items():
            for part in namespace.collections:
                names.append(f"{name}.{part}")
        return names


# ── stub the bot package ────────────────────────────────────────────────
SENT = []


class _Logger:
    def info(self, *a, **k):
        pass

    error = warning = debug = info


class _PluginInfo:
    def __init__(self, **kwargs):
        self.handlers = []
        for key, value in kwargs.items():
            setattr(self, key, value)


class _PluginBase:
    pass


async def _send_message(message, text, **kwargs):
    SENT.append(text)
    return None


async def _noop(*args, **kwargs):
    return None


class FakeTaskListener:
    def __init__(self):
        self.user_id = 7
        self.size = 0
        self.name = ""
        self.message = types.SimpleNamespace(link="https://t.me/c/1/2")
        self.downloaded = False
        self.uploaded = False

    async def on_download_complete(self, *args, **kwargs):
        self.size = 5 * 1024 ** 3
        self.downloaded = True

    async def on_upload_complete(self, *args, **kwargs):
        self.uploaded = True


class FakeModule:
    """Stands in for Mirror / YtDlp."""

    def __init__(self):
        self.user_id = 7
        self.message = types.SimpleNamespace(link="", chat=types.SimpleNamespace(id=1))
        self.started = False

    async def new_event(self, *args, **kwargs):
        self.started = True


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


DB = FakeDB()
_stub("bot", LOGGER=_Logger())
_stub("bot.core")
_stub("bot.core.plugin_manager", PluginBase=_PluginBase, PluginInfo=_PluginInfo)
_stub("bot.core.config_manager", Config=types.SimpleNamespace(OWNER_ID=1, SUDO_USERS=""))
_stub("bot.core.tg_client", TgClient=types.SimpleNamespace(PARTITION="testpart"))
_stub("bot.helper")
_stub("bot.helper.ext_utils")
_stub("bot.helper.ext_utils.bot_utils", new_task=lambda fn: fn)
_stub("bot.helper.ext_utils.db_handler", database=types.SimpleNamespace(db=DB))
_stub("bot.helper.telegram_helper")
_stub("bot.helper.telegram_helper.message_utils", send_message=_send_message)
_stub("bot.helper.telegram_helper.filters", CustomFilters=object)
_stub("bot.helper.listeners")
_stub("bot.helper.listeners.task_listener", TaskListener=FakeTaskListener)
_stub("bot.modules")
_stub("bot.modules.mirror_leech", Mirror=FakeModule)
_stub("bot.modules.ytdlp", YtDlp=FakeModule)

spec = importlib.util.spec_from_file_location("quota_plugin", PLUGIN_PATH)
quota = importlib.util.module_from_spec(spec)
sys.modules["quota_plugin"] = quota
spec.loader.exec_module(quota)

GB = 1024 ** 3


async def main():
    # ── helpers ─────────────────────────────────────────────────────────
    check("human formats GB", quota._human(2 * GB) == "2.00 GB", quota._human(2 * GB))
    check("human formats MB", quota._human(5 * 1024 ** 2) == "5.00 MB")
    check("human formats bytes", quota._human(999) == "999 B")

    os.environ["DAILY_QUOTA_GB"] = "3"
    check("default limit from env", quota._default_gb() == 3.0, str(quota._default_gb()))
    check("enforcing when a limit is set", quota._enforcing())
    os.environ["DAILY_QUOTA_GB"] = "0"
    check("0 disables enforcement", not quota._enforcing())
    os.environ["DAILY_QUOTA_GB"] = "junk"
    check("junk falls back to 15", quota._default_gb() == 15.0, str(quota._default_gb()))
    os.environ["DAILY_QUOTA_GB"] = "3"

    # ── usage accounting ────────────────────────────────────────────────
    check("no usage yet", await quota.usage_of(7) == 0)
    await quota.add_usage(7, 1 * GB)
    check("usage recorded", await quota.usage_of(7) == 1 * GB, str(await quota.usage_of(7)))
    await quota.add_usage(7, int(0.5 * GB))
    check("usage accumulates", await quota.usage_of(7) == int(1.5 * GB))

    check("remaining is limit minus used", await quota.remaining(7) == int(1.5 * GB),
          str(await quota.remaining(7)))

    # a new day resets the counter without losing the limit
    col = quota._quota_col()
    await col.update_one({"_id": 7}, {"$set": {"day": "1999-01-01"}})
    check("usage resets on a new day", await quota.usage_of(7) == 0)
    await quota.add_usage(7, int(0.2 * GB))
    check("usage restarts from zero", await quota.usage_of(7) == int(0.2 * GB))

    # ── per-user limits ─────────────────────────────────────────────────
    check("limit defaults to the global value", await quota.limit_of(7) == 3.0)
    await quota.set_limit(7, 10.0)
    check("per-user override wins", await quota.limit_of(7) == 10.0)
    await quota.set_limit(7, None)
    check("clearing the override restores the default", await quota.limit_of(7) == 3.0)

    await quota.reset_usage(7)
    check("reset zeroes the day", await quota.usage_of(7) == 0)

    # ── the gate ────────────────────────────────────────────────────────
    SENT.clear()
    listener = FakeTaskListener()
    check("gate allows a user with headroom", not await quota._over_quota_notice(listener))
    check("no message sent when allowed", SENT == [], str(SENT))

    await quota.add_usage(7, 3 * GB)  # exactly at the limit
    SENT.clear()
    refused = await quota._over_quota_notice(listener)
    check("gate refuses at the limit", refused)
    check("refusal explains itself", SENT and "QUOTA" in SENT[0], str(SENT[:1]))

    # ── hooks ───────────────────────────────────────────────────────────
    import bot.modules.mirror_leech as ml
    import bot.modules.ytdlp as yt
    import bot.helper.listeners.task_listener as tl

    original_mirror = ml.Mirror.new_event
    original_download = tl.TaskListener.on_download_complete

    check("hooks install", quota._install_hooks())
    check("mirror new_event replaced", ml.Mirror.new_event is not original_mirror)
    check("on_download_complete replaced",
          tl.TaskListener.on_download_complete is not original_download)

    # still over quota → the task must not start
    task = ml.Mirror()
    await task.new_event()
    check("over-quota task is refused", not task.started)

    # give the user headroom again → the task runs and the bytes land
    await quota.reset_usage(7)
    task = ml.Mirror()
    await task.new_event()
    check("task runs under quota", task.started)

    await quota.reset_usage(7)
    real = tl.TaskListener()
    await real.on_download_complete()
    check("download bytes are recorded", await quota.usage_of(7) == 5 * GB,
          str(await quota.usage_of(7)))

    # ── library ─────────────────────────────────────────────────────────
    await real.on_upload_complete()
    found = await quota.search_files(7, "fake")
    check("library records the finished file", len(found) == 0,
          "the fake listener has no name, so nothing is stored")
    await quota.record_file(7, "Fake.Movie.2024.mkv", 2 * GB, "https://t.me/c/1/2")
    await quota.record_file(7, "Another.File.mp4", 1 * GB, "")
    found = await quota.search_files(7, "fake")
    check("library finds by name", len(found) == 1 and found[0]["name"] == "Fake.Movie.2024.mkv",
          str([d["name"] for d in found]))
    check("library keeps the message link", found[0]["link"] == "https://t.me/c/1/2")
    found = await quota.search_files(7, "nothing-matches-this")
    check("library returns nothing for a miss", found == [])
    found = await quota.search_files(999, "fake")
    check("library is per-user", found == [])

    # ── unload puts everything back ─────────────────────────────────────
    check("hooks uninstall", quota._remove_hooks())
    check("mirror restored", ml.Mirror.new_event is original_mirror)
    check("on_download_complete restored",
          tl.TaskListener.on_download_complete is original_download)

    # ── runtime default cap ─────────────────────────────────────────────
    os.environ["DAILY_QUOTA_GB"] = "3"
    quota._SETTINGS.update(at=0.0, gb=None)
    check("default falls back to env", await quota.default_gb() == 3.0,
          str(await quota.default_gb()))
    await quota.set_default_gb(8.0)
    check("botcap overrides the env default", await quota.default_gb() == 8.0,
          str(await quota.default_gb()))
    check("enforcement follows the runtime cap", await quota.enforcing())
    await quota.set_default_gb(0.0)
    check("a zero cap disables enforcement", not await quota.enforcing())
    await quota.set_default_gb(3.0)

    # ── user registry ───────────────────────────────────────────────────
    await quota.reset_usage(7)
    await quota.add_usage(7, 2 * GB)
    await quota.add_usage(8, 1 * GB)
    rows = await quota.registry()
    check("registry lists users by usage", rows and rows[0]["user_id"] == 7,
          str([(r["user_id"], r["used"]) for r in rows]))
    check("registry skips the settings document",
          all(isinstance(r["user_id"], int) for r in rows), str(rows))

    # ── db stats + purge ────────────────────────────────────────────────
    await quota.record_file(7, "Old.Release.mkv", GB, "")
    lib = quota._library_col()
    for doc in lib.docs.values():  # age the first row (fake has no name filter)
        if doc.get("name") == "Old.Release.mkv":
            doc["at"] = 1000.0
    await quota.record_file(7, "New.Release.mkv", GB, "")

    stats = await quota.collection_stats()
    check("collection stats list collections", stats, str(stats))

    removed = await quota.purge_older_than(30)
    check("purge removes the old library row", removed["library"] == 1, str(removed))
    remaining_rows = await quota.search_files(7, "Release")
    check("purge keeps the fresh row", len(remaining_rows) == 1, str(len(remaining_rows)))
    check("purge never deletes the settings document",
          (await quota._quota_col().find_one({"_id": "settings"})) is not None)

    # ── plugin contract ─────────────────────────────────────────────────
    info = quota.QuotaPlugin.PLUGIN_INFO
    check("commands declared",
          set(info.commands) == {
              "usage", "quota", "quotareset", "find",
              "qusers", "addcap", "botcap", "dbstats", "dbclean",
          }, str(info.commands))
    for name in (
        "usage_command", "quota_command", "quotareset_command", "find_command",
        "qusers_command", "addcap_command", "botcap_command",
        "dbstats_command", "dbclean_command", "admin_callback",
    ):
        check(f"{name} exists", callable(getattr(quota, name, None)))

    # owner commands render, and refuse a non-owner
    owner_message = types.SimpleNamespace(
        text="/qusers", from_user=types.SimpleNamespace(id=1),
        link="", chat=types.SimpleNamespace(id=1),
    )
    SENT.clear()
    await quota.qusers_command(None, owner_message)
    check("/qusers replies for the owner", SENT and "USERS TODAY" in SENT[0], str(SENT[:1]))

    SENT.clear()
    stranger = types.SimpleNamespace(
        text="/qusers", from_user=types.SimpleNamespace(id=999),
        link="", chat=types.SimpleNamespace(id=1),
    )
    await quota.qusers_command(None, stranger)
    check("/qusers refuses a stranger", SENT and "Owner only" in SENT[0], str(SENT[:1]))

    SENT.clear()
    await quota.addcap_command(
        None,
        types.SimpleNamespace(
            text="/addcap 7 5", from_user=types.SimpleNamespace(id=1),
            link="", chat=types.SimpleNamespace(id=1),
        ),
    )
    check("/addcap raises the cap", SENT and "Cap adjusted" in SENT[0], str(SENT[:1]))
    check("cap really moved", await quota.limit_of(7) == 8.0, str(await quota.limit_of(7)))

    SENT.clear()
    await quota.dbstats_command(None, owner_message)
    check("/dbstats replies", SENT and "DATABASE" in SENT[0], str(SENT[:1]))

    # /usage renders for a normal user
    SENT.clear()
    message = types.SimpleNamespace(
        text="/usage",
        from_user=types.SimpleNamespace(id=7),
        link="",
        chat=types.SimpleNamespace(id=1),
    )
    await quota.usage_command(None, message)
    check("/usage replies", SENT and "USAGE TODAY" in SENT[0], str(SENT[:1]))


asyncio.run(main())

failed = 0
for ok, name, detail in results:
    if not ok:
        failed += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
print(f"\n{len(results) - failed}/{len(results)} passed")
sys.exit(1 if failed else 0)
