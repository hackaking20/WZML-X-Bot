#!/usr/bin/env python3
"""Broadcast a message to all bot users via Telegram API.

Usage: python3 broadcast.py "Your message here"
Reads BOT_TOKEN, DATABASE_URL, OWNER_ID from environment.
Queries MongoDB for all PM users + registered users, then sends
the message to each via the Telegram Bot API.
"""
import sys
import os
import time
from hashlib import sha256

import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
OWNER_ID = os.environ.get("OWNER_ID", "0")
MESSAGE = sys.argv[1] if len(sys.argv) > 1 else "Bot is live!"

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set")
    sys.exit(1)

bot_id = BOT_TOKEN.split(":")[0]
salt = b"wzmlx_v3_db_partition_salt"
partition = f"p_{sha256(salt + bot_id.encode()).hexdigest()[:24]}"

uids = []

if DATABASE_URL:
    try:
        from pymongo import MongoClient

        client = MongoClient(DATABASE_URL, serverSelectionTimeoutMS=10000)
        db = client.wzmlx

        # PM users (users who have started the bot)
        pm_col = db[f"pm_users.{partition}"]
        for doc in pm_col.find({}):
            if doc.get("_id"):
                uids.append(int(doc["_id"]))

        # Registered users (users with stored settings)
        try:
            reg_col = db[f"users.{partition}"]
            for doc in reg_col.find({}):
                if doc.get("_id") and int(doc["_id"]) not in uids:
                    uids.append(int(doc["_id"]))
        except Exception:
            pass

        client.close()
        print(f"Found {len(uids)} users in MongoDB (partition: {partition})")
    except Exception as e:
        print(f"MongoDB error: {e}")

# Always include the owner
try:
    oid = int(OWNER_ID)
    if oid and oid not in uids:
        uids.insert(0, oid)
except (ValueError, TypeError):
    pass

if not uids:
    print("No users found at all. Skipping broadcast.")
    sys.exit(0)

print(f"Broadcasting to {len(uids)} users...")
api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
success, failed = 0, 0

for uid in uids:
    try:
        resp = requests.post(
            api_url,
            json={
                "chat_id": uid,
                "text": MESSAGE,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            success += 1
        else:
            failed += 1
            if failed <= 3:
                print(f"  Failed for {uid}: {resp.status_code} - {resp.text[:100]}")
        time.sleep(0.05)
    except Exception as e:
        failed += 1
        if failed <= 3:
            print(f"  Error for {uid}: {e}")

print(f"Broadcast done: {success} ok, {failed} failed")
