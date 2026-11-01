"""Offline tests for plugins/helpers.py (the connection governor).

The bot core is stubbed: a fake TgClient with the same dicts and a fake
start_hclient, plus fake Mirror/YtDlp classes to wrap. What this proves is
the behaviour that matters — helpers stay down until a task needs them, come
up once, and are dropped again when the queue empties.

Run: python3 scripts/test-helpers-plugin.py
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
results = []


def check(name, condition, detail=""):
    results.append((bool(condition), name, detail))


# ── stubs ───────────────────────────────────────────────────────────────
class FakeClient:
    def __init__(self, name):
        self.name = name
        self.stopped = False

    async def stop(self):
        self.stopped = True


class FakeTgClient:
    helper_bots = {}
    helper_loads = {}
    helper_bot_clients = {}
    stream_clients = {}
    stream_loads = {}
    stream_prewarm = {}
    started = []
    streams_started = 0

    @classmethod
    async def start_stream_clients(cls):
        cls.streams_started += 1
        cls.stream_clients[0] = FakeClient("bot")
        cls.stream_clients[1] = FakeClient("stream1")
        cls.stream_loads[0] = 0
        cls.stream_loads[1] = 0
        cls.stream_prewarm = {0: True, 1: True}

    @classmethod
    async def start_hclient(cls, no, token, proxy=None):
        cls.started.append(no)
        client = FakeClient(f"hbot{no}")
        cls.helper_bots[no] = client
        cls.helper_bot_clients[token] = client


TOKENS = ["111:aaa", "222:bbb", "333:ccc"]

fake_config = types.SimpleNamespace(helper_bot_tokens=lambda: list(TOKENS))

bot_pkg = types.ModuleType("bot")
bot_pkg.LOGGER = types.SimpleNamespace(
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    debug=lambda *a, **k: None,
)
bot_pkg.task_dict = {}

pm = types.ModuleType("bot.core.plugin_manager")


class PluginInfo:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.handlers = []
        self.commands = kwargs.get("commands", [])


class PluginBase:
    async def on_load(self):
        return True

    async def on_unload(self):
        return True


pm.PluginInfo = PluginInfo
pm.PluginBase = PluginBase

core = types.ModuleType("bot.core")
core.plugin_manager = pm

config_mod = types.ModuleType("bot.core.config_manager")
config_mod.Config = fake_config
core.config_manager = config_mod

tg_client_mod = types.ModuleType("bot.core.tg_client")
tg_client_mod.TgClient = FakeTgClient
core.tg_client = tg_client_mod

mirror_mod = types.ModuleType("bot.modules.mirror_leech")


class Mirror:
    async def new_event(self):
        return "mirror-ran"


ytdlp_mod = types.ModuleType("bot.modules.ytdlp")


class YtDlp:
    async def new_event(self):
        return "ytdlp-ran"


modules_pkg = types.ModuleType("bot.modules")
modules_pkg.Mirror = Mirror
modules_pkg.YtDlp = YtDlp
modules_pkg.mirror_leech = mirror_mod
modules_pkg.ytdlp = ytdlp_mod
mirror_mod.Mirror = Mirror
ytdlp_mod.YtDlp = YtDlp

for name, module in {
    "bot": bot_pkg,
    "bot.core": core,
    "bot.core.plugin_manager": pm,
    "bot.core.config_manager": config_mod,
    "bot.core.tg_client": tg_client_mod,
    "bot.modules": modules_pkg,
    "bot.modules.mirror_leech": mirror_mod,
    "bot.modules.ytdlp": ytdlp_mod,
}.items():
    sys.modules[name] = module

spec = importlib.util.spec_from_file_location("helpers", ROOT / "plugins" / "helpers.py")
helpers = importlib.util.module_from_spec(spec)
sys.modules["helpers"] = helpers
spec.loader.exec_module(helpers)


async def main():
    # 1. config surface
    check("reads the configured tokens", helpers._tokens() == TOKENS, str(helpers._tokens()))

    # 2. stop_all clears every connection
    FakeTgClient.helper_bots = {1: FakeClient("a"), 2: FakeClient("b")}
    FakeTgClient.helper_bot_clients = {"111:aaa": FakeTgClient.helper_bots[1]}
    helpers._state["up"] = True
    closed = await helpers.stop_all("test")
    check("stop_all closes them all", closed == 2, str(closed))
    check("stop_all empties the registry", FakeTgClient.helper_bots == {})
    check("stop_all forgets the token map", FakeTgClient.helper_bot_clients == {})
    check("stop_all marks state down", helpers._state["up"] is False)

    # 3. start_all brings them up once
    FakeTgClient.started = []
    started = await helpers.start_all()
    check("start_all raises every helper", started == 3, str(started))
    check("start_all marks state up", helpers._state["up"] is True)
    FakeTgClient.started = []
    again = await helpers.start_all()
    check("start_all is idempotent", again == 3 and FakeTgClient.started == [],
          f"again={again} started={FakeTgClient.started}")

    # 4. auto off means never raising
    helpers._state["auto"] = False
    await helpers.stop_all("test")
    check("auto off does not raise", await helpers.ensure_up() == 0)
    helpers._state["auto"] = True

    # 5. hooks raise helpers before a task
    await helpers.stop_all("test")
    check("hooks install", helpers.install_hooks() is True)
    result = await Mirror().new_event()
    check("task still runs", result == "mirror-ran", str(result))
    check("task raised the helpers", helpers._state["up"] is True)
    check("ytdlp is wrapped too", await YtDlp().new_event() == "ytdlp-ran")

    # 6. idle governor drops when the queue is empty
    import time

    helpers._state["last_activity"] = time.time() - 3600
    acted = await helpers.idle_tick()
    check("idle tick drops idle helpers", acted is True and helpers._state["up"] is False)

    # 7. …but never while a task is running
    await helpers.start_all()
    bot_pkg.task_dict["x"] = object()
    helpers._state["last_activity"] = time.time() - 3600
    acted = await helpers.idle_tick()
    check("active tasks keep helpers up", acted is False and helpers._state["up"] is True)
    bot_pkg.task_dict.clear()

    # 8. governor respects auto off
    helpers._state["last_activity"] = time.time() - 3600
    helpers._state["auto"] = False
    check("auto off never drops", await helpers.idle_tick() is False)
    helpers._state["auto"] = True

    # 9. card renders the state
    card = helpers._card()
    for needle in ("Helper connections", "configured: 3", "auto: on"):
        check(f"card shows {needle!r}", needle in card, card[:120])

    # 9b. wake raises helpers AND stream clients
    await helpers.stop_all("test")
    FakeTgClient.stream_clients = {0: FakeClient("bot")}
    FakeTgClient.stream_prewarm = {}
    FakeTgClient.streams_started = 0
    result = await helpers.wake("test")
    check("wake starts helpers", result["helpers"] == 3, str(result))
    check("wake starts stream clients", result["streams"] == 1 and FakeTgClient.streams_started == 1, str(result))
    check("wake marks awake", helpers._state["awake"] is True)

    # 9c. sleep drops both but keeps the bot's own client
    result = await helpers.sleep("test")
    check("sleep drops helpers", result["helpers"] >= 1, str(result))
    check("sleep drops stream clients", result["streams"] == 1, str(result))
    check("sleep keeps the bot client", 0 in FakeTgClient.stream_clients, str(FakeTgClient.stream_clients))
    check("sleep clears the pre-warm map", FakeTgClient.stream_prewarm == {})
    check("sleep marks asleep", helpers._state["awake"] is False)

    # 10. unload puts the bot core back
    helpers.remove_hooks()
    check("hooks removed", helpers._patched is False)

    # 11. no tokens is a clean no-op
    fake_config.helper_bot_tokens = lambda: []
    plugin = helpers.HelpersPlugin()
    ok = await plugin.on_load()
    check("loads with no tokens", ok is True and helpers._tokens() == [])


asyncio.run(main())

failed = 0
for ok, name, detail in results:
    if not ok:
        failed += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
print(f"\n{len(results) - failed}/{len(results)} passed")
sys.exit(1 if failed else 0)
