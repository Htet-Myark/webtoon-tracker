"""Webtoon chapter tracker.

Reads each series' official RSS feed, finds episodes it hasn't seen before,
and sends a Telegram message for each one.

Usage:
    python tracker.py              # normal check
    python tracker.py --dry-run    # print instead of sending to Telegram

Env vars (optional; without them it just prints):
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).parent
SERIES_FILE = BASE_DIR / "series.json"
STATE_FILE = BASE_DIR / "state.json"
USER_AGENT = "webtoon-chapter-tracker/1.0 (personal RSS reader)"
MAX_SEEN_PER_SERIES = 200  # keep state.json small


def load_json(path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def fetch_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def parse_episodes(xml_bytes):
    """Return a list of episodes (newest first, as the feed lists them)."""
    root = ET.fromstring(xml_bytes)
    episodes = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or title).strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if guid:
            episodes.append({"id": guid, "title": title, "link": link, "date": pub_date})
    return episodes


def clean_env(name):
    """Read a secret, dropping whitespace and any byte-order mark (U+FEFF).

    A secret saved from Windows PowerShell 5.1 or a "UTF-8 with BOM" file
    starts with an invisible U+FEFF. In the token it crashes the request
    (the URL must be ASCII); in the chat ID Telegram answers "chat not found".
    """
    return (os.environ.get(name) or "").replace("﻿", "").strip()


def send_telegram(text, dry_run=False):
    token = clean_env("TELEGRAM_BOT_TOKEN")
    chat_id = clean_env("TELEGRAM_CHAT_ID")
    if dry_run or not token or not chat_id:
        print("[notify]", text.replace("\n", " | "))
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "false",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        # Telegram explains every rejection ("chat not found", "Unauthorized", ...)
        # in the body. Surface that, never the URL: it contains the token.
        try:
            reason = json.loads(e.read()).get("description", "")
        except Exception:
            reason = ""
        raise RuntimeError(f"Telegram sendMessage failed: HTTP {e.code} {reason}".rstrip()) from None


def check_series(series, state, dry_run=False):
    name = series["name"]
    url = series["rss"]
    try:
        episodes = parse_episodes(fetch_feed(url))
    except Exception as e:
        print(f"[error] {name}: {e}", file=sys.stderr)
        return 0

    seen = state.get(url)
    first_run = seen is None
    seen = set(seen or [])

    new_eps = [ep for ep in episodes if ep["id"] not in seen]

    if first_run:
        # Don't spam the whole back catalogue on the first run.
        print(f"[init] {name}: recorded {len(episodes)} existing episodes")
    else:
        # Feed is newest first; notify oldest first so messages read in order.
        for ep in reversed(new_eps):
            msg = f"📖 New on {name}\n{ep['title']}\n{ep['link']}"
            send_telegram(msg, dry_run=dry_run)
        print(f"[check] {name}: {len(new_eps)} new")

    # Store ids in feed order so trimming keeps the newest ones.
    all_ids = [ep["id"] for ep in episodes] + [i for i in state.get(url, []) if i not in {ep["id"] for ep in episodes}]
    state[url] = all_ids[:MAX_SEEN_PER_SERIES]
    return 0 if first_run else len(new_eps)


def main():
    parser = argparse.ArgumentParser(description="Webtoon new-episode tracker")
    parser.add_argument("--dry-run", action="store_true", help="print instead of sending")
    args = parser.parse_args()

    series_list = load_json(SERIES_FILE, [])
    if not series_list:
        print("series.json is empty. Add some series first.")
        return

    state = load_json(STATE_FILE, {})
    total = 0
    for series in series_list:
        total += check_series(series, state, dry_run=args.dry_run)
    save_json(STATE_FILE, state)
    print(f"Done. {total} new episode(s) across {len(series_list)} series.")


if __name__ == "__main__":
    main()
