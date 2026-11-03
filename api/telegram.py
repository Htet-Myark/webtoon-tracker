"""Telegram webhook (Vercel Python function).

Telegram POSTs every message sent to the bot here, so commands are answered
instantly. Episode checking still happens in tracker.py on GitHub Actions.

Env vars (set in Vercel):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_WEBHOOK_SECRET
"""

import json
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

SERIES_FILE = Path(__file__).resolve().parent.parent / "series.json"

HELP = "Commands:\n/list - show the series being tracked"


def load_series():
    with open(SERIES_FILE, encoding="utf-8") as f:
        return json.load(f)


def format_list(series_list):
    lines = [f"📚 Tracking {len(series_list)} series:"]
    for i, s in enumerate(series_list, 1):
        page = s["rss"].replace("/rss?", "/list?")
        lines.append(f"{i}. {s['name']}\n   {page}")
    return "\n".join(lines)


def reply_for(text):
    command = (text or "").strip().split()[:1]
    command = command[0].split("@")[0].lower() if command else ""
    if command in ("/list", "/start"):
        return format_list(load_series())
    if command.startswith("/"):
        return HELP
    return None  # ignore plain chat


def send_message(chat_id, text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as resp:
        resp.read()


class handler(BaseHTTPRequestHandler):
    def _respond(self, status, body=b"ok"):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._respond(200, b"webtoon tracker bot is up")

    def do_POST(self):
        # Only Telegram knows this secret (sent via setWebhook's secret_token).
        expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        if not expected or self.headers.get("X-Telegram-Bot-Api-Secret-Token") != expected:
            return self._respond(401, b"unauthorized")

        length = int(self.headers.get("Content-Length") or 0)
        try:
            update = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._respond(200)  # never make Telegram retry junk

        msg = update.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        # Only answer the owner's chat; strangers who find the bot get nothing.
        if chat_id and chat_id == os.environ.get("TELEGRAM_CHAT_ID"):
            text = reply_for(msg.get("text"))
            if text:
                try:
                    send_message(chat_id, text)
                except Exception as e:
                    print(f"[error] sendMessage: {e}")
        self._respond(200)
