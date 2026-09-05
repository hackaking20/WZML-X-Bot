"""
WZML-X Bot Notification Script
Sends shutdown countdown + startup notifications via Telegram and ntfy.sh.

Usage:
  python3 notify.py shutdown <minutes> <bot_token> <owner_id>
  python3 notify.py startup <bot_token> <owner_id> <ntfy_topic> <stream_url>
"""
import sys
import json
import urllib.request

API_BASE = "https://api.telegram.org/bot"


def send_telegram(bot_token, chat_id, text):
    url = f"{API_BASE}{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")


def send_ntfy(topic, title, message):
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode(),
            headers={"Title": title},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"ntfy error: {e}")


def main():
    action = sys.argv[1]

    if action == "shutdown":
        minutes = int(sys.argv[2])
        bot_token = sys.argv[3]
        owner_id = sys.argv[4]
        time_text = f"{minutes // 60} hour(s)" if minutes >= 60 else f"{minutes} minute(s)"
        msg = (
            f"⚠️ *Bot Restart Notice*\n\n"
            f"The bot is shutting down in {time_text}.\n"
            f"It will come back in ~30 minutes.\n"
            f"Stay tuned! 🔄"
        )
        send_telegram(bot_token, owner_id, msg)
        print(f"Shutdown notification sent: {time_text} remaining")

    elif action == "startup":
        bot_token = sys.argv[2]
        owner_id = sys.argv[3]
        ntfy_topic = sys.argv[4]
        stream_url = sys.argv[5]
        msg = (
            f"✅ *Bot has started!*\n\n"
            f"🌐 Stream Gateway: {stream_url}\n"
            f"📊 Health: {stream_url}/health\n\n"
            f"Bot is online and ready to stream."
        )
        send_telegram(bot_token, owner_id, msg)
        send_ntfy(ntfy_topic, "WZML-X Bot is LIVE!", f"Bot online! Stream Gateway: {stream_url}")
        print(f"Startup notification sent to owner + ntfy/{ntfy_topic}")


if __name__ == "__main__":
    main()
