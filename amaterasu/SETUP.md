# Amaterasu on GitHub Actions — full setup guide

Everything below is written for the repo you already have (`toqolufabo63-ui/amaterasu-runner`), but it works from zero if you ever rebuild it. Follow it in order; each step tells you how to know it worked before moving on.

---

## 0. What you are actually running

Five pieces, and it helps to know which one is failing when something goes wrong:

```
   Telegram  ──────────────►  Amaterasu bot process (GitHub runner)
                                    │
   Browser ──► Cloudflare Worker ──►│ gunicorn web server :8080
               (optional, stable    │   ├── /webdl   browser downloader
                URL + password)     │   ├── /watch   player / FileToLink
                                    │   └── /app/*   admin pages
                                    │
                                    ├── yt-dlp + ffmpeg  (music, webdl, leech)
                                    ├── aria2c / qbittorrent-nox  (torrents)
                                    └── MongoDB Atlas   (all state that survives)
```

The runner itself is disposable. Everything that persists — your settings, users, quota usage, download library — lives in MongoDB. That is why the bot can die every five hours and come back as if nothing happened.

---

## 1. Accounts you need

| Account | Why | Cost |
|---|---|---|
| GitHub | runs the bot | free for public repos |
| Telegram [@BotFather](https://t.me/BotFather) | the bot token | free |
| [my.telegram.org](https://my.telegram.org) → API development tools | `api_id` / `api_hash` | free |
| [MongoDB Atlas](https://cloud.mongodb.com) | persistence | free M0 tier is enough |
| [Cloudflare](https://dash.cloudflare.com) (optional) | stable URL for the web UI | free |

---

## 2. Create the repository

If you are starting fresh:

```bash
unzip amaterasu-actions.zip && cd amaterasu-actions
git init && git add -A && git commit -m "Amaterasu on Actions"
git branch -M main
git remote add origin https://github.com/<you>/amaterasu-runner.git
git push -u origin main
```

**The repo must be public.** A run every 5 hours is roughly 43,000 minutes a month; private repos get 2,000 free minutes and you would burn through them in under two days. Secrets are not exposed by being in a public repo — they live in Actions secrets, which are write-only and never printed.

**Check:** the repo page shows the workflow under the Actions tab, named *Amaterasu (ephemeral runner)*.

---

## 3. Set up MongoDB

1. Create a free **M0** cluster.
2. Database Access → add a user with a password. If the password has `@ : / ?` in it, percent-encode those characters in the URI.
3. Network Access → add `0.0.0.0/0`. This is not laziness: every Actions run gets a different IP, so an allowlist will lock the bot out of its own database.
4. Copy the connection string: `mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority`

**Check:** you can connect with `mongosh "<uri>"` or MongoDB Compass.

---

## 4. Add the secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**.

Required:

| Secret | Where it comes from |
|---|---|
| `BOT_TOKEN` | BotFather, looks like `123456789:AAH...` |
| `TELEGRAM_API` | the numeric `api_id` |
| `TELEGRAM_HASH` | the 32-character `api_hash` |
| `OWNER_ID` | your numeric Telegram id, from [@userinfobot](https://t.me/userinfobot) |
| `DATABASE_URL` | the Atlas URI from step 3 |

Strongly recommended:

| Secret | Why |
|---|---|
| `USER_SESSION_STRING` | leech files over 2 GB, and the user-session streaming fallback |
| `WEB_ACCESS_PASSWORD` | protects the web UI and FileToLink |
| `HELPER_TOKENS` | comma-separated extra bot tokens for parallel uploads |
| `LOG_CHAT_ID` | a channel id where task logs go |

Optional, covered in later steps: `WORKER_URL`, `WORKER_SECRET`, `NTFY_TOPIC`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`.

**Check:** all five required secrets appear in the list (values are hidden — that is normal).

---

## 5. First run

Actions → *Amaterasu (ephemeral runner)* → **Run workflow** → set `minutes` to `290` → run.

Expect roughly **17–18 minutes** before the bot is online, almost all of it `apt-get` installing ffmpeg and qBittorrent on a bare runner. The log tells you where it is:

```
[setup] installing apt packages          ← the slow part
[setup] installing cloudflared
[setup] plugins copied: music.py quota.py speedtest_plugin.py
[setup] plugin autoload patched into bot/__main__.py
[setup] web modules registered in web/wserver.py: webdl
[setup] smoke test OK — WZGram 3.1.5, imports clean
[harness 09:12:44] attempt 1: starting bot with 16500s of budget left
[harness 09:13:10] tunnel URL is https://something-random.trycloudflare.com
```

**Check:** the run is green, and the tunnel line appears. If the smoke test fails, the run stops there — that means a dependency broke upstream, and the log names it.

---

## 6. Verify in Telegram

Send these to your bot, in order:

1. `/start` — the bot answers. If it doesn't, the token is wrong or the bot is still booting.
2. `/status` — engines, disk, uptime. qBittorrent and aria2c should show as available.
3. `/msdebug` — the music providers. You want green ticks on Deezer, JioSaavn and yt-dlp search. Spotify will show "not set (optional)" until step 8.
4. `/usage` — your quota card. If it says "quota disabled", `DAILY_QUOTA_GB` is 0 or Mongo isn't connected.
5. `/plugins` — Music and Quota should already be **loaded** (the setup script autoloads them). If they show as available-but-not-loaded, the autoload patch didn't apply — check the setup log for `plugin autoload patched`.

Then a real task: mirror something small (a 10 MB direct link) with `/mirror <url>`. That exercises download, upload and the quota recorder in one go. `/usage` afterwards should show the bytes.

---

## 7. The web side

Without a Worker, your URL is the `trycloudflare.com` hostname in the log, and **it changes on every boot** (every five hours). That is fine for poking around, useless for bookmarking.

### Optional but worth doing: the Cloudflare Worker

1. Cloudflare dashboard → Workers & Pages → Create → Worker → paste `cloudflare-worker/worker.js` → Deploy.
2. Storage & Databases → KV → create a namespace → bind it to the Worker as `TUNNEL_KV`.
3. Worker → Settings → Variables → add secret `TUNNEL_SECRET` (any long random string) and, if you want a login gate, plain variable `PASS`.
4. Copy the Worker URL (`https://<name>.<subdomain>.workers.dev`) and add two GitHub secrets: `WORKER_URL` and `WORKER_SECRET` (same value as `TUNNEL_SECRET`).

From the next run on, `run-bot.sh` notices the new tunnel hostname and POSTs it to `/update-tunnel`, so the Worker URL always points at the live bot.

**Check:** open `https://<worker>/tunnel-status` — it should show the current tunnel URL and `"reachable": true`.

### The pages

| URL | What |
|---|---|
| `/webdl` | paste a link, the bot fetches it, the file downloads to your browser |
| `/watch/<token>` | FileToLink player — generate links with `/link` in Telegram |
| `/app/files` | file selector for torrents |
| `/app/encode-profiles` | FFmpeg encode presets |
| `/app/merge-plan` | arrange split video parts for merging |
| `/app/session-generator` | mint a `USER_SESSION_STRING` |
| `/app/token-generator` | Google Drive OAuth token |
| `/qbit/` `/nzb/` | qBittorrent and SABnzbd web UIs |

Everything except the watch/download links sits behind `/login` when `LOGIN_PASS` is set — and `/webdl` reuses that same cookie, so one login covers both.

**Check:** `/webdl` loads, and pasting a YouTube link produces a progress bar and then a download button. If you get redirected to `/login`, that is the gate working; log in with `LOGIN_PASS`.

---

## 8. Turning on the optional pieces

### Spotify catalogues (full artist discographies)

Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard), then add `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` as secrets. Without them `/ms <spotify artist>` still works — it reads the name from oEmbed and builds the catalogue from JioSaavn and then Deezer. With them you also get album and playlist links read in full.

### Quota tuning

| Variable | Default | Set it as |
|---|---|---|
| `DAILY_QUOTA_GB` | 15 | repo *variable* (Settings → Variables) |
| `QUOTA_ENFORCE` | true | variable |
| `MUSIC_MAX_TRACKS` | 25 | variable |
| `WEBDL_MAX_GB` | 8 | variable |

You can also change the global cap at runtime with `/botcap <gb>` — that is stored in Mongo and survives restarts, unlike the env vars.

**Disk reality check:** a runner has roughly 20–25 GB free after the toolchain. Keep `DAILY_QUOTA_GB × users` and `WEBDL_MAX_GB` under that, or set `TORRENT_LIMIT` / `DIRECT_LIMIT` in `/bs`.

### Notifications

Add `NTFY_TOPIC` (any unique string) and subscribe to `https://ntfy.sh/<topic>` in the ntfy app. You get a ping when the bot starts, when the tunnel changes, and when a run ends.

---

## 8b. Where config actually lives (and what you can keep in Mongo)

Three layers are applied in this order, so the last one wins:

1. `config.py` in the checkout — empty values are skipped
2. **MongoDB** — `settings.config`, written by every `/bs` change
3. **Environment variables** — the GitHub secrets

Because env is applied last, anything you leave in Mongo is used *as long as no env var of the same name exists*. That means you can keep `HELPER_TOKENS`, `USER_SESSION_STRING` and every `/bs` setting in the database and never put them in GitHub — which is how the bot is meant to work, and the only way to keep them across restarts on a disposable runner.

Five values are the exception: `BOT_TOKEN`, `TELEGRAM_API`, `TELEGRAM_HASH`, `OWNER_ID` and `DATABASE_URL`. They are validated *before* the database connection is made, so they must come from secrets (or `config.py`). There is no way around that.

**The partition rule.** Settings are stored under an id derived from the bot token: `p_` + the first 24 hex chars of `sha256(salt + <numeric part of the token>)`. Reuse the same bot token and your existing database is picked up exactly as it was. Point the bot at a *different* token and it computes a different partition — it will look like an empty database and start writing fresh documents alongside your old ones. Nothing is deleted, but nothing is read either.

**The trap this used to have, now fixed.** An unset GitHub secret still arrives as an empty string, and the env layer would apply it — blanking the Mongo value. `run-bot.sh` now unsets every known config variable that is empty before starting the bot, and logs which ones it dropped:

```
[harness 09:13:02] cleared empty config env var(s) so MongoDB values survive: USER_SESSION_STRING HELPER_TOKENS
```

If you see a key in that list, it is being read from Mongo instead.

**If you edit the database by hand**, the document is `settings.config` with `_id` equal to the partition id, and the key names must match the bot's exactly. Helper tokens set through `/bs` are stored as `MULTI_TOKEN1`, `MULTI_TOKEN2`, … rather than as one `HELPER_TOKENS` string, and `load_dict` accepts both forms. Set one value at a time with `$set` and leave the rest of the document alone.

**One security note.** Values in Mongo are plaintext. Anyone holding the connection string holds your helper bot tokens and your Telegram session string. On a disposable runner there is nowhere else to put them, but treat the `DATABASE_URL` with the same care as the tokens themselves — and use a dedicated cluster, not one shared with anything else.

---

## 8c. Cookies (this is what makes YouTube work)

YouTube refuses datacenter IPs — *"Sign in to confirm you're not a bot"* — and a GitHub runner is a datacenter IP. The live test suite confirms it. The fix is a cookie file, and you only have to supply it once:

1. In a browser, export cookies for `youtube.com` in Netscape format (any "Get cookies.txt" extension).
2. Send `/us` to the bot → **YT Cookie File** → upload the `cookies.txt`.
3. That is stored in MongoDB and restored to `cookies/<your_id>/cookies.txt` on every boot.

Both the bot's own yt-dlp path and `/webdl` then use it automatically — `/webdl` looks for `WEBDL_COOKIE_FILE`, then `./cookies.txt`, then the newest per-user file. The `/webdl` page shows `cookies: on` in its status pills when one is found.

Without cookies, direct links, torrents and the music providers all still work; only YouTube (and other login-walled sites) will refuse.

---

## 8d. Hosting the downloader UI somewhere else

`webdl.html` in this repo is the same page the bot serves at `/webdl`, and it also works as a standalone site — it is published at `https://<you>.github.io/<repo>/webdl.html`. On first load it asks for the bot's URL and a password, stores both in `localStorage`, and talks to the bot cross-origin from then on.

To make that safe, set `WEBDL_PASS` on the bot (repo variable) and give the page the same password. With a password set, the API also answers with `Access-Control-Allow-Origin: *`; without one, only same-origin requests are allowed. `WEBDL_ORIGINS` lets you narrow it to specific origins instead.

Honestly: for a single user, the redirect at `https://<you>.github.io/<repo>/` is the better route — it lands you on the bot's own `/webdl`, same origin, no configuration. The standalone UI is for when you want a bookmarkable page that survives tunnel changes, or you are pointing one front-end at several bots.

---

## 8e. Running the tests

`.github/workflows/test.yml` runs everything without needing your bot credentials. Dispatch it from the Actions tab whenever you change a plugin.

- **Offline suites** (~1 min): the music, quota, web-downloader and Cloudflare Worker tests. No network.
- **Live probes** (~2 min): Deezer, JioSaavn, Spotify oEmbed, catalogue assembly against a real artist, yt-dlp search, cookie discovery, and an actual file download through the `/webdl` engine.

The live job is the only place these can run — a restricted network can't reach those hosts, which is why it exists. It exits non-zero only if a *required* probe fails; the YouTube download is marked optional because it depends on cookies.

---

## 8f. A permanent URL with GitHub Pages (no Cloudflare account needed)

The tunnel hostname changes every run, which makes bookmarking pointless. A Cloudflare Worker solves that by proxying, but it needs a Cloudflare account. GitHub Pages solves it with a **redirect** instead, using the repo you already have.

**How it works.** Each run writes `tunnel.json` (`{"url": ..., "updated": ...}`) and commits it. The Pages site reads that file and forwards you to the live tunnel. Nothing else to host.

**Turn it on once:**

1. Settings → Pages → Source: *Deploy from a branch* → Branch: `main`, folder `/ (root)` → Save.
2. Wait a minute. Your site is `https://<your-username>.github.io/amaterasu-runner/`.

From then on that URL always works: open it and you're redirected to whichever tunnel the bot is on right now. If the bot is offline it says so, with the age of the last known tunnel, instead of dumping you on a dead page.

`404.html` handles deep links, so `…github.io/amaterasu-runner/webdl` redirects to `<tunnel>/webdl`, and `…/app/files` to `<tunnel>/app/files`. Bookmarks to individual pages keep working across restarts.

**What you give up versus the Worker.** Pages cannot proxy, so the address bar changes to the trycloudflare hostname — it is a redirect, not a reverse proxy. And a static page cannot hold a password gate, so the Worker's `PASS` protection is gone. What still protects you is Amaterasu's own `LOGIN_PASS`: `/app/*` and `/webdl` keep asking for it. Set it if you haven't.

**Turning it off:** set `PAGES_PUBLISH: '0'` in the workflow env and the runs stop committing.

---

## 8g. The hub and its vault

The Pages root is a control panel: it lists every page and opens them on the live tunnel, with passwords beside the ones that need them. The list lives in `vault.json` as AES-GCM ciphertext.

**Make your own vault:**

1. Download `vault-maker.html` and open it in a browser — it runs offline, no network calls.
2. Edit the JSON: one entry per page, `name`, `path`, `desc`, and `pass` if that page needs one.
3. Choose a passphrase of at least twelve characters. This is the only thing protecting the contents.
4. Press **Encrypt**, then **Download vault.json**.
5. Commit it to the repo root, replacing the demo one.

The demo vault shipped in the repo opens with the passphrase `amaterasu-demo-pass` and contains fake passwords — replace it before you put anything real in there.

There is also a CLI, if you prefer: `VAULT_PASSPHRASE=… python3 scripts/make-vault.py payload.json --hint "…" > vault.json`.

**What the page does for safety:** PBKDF2-SHA256 at 310,000 iterations, AES-GCM with a random salt and IV, decrypted content held only in memory, auto-lock after ten idle minutes, lock on demand, five wrong attempts before a one-minute cooldown, `no-referrer`, a restrictive CSP, and a CI check that fails the build if `vault.json` ever contains plaintext.

**What it cannot do:** be a real login. A static page has no server to check credentials against. If someone has the URL they can download the ciphertext and try passphrases offline forever. Long passphrase, and nothing catastrophic inside.

---

## 8h. Building the vault from a repository secret

You can keep both the passphrase and the page list in GitHub Secrets and let CI build the vault, so neither ever exists in the repo or on your laptop:

| Secret | What it is |
|---|---|
| `link_house_pass` | the passphrase — the same string you type into the hub |
| `vault_payload` | the page list as JSON, passwords included |

Optionally set a repository *variable* `VAULT_HINT` for the hint shown on the lock screen.

Then run **Actions → Vault → Run workflow**, or push a change to `vault.payload.json`. The workflow encrypts with `link_house_pass`, commits `vault.json` only if the payload actually changed, and fails if any plaintext ends up in the ciphertext file.

If `vault_payload` is not set, the workflow falls back to a `vault.payload.json` file in the repo — handy for a page list with no passwords in it.

**The limitation, stated plainly.** A static page cannot read a repository secret. GitHub injects secrets into workflow runs and nowhere else; the browser has no access to them. So the hub still asks you to type `link_house_pass` to unlock — that is not an oversight, it is the only way a static site can decrypt anything. What the secret buys you is that the key is never written to disk, never committed, and the payload never leaves GitHub.

If you want to open the panel without typing anything, you need something with a server — the Cloudflare Worker in section 8 is exactly that, and it can hold `link_house_pass` as a Worker secret.

---

## 9. Day-to-day

**The rhythm.** Cron fires every 5 hours. Each run clones Amaterasu fresh, installs, boots, runs for ~4.5 hours, then shuts down cleanly as the next run starts. Expect a gap of a few minutes, and up to 20 minutes extra if GitHub's scheduler is backed up.

**What survives a restart:** everything in Mongo — `/bs` settings, users, quota usage, the library, RSS feeds, thumbnails. **What doesn't:** downloaded files, in-flight tasks (a large torrent will start over).

**Changing settings.** Two ways, and they differ:
- `/bs` in Telegram → stored in Mongo, survives, applies immediately.
- Repo variables/secrets → applied at the next boot, and they *override* Mongo values.

**Reading logs.** Actions → the run → the job. The `amaterasu-log` artifact (3-day retention) carries `log.txt` from the bot itself, which is where real errors land.

**Restarting.** `/restart` in Telegram restarts the bot inside the current run. To get a clean environment, cancel the run in Actions and start a new one.

**Stopping it.** Actions → the workflow → `⋯` → Disable workflow. That kills the cron; a running job finishes or you cancel it.

---

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: niquests.packages` | pip resolved an old niquests. `setup-runner.sh` pins `>=3.21` — check it wasn't edited |
| Bot silent, log says `BOT_TOKEN variable is missing` | the secret isn't set, or you named it differently |
| `CLOUDFLARE_TUNNEL_ENABLED is True but cloudflared is not installed` | the toolchain step failed; `cloudflared --version` in the log should print one |
| FileToLink links 502 after a while | the tunnel hostname rotated; check `/tunnel-status` on the Worker, or use the Worker URL instead of the raw tunnel |
| Mongo connection timeouts | Atlas Network Access isn't open to `0.0.0.0/0`, or the password isn't URL-encoded |
| `/usage` always zero | Mongo not connected, or `DAILY_QUOTA_GB=0` |
| Music commands missing | `/plugins` → Music → Load. If it's not listed, the file wasn't copied — check the setup log |
| `/msdebug` shows Deezer/JioSaavn red | that runner can't reach them; YouTube fallback still works, or try again next run (transient blocks happen) |
| `/webdl` 401 or redirects to login | `LOGIN_PASS` is set and you aren't logged in — open `/login` first |
| Encode fails with `Cannot load libnvidia-encode.so.1` | `FFMPEG_HW_ACCEL` picked NVENC on a GPU-less runner. The workflow sets it to `none`; if you removed that line, put it back |
| Job cancelled at the 5-hour mark | that's the next cron run taking over, by design |
| `Resource not accessible by integration` when pushing | the GitHub App lacks access to that repo — grant it under Settings → Applications |

---

## 11. Honest limits

- **This is against the spirit of GitHub's terms.** Long-lived services on Actions runners get accounts suspended. Yours is a brand-new account, which draws more automated attention than an old one.
- **Disk is the hard ceiling.** ~20–25 GB, wiped every run. Set limits before you need them.
- **No stable IP or inbound port.** Anything that needs either (private trackers with IP allowlists, myJD pairing) will not work.
- **The bot is offline a few minutes every 5 hours.** If that matters, you already need the VPS.
- **Free minutes are only free because the repo is public.** Keep it that way.

---

## 12. Moving to a VPS (when this proves out)

Nothing has to be rebuilt:

```bash
git clone https://github.com/Zan-getsu/Amaterasu && cd Amaterasu
cp config_sample.py config.py       # or keep using .env / env vars
# copy plugins/*.py   -> ./plugins/
# copy web/webdl.py   -> ./web/     and register it (see below)
docker compose up -d --build
```

- The **same Mongo URI** carries your settings, users and quota history across.
- The **same secrets** become `.env` entries or `config.py` values.
- Keep the Worker, or drop it for a named Cloudflare tunnel (`CLOUDFLARE_TUNNEL_TOKEN`) or a plain reverse proxy on your own domain.
- For the web downloader on a VPS, add the two lines `from web.webdl import register` / `register(app)` at the end of `web/wserver.py` — the same patch the setup script applies.

A €5/month 2 vCPU / 4 GB box runs this comfortably; budget 40 GB of disk if you handle big torrents.

---

## 13. Command reference

Core Amaterasu (a selection):

| Command | What |
|---|---|
| `/mirror`, `/m` | download and upload to Drive/rclone |
| `/leech`, `/l` | download and upload to Telegram |
| `/qbmirror`, `/qm` | torrent via qBittorrent |
| `/ytdl`, `/y` | yt-dlp download |
| `/link` | FileToLink — turn a Telegram file into a stream URL |
| `/status`, `/s` | running tasks |
| `/cancel`, `/c` | cancel a task |
| `/bs` | bot settings |
| `/us` | your settings |
| `/plugins` | load/unload plugins |
| `/restart` | restart the bot process |
| `/stats` | bot statistics |

Music plugin:

| Command | What |
|---|---|
| `/ms <link>` | artist / album / playlist / track from Spotify, Apple, Deezer, JioSaavn |
| `/ms <song name>` | search and pick |
| `/ld <song>` | grab a song (lyrics video audio) |
| `/msdebug` | provider health check |

Quota plugin:

| Command | What |
|---|---|
| `/usage` | today's bytes against your cap |
| `/find <text>` | search your download library |
| `/qusers` | owner: everyone's usage today |
| `/quota <id> <gb>` | owner: set a user's cap (0 = unlimited) |
| `/addcap <id> <gb>` | owner: raise/lower a cap by an amount |
| `/botcap <gb>` | owner: global cap, stored in Mongo |
| `/quotareset <id>` | owner: zero today's usage |
| `/dbstats` | owner: collection counts |
| `/dbclean [days]` | owner: purge old library/quota rows, with a confirm button |
