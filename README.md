# Webtoon Chapter Tracker

A small agent that watches your favourite Webtoon series through their official RSS feeds and pings you on Telegram when a new episode drops. Runs free on GitHub Actions every hour.

## How it works

1. `series.json` lists the series you follow (name + RSS link).
2. `tracker.py` fetches each feed and compares episode links against `state.json`.
3. New episodes trigger a Telegram message. The first run for a series only records what exists, so you don't get spammed with the back catalogue.
4. The GitHub workflow commits the updated `state.json` so it remembers between runs.

No login, no scraping, no ads touched. Only Python's standard library.

## Setup

### 1. Find a series' RSS link
Open the series page on webtoons.com and click the RSS icon (or add `/rss` before `?title_no=`):

```
https://www.webtoons.com/en/<genre>/<series-name>/list?title_no=1234
https://www.webtoons.com/en/<genre>/<series-name>/rss?title_no=1234
```

Add it to `series.json`:

```json
[
  { "name": "My Series", "rss": "https://www.webtoons.com/en/fantasy/my-series/rss?title_no=1234" }
]
```

### 2. Telegram bot
1. Message **@BotFather**, send `/newbot`, copy the token.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.

### 3. Run locally
```bash
export TELEGRAM_BOT_TOKEN=xxx
export TELEGRAM_CHAT_ID=yyy
python tracker.py            # first run records existing episodes
python tracker.py --dry-run  # prints instead of sending
```

### 4. Run on GitHub Actions
1. Push this folder to a GitHub repo (private is fine).
2. Repo **Settings > Secrets and variables > Actions**: add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. **Actions** tab > "Check Webtoon episodes" > **Run workflow** to test it.

It then runs hourly. Change the `cron` line in `.github/workflows/check.yml` to adjust.

## Limits
- RSS shows publicly released episodes. Fast Pass (paid early access) and your personal Daily Pass timers aren't in the feed, since those are tied to your account.
- GitHub may pause scheduled workflows after 60 days of no repo activity; the state commits usually keep it alive.

## Ideas to extend
- `/add <rss link>` and `/list` commands through your existing Telegram bot
- A short LLM summary of each new episode's description
- Daily digest mode instead of one message per episode
