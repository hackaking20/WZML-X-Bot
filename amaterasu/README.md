# Amaterasu on GitHub Actions

Runs [Amaterasu](https://github.com/Zan-getsu/Amaterasu) — the most complete of the WZML-X forks — on a disposable GitHub Actions runner, with a Cloudflare quick tunnel for the web UI and FileToLink, the same shape as `hackaking20/WZML-X-Bot` but carrying Amaterasu instead of WZML-X.

This is a test bench. It exists so you can try the bot for a week without renting a VPS. It is not a production deployment, and the section at the bottom explains why.

**New here? Read [SETUP.md](SETUP.md)** — the full walkthrough from accounts to first download, including what to check after each step.

---

## What you get

- The bot running ~4.8 hours out of every 5, restarted automatically by cron, with a supervisor loop inside each run so crashes and its own daily 06:00 restart are absorbed.
- The full Amaterasu feature set that does not need extra services: aria2c + qBittorrent torrents, direct links, TeraBox, Mega, yt-dlp (with Deno, so YouTube actually works), Google Drive / rclone uploads, Telegram leech, FileToLink streaming, encode profiles, the web UI.
- MongoDB-backed persistence, so your `/bs` settings, users, RSS feeds and thumbnails survive between runs even though the runner does not.
- A Cloudflare Worker that gives you one stable URL pointing at whichever tunnel the current run happens to be using.

Deliberately switched off by default: JDownloader (Java + a large download every boot) and SABnzbd/Usenet (apt package that is fiddly on a runner). Both are one-line flips if you want them.

---

## Before you start

You need:

1. **A public GitHub repo.** This matters more than it looks. Free Actions minutes are unlimited for public repos and 2,000/month for private ones. A run every 5 hours is roughly 43,000 minutes a month, so on a private repo you would exhaust the quota in under two days. Keep the harness repo public.
2. **A bot token** from [@BotFather](https://t.me/BotFather).
3. **`api_id` and `api_hash`** from [my.telegram.org](https://my.telegram.org) → API development tools.
4. **A MongoDB URI.** Atlas M0 (free) is fine. When you create the cluster, allow `0.0.0.0/0` in Network Access — runner IPs change on every job, so an IP allowlist will lock you out.
5. **Your Telegram numeric user ID** (from [@userinfobot](https://t.me/userinfobot)).
6. Optional: a **user session string**, needed for leeching files over 2 GB and for the user-account stream fallback. Generate it with the bot's own `/session` flow once it is up, or with a session generator.
7. Optional: a **Cloudflare account** for the Worker. Free tier is plenty.

---

## Setup

**1. Create the repo and push these files.**

```bash
git init amaterasu-runner && cd amaterasu-runner
# copy .github/, scripts/, cloudflare-worker/, README.md here
git add -A && git commit -m "Amaterasu on Actions"
git branch -M main
git remote add origin https://github.com/<you>/amaterasu-runner.git
git push -u origin main
```

**2. Add the secrets.** Repo → Settings → Secrets and variables → Actions → New repository secret.

| Secret | Required | What it is |
|---|---|---|
| `BOT_TOKEN` | yes | BotFather token |
| `TELEGRAM_API` | yes | `api_id` |
| `TELEGRAM_HASH` | yes | `api_hash` |
| `OWNER_ID` | yes | your numeric Telegram ID |
| `DATABASE_URL` | yes | MongoDB URI |
| `USER_SESSION_STRING` | recommended | unlocks >2 GB leech and user-session streaming |
| `WEB_ACCESS_PASSWORD` | recommended | password for the web UI / FileToLink |
| `HELPER_TOKENS` | optional | comma-separated extra bot tokens for parallel uploads |
| `LOG_CHAT_ID` | optional | channel ID for logs |
| `WORKER_URL` | optional | `https://<name>.<subdomain>.workers.dev` |
| `WORKER_SECRET` | optional | random string, must match the Worker's `TUNNEL_SECRET` |
| `NTFY_TOPIC` | optional | ntfy.sh topic for start/stop/tunnel pings |

Optional **variables** (Settings → Variables) if you want to track a fork or branch: `AMATERASU_REPO`, `AMATERASU_REF`. They default to `Zan-getsu/Amaterasu` and `main`.

**3. Run it.** Actions → *Amaterasu (ephemeral runner)* → Run workflow. Leave `minutes` at 290 for the first run. The first run takes ~6 minutes before the bot is online, most of it apt and pip.

**4. Find your URL.** Watch the run log for:

```
[harness 09:12:44] tunnel URL is https://something-random.trycloudflare.com
```

That URL is live for the length of the run. If you set up the Worker, use the Worker URL instead — it follows the tunnel automatically and never changes.

**5. Say hello.** Send `/start` to your bot. Then `/status` to confirm the engines came up, and `/bs` to look at settings.

---

## The Cloudflare Worker (stable URL)

Skip this on day one if you like; the tunnel URL in the log is enough to poke at the web UI.

1. Cloudflare dashboard → Workers & Pages → Create → Worker. Paste `cloudflare-worker/worker.js`, deploy.
2. Create a KV namespace, then bind it to the Worker as `TUNNEL_KV`.
3. Add secret `TUNNEL_SECRET` (any long random string) and, if you want a login gate, variable `PASS`.
4. Copy the Worker URL and secret into the GitHub secrets `WORKER_URL` and `WORKER_SECRET`.

Every boot, `run-bot.sh` notices the new tunnel hostname and POSTs it to `/update-tunnel`. Visit `/tunnel-status` any time to see which tunnel is registered and whether it answers.

The password gate is worth using. Amaterasu's web UI includes session and token generators — leaving that on a public URL with no password is asking for trouble.

---

## Keeping config in MongoDB

Anything except `BOT_TOKEN`, `TELEGRAM_API`, `TELEGRAM_HASH`, `OWNER_ID` and `DATABASE_URL` can live in the database instead of in GitHub secrets — that is where `/bs` writes, and it is the only thing that survives a runner being wiped. Env vars are applied *after* Mongo, so they win when present; `run-bot.sh` now unsets empty ones so an unset secret can't blank a stored value. Settings are partitioned by a hash of the bot token's numeric id, so reuse the same bot token if you want an existing database picked up. See [SETUP.md](SETUP.md#8b-where-config-actually-lives-and-what-you-can-keep-in-mongo).

---

## The hub on GitHub Pages

`https://<you>.github.io/<repo>/` is a control panel, not a redirect. It lists every page the bot serves — downloader, file selector, encode profiles, merge planner, session generator, Google token, qBittorrent — and opens each one on whichever tunnel is live right now, with the passwords shown beside the pages that need them.

That only works because the page list is **AES-GCM encrypted** in `vault.json`. The repo holds ciphertext; the plaintext never touches it. Open `vault-maker.html` locally, paste your page list and passwords, pick a passphrase, and commit the `vault.json` it produces. The hub unlocks with that passphrase, keeps the decrypted data in memory only, never writes it to storage, and locks itself after ten minutes idle.

The passphrase and the page list can both live in GitHub Secrets instead: set `link_house_pass` and `vault_payload`, then run the **Vault** workflow and CI builds `vault.json` for you. Note that a static page can never *read* a secret — you still type the passphrase to unlock, because the browser has to derive the key somehow. The secret keeps the key out of the repo and off your disk; it does not remove the typing.

**What this is and is not.** GitHub Pages is static, so there is no server-side authorisation to be had — no login wall, no session, no access control. The encryption is real: without the passphrase the file is noise. But the passphrase is the entire lock, and anyone holding the page can attack it offline at their leisure. Use a long one, and treat the vault as a convenience for links rather than a place for anything whose loss would be catastrophic.

`404.html` still forwards deep links, so `…/<repo>/webdl` lands on the live bot.

---

## A permanent URL

The hub at `https://<you>.github.io/<repo>/` opens whichever tunnel the bot is on right now. Each run commits `tunnel.json`, and the Pages site reads it from the API so the redirect is never stale-cached. Deep links work too (`…/webdl` → `<tunnel>/webdl`).

It is a redirect, not a proxy — the address bar changes to the trycloudflare hostname, and a static page can't hold a password gate. Amaterasu's own `LOGIN_PASS` still protects the admin pages. Enable it under Settings → Pages → deploy from `main` / root. See [SETUP.md](SETUP.md#8e-a-permanent-url-with-github-pages-no-cloudflare-account-needed).

---

## What actually works, and what does not

Be clear-eyed about the platform before you spend an evening debugging it.

**Works well.** Torrents and direct links, uploads to Drive and rclone, Telegram leech, yt-dlp, FileToLink streaming, the web UI, all settings persisted in Mongo. A 4-core runner with 16 GB RAM is genuinely decent hardware for this.

**Rough edges.**

- **Downloads die with the runner.** Every 5 hours the disk is wiped. Amaterasu's incomplete-task notifier can resume some tasks from Mongo, but anything mid-transfer starts over. Do not start a 40 GB torrent at the end of a run.
- **Disk is the real limit.** Roughly 20-25 GB free after the toolchain installs. Set your download size limits accordingly (`DIRECT_LIMIT`, `TORRENT_LIMIT`, `LEECH_SPLIT_SIZE`) rather than finding out the hard way.
- **The bot disappears for a few minutes every 5 hours**, and GitHub's scheduler can be 5-20 minutes late under load. The gap is usually short but it is not zero.
- **No inbound ports.** Everything public goes through the tunnel, so the URL rotates unless you use the Worker. Rclone serve, qBittorrent's web UI and similar are only reachable through the tunnel paths.
- **Telegram flood limits are shared.** If you have another bot on the same token or session, both get hit.

**Does not work.** Nothing that needs a stable IP or a persistent port — JDownloader's myJD pairing, MyAnonaMouse-style IP-whitelisted trackers, or anything expecting to be reachable at a fixed address. And anything that assumes state on disk: the runner has none.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'niquests.packages'`** — pip resolved an old niquests. The setup script pins `niquests>=3.21` for exactly this; if you edited it out, put it back.

**`CLOUDFLARE_TUNNEL_ENABLED is True but cloudflared is not installed`** — the tool step was skipped or failed. `cloudflared --version` in the log should print a version.

**Bot online but FileToLink links 502** — the tunnel hostname changed and whatever you copied is stale. Check `/tunnel-status` on the Worker.

**Mongo connection timeouts** — Atlas Network Access is not open to `0.0.0.0/0`, or the password has URL-unsafe characters that need percent-encoding.

**Bot goes silent around 06:00 IST** — that is Amaterasu's built-in daily maintenance restart, not a crash. The supervisor brings it back within ~20 seconds.

**Job cancelled at the 5-hour mark** — the next cron run kills the current one by design (`cancel-in-progress`). If you want longer uninterrupted runs, raise `minutes` to 330 and move the cron to `0 */6 * * *`.

---

## Music plugin (`/ms`, `/ld`, `/msdebug`)

Ported from the WZFIX music stack inside `vot1122/Kaggle-auto` (`r3_music.py` + `r4_music_cmds.py`), rewritten as a self-contained plugin that needs no hooks in the bot core. `scripts/setup-runner.sh` copies everything in `plugins/` into the bot and patches a two-line autoload into `bot/__main__.py`, so the commands come back on every 5-hourly restart instead of needing a manual `/plugins` tap.

| Command | What it does |
|---|---|
| `/ms <link>` | Reads the catalogue behind a Spotify / Apple Music / Deezer / JioSaavn link — artist, album, playlist or single track — then offers to download all of it |
| `/ms <song name>` | Searches Deezer and JioSaavn, shows the top matches as buttons |
| `/ld <song name>` | Searches for the song, shows six results, downloads the one you pick as tagged mp3 |
| `/msdebug` | Probes every provider and reports which ones answer from *your* runner |

Catalogue discovery and audio are separate on purpose: Spotify, Apple and Deezer return metadata only, never a full-length file. So the plugin reads the track list from whichever provider the link points at, then fetches each track's audio from YouTube with yt-dlp — the same approach WZFIX uses, and the reason an artist link works for any artist rather than only ones in one catalogue.

Optional config, all via env or `config.py`:

| Key | Default | Meaning |
|---|---|---|
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | — | Without these, Spotify links still resolve but the catalogue comes from Deezer/JioSaavn by artist name. Album and playlist links need them to be read in full |
| `MUSIC_MAX_TRACKS` | 25 | Tracks per catalogue request, clamped to 200 |
| `MUSIC_QUALITY` | 320 | mp3 bitrate |
| `MUSIC_DIR` | `music_downloads` | Where files land before upload |

First thing to run after boot is `/msdebug`. It tells you in one message whether Deezer, JioSaavn, the Spotify token, oEmbed and yt-dlp all reach the internet from that runner — which is the only failure mode that matters here and the one I could not test from my sandbox (its egress proxy blocks Deezer and JioSaavn).

`scripts/test-music-plugin.py` runs the offline suite: provider response parsing, catalogue assembly and de-duplication, the Spotify-without-credentials fallback, URL routing, card rendering and zipping. 35 checks, no network needed.

---

## Quota plugin (`/usage`, `/quota`, `/quotareset`, `/find`)

Ported from the WZFIX `r1_core` module. That bot ran on a Kaggle notebook with ~20 GB of disk, so one user filling the box took the bot down for everyone — the same failure mode a GitHub runner has, only faster.

The quota is enforced *before* a task starts and recorded when the download lands. It hooks in by wrapping three existing methods at plugin load and unwrapping them on unload, so no source file is patched:

| Method | Why |
|---|---|
| `Mirror.new_event`, `YtDlp.new_event` | refuse the task when today's allowance is gone |
| `TaskListener.on_download_complete` | record the bytes that actually arrived |
| `TaskListener.on_upload_complete` | add the finished file to the library for `/find` |

Every hook is wrapped in `try/except`: a Mongo outage or a changed upstream signature must never stop a download from working.

| Key | Default | Meaning |
|---|---|---|
| `DAILY_QUOTA_GB` | 15 | Per-user daily allowance. `0` disables enforcement entirely |
| `QUOTA_ENFORCE` | true | Check the quota at all |
| `QUOTA_TZ_OFFSET` | 5.5 | Hours offset for "today" (IST) |
| `LIBRARY_MAX` | 20000 | Entries kept for `/find`, oldest pruned |

Owner tooling, ported from the same WZFIX admin module:

| Command | What |
|---|---|
| `/usage` | today's bytes against your cap |
| `/find <text>` | search your download library |
| `/qusers` | everyone's usage today, busiest first |
| `/quota <id> <gb>` | set a user's cap (0 = unlimited) |
| `/addcap <id> <gb>` | raise or lower a cap by an amount |
| `/botcap <gb>` | global cap, stored in Mongo so it survives restarts |
| `/quotareset <id>` | zero today's usage |
| `/dbstats` | collection counts in the bot's database |
| `/dbclean [days]` | purge library and quota rows older than N days, behind a confirm button |

`/dbclean` only ever touches the two collections this plugin owns, never drops a collection, and never deletes the settings document. Everything except `/usage` and `/find` is owner/sudo only.

## Web downloader (`/webdl`)

Ported from the R17 `webdl` module in Kaggle-auto: paste a link on a web page, the bot fetches it server-side, and the file downloads straight to your browser — no Telegram round trip.

It differs from the original in three ways. It registers itself on Amaterasu's own FastAPI app instead of being patched into a second server; it reuses the bot's login cookie (`amaterasu_session`), so one password covers the whole web UI; and every URL is checked against an SSRF filter — private ranges, loopback, link-local and `metadata.google.internal` are refused — before yt-dlp ever sees it.

The web server runs in its own gunicorn process, so a plugin cannot add these routes. `setup-runner.sh` copies `web/*.py` into the bot and appends a registration block to `web/wserver.py` (only for modules that actually expose `register(app)`).

| Key | Default | Meaning |
|---|---|---|
| `WEBDL_CONC` | 2 | Concurrent fetches |
| `WEBDL_TTL` | 6 | Hours before a finished file is deleted |
| `WEBDL_MAX_GB` | 8 | Disk budget for the download directory |
| `WEBDL_DIR` | `webdl_downloads` | Where files land |
| `WEBDL_COOKIE_FILE` | auto | Override the cookie file yt-dlp uses |

**What the page does.** Paste a link and it probes it first — thumbnail, title, uploader, duration and the available resolutions — then downloads the quality you pick, with a live progress bar, speed and ETA, a cancel button, and a "Recent" list of your last ten downloads. Audio mode extracts a 320k mp3 with tags. There is a settings panel for the server URL and password, so the same page also works when hosted somewhere else.

**Two more knobs**, both for using the UI away from the bot:

| Key | Default | Meaning |
|---|---|---|
| `WEBDL_PASS` | unset | When set, the API needs the password in the `X-Webdl-Pass` header (or a `pass` query param). Wrong attempts are throttled: five, then a minute's block |
| `WEBDL_ORIGINS` | `*` if a password is set, else same-origin | Comma-separated CORS allow-list for a front-end hosted elsewhere |

**Cookies.** `/webdl` reuses the bot's own cookie files, in the same order the bot does: `WEBDL_COOKIE_FILE`, then `./cookies.txt`, then the freshest per-user file under `cookies/<uid>/cookies.txt` (which is what Mongo restores on boot after you upload one through `/us` → *YT Cookie File*). The page shows a `cookies: on/none` badge, so a failure is never a mystery.

This is not a nicety. YouTube answers datacenter IPs with *"Sign in to confirm you're not a bot"*, and a GitHub runner is a datacenter IP — the live test proves it. With a cookie file present the same download works. Upload cookies once via `/us` and `/webdl` picks them up on every run.

---

## What was tested before shipping

So you know what you are trusting:

- **The Python stack.** `scripts/setup-runner.sh` was run end to end against a fresh clone of `Zan-getsu/Amaterasu@main` (commit `40fc2ce`): clone, venv, `pip install -r requirements.txt`, the niquests pin, then a smoke test that imports the whole bot package and asserts WZGram 3.1.5. It passes. The apt and cloudflared/Deno steps need root, so those were not exercised here — they are the same packages the upstream Dockerfile installs.
- **The supervisor.** `scripts/run-bot.sh` was run with a 2-minute budget and no bot token. It started the bot, caught the fast failure, retried, and exited on budget with the right log lines.
- **The Worker.** `cloudflare-worker/test-worker.mjs` covers registration auth, URL validation, KV writes, proxy path/query preservation, upstream status passthrough, the password gate (wrong password, forged cookie, valid cookie) and the no-tunnel 503. 14/14 pass. Run it yourself: `cd cloudflare-worker && cp worker.js worker.mjs && node test-worker.mjs`.
- **The music plugin.** `scripts/test-music-plugin.py` — 35 checks: provider response parsing, catalogue assembly and de-duplication, the Spotify-without-credentials fallback, URL routing, card rendering, zipping.
- **The quota plugin.** `scripts/test-quota.py` — 41 checks against an in-memory Mongo stand-in: day rollover, per-user overrides, the refusal gate, byte recording, library search, and that every patched method is restored on unload.
- **The web downloader.** `scripts/test-webdl.py` — 27 checks through a real FastAPI TestClient: SSRF rejections, the job lifecycle, file delivery, cancellation, the concurrency cap, the login gate and TTL cleanup. Also confirmed the five `/webdl` routes appear on the bot's actual app after the setup patch.

Not tested: a real Telegram login, a real torrent, a real tunnel, because all three need your credentials. That is what your first run is for.

---

## Two honest warnings

**This will get your account noticed eventually.** Running long-lived services on Actions runners is not what the platform is for, and GitHub does suspend accounts for it. hackaking's repo and this one are the same bet. If you want a bot that stays up, the VPS is not optional — this is a rehearsal.

**Treat the token like root.** Amaterasu exposes `/shell` and `/eval` to the owner. Anyone who gets your bot token gets a shell on a machine holding your MongoDB URI, your Google credentials and your session string. Use a throwaway bot, a dedicated Mongo cluster, and never reuse a token from anything else.

---

## Moving to a real VPS when this proves out

The point of the experiment is that the migration is small. What carries over:

- Your Mongo database — same `DATABASE_URL`, same settings, same users. Nothing to redo.
- Your secrets — the same values go into `.env` or `config.py` on the server.
- The Worker — keep it, or drop it for a named Cloudflare tunnel or a plain reverse proxy on your own domain.

What changes:

```bash
git clone https://github.com/Zan-getsu/Amaterasu
cd Amaterasu
cp config_sample.py config.py   # or use .env, both are read
docker compose up -d --build
```

Set `CLOUDFLARE_TUNNEL_ENABLED=False` and either put the container behind Caddy/nginx on port 8080, or use a named tunnel with `CLOUDFLARE_TUNNEL_TOKEN`. A €5/month VPS with 2 vCPU and 4 GB RAM runs this comfortably; budget 40 GB of disk if you will handle large torrents.

If the bot behaved well on Actions, it will behave better on a VPS — same code, same database, one fewer moving part.
