# Moving to a second account without breaking the first

For deploying this harness onto an account that **already runs a working instance**. The order matters: most of the ways this goes wrong are collisions, not bugs.

---

## 1. The hard constraint: one bot token, one process

Telegram allows exactly one `getUpdates` consumer per bot. Two processes on the same token produce `409 Conflict`, and both start dropping updates intermittently — the symptom is a bot that answers some messages and silently ignores others, which is maddening to debug.

So the new deployment needs **a different bot**, from BotFather. Consequences that follow automatically:

| Because the bot id differs… | …this happens |
|---|---|
| `db_partition_id(bot_id)` hashes the token prefix | New partition `p_…` — an empty database view. Your users, settings, quota history and library are **not** visible to the new bot |
| Mongo restore runs against the new partition | `cookies/<uid>/cookies.txt` is not restored, so YouTube will bot-check until you upload cookies again |
| Pages derives owner/repo from its own URL | New repo means a new hub URL; `vault.json` must be rebuilt or copied |

If you want the same *content* on the new bot, copy the documents from the old partition rather than pointing both bots at one — two live bots on one partition will overwrite each other's settings on every save.

---

## 2. Secrets for the new repo

Set these on the new repository only. Never copy a secret between two live deployments.

**Required**

- `BOT_TOKEN` — the *new* bot
- `TELEGRAM_API`, `TELEGRAM_HASH` — can be the same api_id
- `OWNER_ID` — your user id
- `DATABASE_URL` — can be the same cluster; the partition keeps the data apart

**Recommended**

- `USER_SESSION_STRING` — for >2 GB leech. Generate fresh: `/app/session-generator`
- `WEB_ACCESS_PASSWORD` — for the web UI
- `WORKER_URL` + `WORKER_SECRET` — only if you run a Worker

**Optional:** `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`, `NTFY_TOPIC`

---

## 3. Repository setup

1. Create the repo, **public** (Actions minutes on private repos are 2,000/month; a 5-hourly bot is ~43,000).
2. Unzip `amaterasu-repo.zip` at the root, commit.
3. `permissions: contents: write` is already in `amaterasu.yml` — it needs it only if you publish the hub.
4. Give the workflow its **own** `concurrency` group. If it matches the other repo's group, the two cancel each other and neither stays up.
5. Do **not** enable Pages on this account (see 4b).

---

## 4. Being a lighter tenant

The account already carries one instance. Two full-duty instances doubles what it spends, and "disproportionate burden" is a judgement about the account, not the repo.

```yaml
on:
  schedule:
    - cron: '0 */6 * * *'      # every 6 hours instead of 5
```

dispatch with `minutes: 240` → ~67% duty instead of ~98%, with a real overnight gap.

---

## 4b. What the long-surviving deployment does differently

`hackaking20/WZML-X-Bot` has been running for months on the same 5-hourly cron. Its workflow, inspected side by side:

| | Theirs | Ours |
|---|---|---|
| Commits back to the repo | **none** — repo frozen since 7 Sept | `tunnel.json` every run, ~5 commits/day |
| GitHub Pages | **not used** | hub published on github.io |
| Bot connections | one `BOT_TOKEN`; session/helpers via bot config | 15 helper bots + 15-connection stream pool |
| Runtime | built into a Docker image, `docker run --net=host` | installed on the runner directly |
| Workflow count | one | three (bot, tests, vault) |
| Duty cycle | ~90%, with a visible overnight gap | ~98%, no gap |

The three that plausibly matter, in order:

1. **No machine activity in the repo.** A repository whose only commits come from a bot, five times a day, reads as automated. A frozen repo with a cron looks like a person's project that happens to run.
2. **No Pages site.** Publishing a hub that lists a bot's pages puts a service front-end on GitHub's own hosting. Not against the rules by itself, but surface the surviving repo does not have.
3. **Sixteen fewer persistent connections.** One bot token and one stream pool is a modest footprint; sixteen concurrent Telegram clients from a single runner IP is not.

The rest is discretion. Identical behaviour survives on one account and dies on another — there is a documented case of an account suspended because of a *DNS name* an action contacted, and others cleared as false positives within a day.

---

## 4c. Helper connections: raise on demand, drop when idle

Amaterasu connects every helper in `HELPER_TOKENS` at boot and holds them for the life of the process. On a shared runner that is one persistent Telegram session per helper, all day, doing nothing between uploads.

`plugins/helpers.py` inverts that:

- helpers stay **down** at boot
- they are raised when a task actually starts (`Mirror` / `YtDlp` hooks)
- they are dropped again after `HELPER_IDLE_MINUTES` with an empty queue (default 10)
- it never drops while a task is running, and every operation is best-effort

```
/helpers              status card — bring up, drop, toggle auto
HELPER_AUTO=0         leave the stock behaviour alone
HELPER_IDLE_MINUTES   idle window before dropping (10)
```

If you would rather have no helpers at all, clear `HELPER_TOKENS` in Mongo (or leave the secret unset). The bot then runs on its own connection and the plugin stays dormant — the quietest option, and the one the surviving deployment appears to use.

Note the trade-off: raising helpers takes a second or two at the start of the first task, and upload parallelism is lower while they are down. That is the price of not holding sixteen sessions open.

---

## 4d. The quiet profile

Drop this into the workflow `env:` block (or a `quiet.env`) for a deployment that should be as unremarkable as possible:

```bash
# connections
HELPER_AUTO=1                 # raise helpers only while a task runs
HELPER_IDLE_MINUTES=10

# engines: fewer moving parts, much lower CPU and RAM
DISABLE_TORRENTS=True
DISABLE_NZB=True
DISABLE_JD=True
DISABLE_ENCODE=True

# concurrency
BOT_MAX_TASKS=2
USER_MAX_TASKS=1
UPLOAD_PARALLELISM=1
DIRECT_PARALLELISM=1
FILETOLINK_GETFILE_CONCURRENCY=4

# disk
DAILY_QUOTA_GB=10
WEBDL_MAX_GB=4
WEBDL_TTL=4

# nothing writes back to the repo
PAGES_PUBLISH=0
```

---

## 5. First-run checks, in order

1. Setup step logs `[setup] path patch verified: DOWNLOAD_DIR = "…/app/downloads/"` — if that line is missing, the path patch didn't apply and **every download will fail**.
2. `[harness] preflight OK` — the credential sanity check.
3. `[helpers] loaded — N helper(s), auto=True` (or "no helper tokens configured").
4. Bot answers `/start` as the new bot.
5. `/status` shows aria2 and qBittorrent up.
6. `/mirror <direct link>` completes. This is the test that proves the download path.
7. `/msdebug` — provider reachability.
8. Upload cookies via `/us` → *YT Cookie File*, then retry a YouTube link.
9. `/usage` reports bytes (proves Mongo writes to the new partition).

If step 6 fails with `Download aborted` and `0B`, it is the path patch, every time.

---

## 6. What to leave alone on the old account

- Don't disable or edit the existing repo or workflow — a working instance is worth more than a tidy one.
- Don't rotate the api_id/api_hash, or you break both at once.
- Don't point the new repo's Pages at the old repo's `tunnel.json`.

---

## 7. When the second one goes down too

It will, eventually, for the same reason as the first: the clause is about the workload. Keep the repo as code and tests, and move the runtime to a host that permits it — Oracle Always Free if a card is possible, FPS.ms 2 GB at €3.49/mo if not. The repo, the plugins and the web UI all work unchanged; only `scripts/setup-runner.sh` is runner-specific.
