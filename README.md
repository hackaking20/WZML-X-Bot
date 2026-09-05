# WZML-X Stream Bot

Runs WZML-X Telegram bot on GitHub Actions with Cloudflare Worker tunnel.

## Quick Start

1. Upload all files to your GitHub repo
2. Deploy the Cloudflare Worker (see cloudflare-worker/stream-worker.js)
3. Add GitHub Secrets (see below)
4. Trigger the workflow via GitHub Actions

## GitHub Secrets

- BOT_TOKEN — from @BotFather
- TELEGRAM_API — from my.telegram.org
- TELEGRAM_HASH — from my.telegram.org
- OWNER_ID — your Telegram user ID
- DATABASE_URL — MongoDB connection string
- WORKER_URL — https://wzml-stream.xxx.workers.dev
- WORKER_SECRET — secret string matching Worker's env
- NTFY_TOPIC — ntfy.sh topic for notifications (optional, defaults to JAI_HO)

## Bot Settings (via Telegram, NOT secrets)

- USER_SESSION_STRING — set via bot config
- STREAM_PASS — set via /bs command
