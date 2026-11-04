"""Tests for the episode checker (tracker.py). No network: feeds are fixtures."""

import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tracker  # noqa: E402

FEED_URL = "https://www.webtoons.com/en/drama/example/rss?title_no=1"
SERIES = {"name": "Example", "rss": FEED_URL}


def make_feed(*episodes):
    """Build an RSS document. episodes = (number, title) pairs, newest first."""
    items = "".join(
        f"""
        <item>
          <title><![CDATA[{title}]]></title>
          <link>https://www.webtoons.com/en/drama/example/ep-{n}/viewer?title_no=1&amp;episode_no={n}</link>
          <guid>ep-{n}</guid>
          <pubDate>Mon, 0{n} Nov 2026 12:00:00 GMT</pubDate>
        </item>"""
        for n, title in episodes
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Example</title>{items}</channel></rss>""".encode()


class ParseEpisodesTest(unittest.TestCase):
    def test_parses_items_in_feed_order(self):
        eps = tracker.parse_episodes(make_feed((3, "Ep. 3"), (2, "Ep. 2")))
        self.assertEqual([e["id"] for e in eps], ["ep-3", "ep-2"])
        self.assertEqual(eps[0]["title"], "Ep. 3")
        self.assertIn("episode_no=3", eps[0]["link"])  # &amp; decoded

    def test_falls_back_to_link_when_guid_missing(self):
        xml = b"""<rss><channel><item><title>A</title>
            <link>https://x/ep-1</link></item></channel></rss>"""
        self.assertEqual(tracker.parse_episodes(xml)[0]["id"], "https://x/ep-1")

    def test_skips_empty_items(self):
        xml = b"<rss><channel><item></item></channel></rss>"
        self.assertEqual(tracker.parse_episodes(xml), [])

    def test_bad_xml_raises(self):
        with self.assertRaises(Exception):
            tracker.parse_episodes(b"<html>not a feed")


class CheckSeriesTest(unittest.TestCase):
    def run_check(self, feed_bytes, state):
        sent = []
        with mock.patch.object(tracker, "fetch_feed", return_value=feed_bytes), \
             mock.patch.object(tracker, "send_telegram", side_effect=lambda t, **k: sent.append(t)), \
             mock.patch("builtins.print"):
            new = tracker.check_series(SERIES, state)
        return new, sent

    def test_first_run_records_everything_and_sends_nothing(self):
        state = {}
        new, sent = self.run_check(make_feed((2, "Ep. 2"), (1, "Ep. 1")), state)
        self.assertEqual((new, sent), (0, []))
        self.assertEqual(state[FEED_URL], ["ep-2", "ep-1"])

    def test_no_new_episodes(self):
        state = {FEED_URL: ["ep-2", "ep-1"]}
        new, sent = self.run_check(make_feed((2, "Ep. 2"), (1, "Ep. 1")), state)
        self.assertEqual((new, sent), (0, []))

    def test_new_episodes_are_sent_oldest_first(self):
        state = {FEED_URL: ["ep-1"]}
        feed = make_feed((3, "Ep. 3"), (2, "Ep. 2"), (1, "Ep. 1"))
        new, sent = self.run_check(feed, state)
        self.assertEqual(new, 2)
        self.assertIn("Ep. 2", sent[0])
        self.assertIn("Ep. 3", sent[1])
        self.assertTrue(all("New on Example" in m for m in sent))
        self.assertEqual(state[FEED_URL], ["ep-3", "ep-2", "ep-1"])

    def test_keeps_old_ids_that_dropped_out_of_the_feed(self):
        # Feeds only show the latest ~20; older seen ids must not be forgotten.
        state = {FEED_URL: ["ep-2", "ep-1", "ep-0"]}
        self.run_check(make_feed((2, "Ep. 2")), state)
        self.assertEqual(state[FEED_URL], ["ep-2", "ep-1", "ep-0"])

    def test_state_is_trimmed_to_newest(self):
        old = [f"old-{i}" for i in range(tracker.MAX_SEEN_PER_SERIES)]
        state = {FEED_URL: old}
        self.run_check(make_feed((9, "Ep. 9")), state)
        self.assertEqual(len(state[FEED_URL]), tracker.MAX_SEEN_PER_SERIES)
        self.assertEqual(state[FEED_URL][0], "ep-9")
        self.assertNotIn(old[-1], state[FEED_URL])

    def test_feed_error_is_reported_and_state_untouched(self):
        state = {FEED_URL: ["ep-1"]}
        with mock.patch.object(tracker, "fetch_feed", side_effect=OSError("timeout")), \
             mock.patch("sys.stderr"):
            self.assertEqual(tracker.check_series(SERIES, state), 0)
        self.assertEqual(state, {FEED_URL: ["ep-1"]})


class SendTelegramTest(unittest.TestCase):
    def test_prints_instead_of_sending_without_credentials(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(tracker.urllib.request, "urlopen") as urlopen, \
             mock.patch("builtins.print") as printed:
            tracker.send_telegram("hello")
        urlopen.assert_not_called()
        printed.assert_called_once()

    def test_dry_run_never_sends(self):
        env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}
        with mock.patch.dict("os.environ", env, clear=True), \
             mock.patch.object(tracker.urllib.request, "urlopen") as urlopen, \
             mock.patch("builtins.print"):
            tracker.send_telegram("hello", dry_run=True)
        urlopen.assert_not_called()

    def test_strips_bom_and_whitespace_from_secrets(self):
        env = {"TELEGRAM_BOT_TOKEN": "﻿123:abc\n", "TELEGRAM_CHAT_ID": "﻿ 42 \r\n"}
        with mock.patch.dict("os.environ", env, clear=True), \
             mock.patch.object(tracker.urllib.request, "urlopen") as urlopen:
            tracker.send_telegram("hello")
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.telegram.org/bot123:abc/sendMessage")
        self.assertIn(b"chat_id=42&", req.data)

    def test_telegram_error_reason_is_reported_without_token(self):
        env = {"TELEGRAM_BOT_TOKEN": "123:secret", "TELEGRAM_CHAT_ID": "42"}
        body = io.BytesIO(b'{"ok":false,"error_code":400,"description":"Bad Request: chat not found"}')
        err = tracker.urllib.error.HTTPError("https://api.telegram.org/bot123:secret/sendMessage",
                                             400, "Bad Request", {}, body)
        with mock.patch.dict("os.environ", env, clear=True), \
             mock.patch.object(tracker.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                tracker.send_telegram("hello")
        self.assertIn("chat not found", str(ctx.exception))
        self.assertNotIn("secret", str(ctx.exception))


class SeriesFileTest(unittest.TestCase):
    def test_series_json_is_valid(self):
        series = tracker.load_json(tracker.SERIES_FILE, None)
        self.assertIsInstance(series, list)
        self.assertTrue(series, "series.json is empty")
        for s in series:
            self.assertTrue(s.get("name"), s)
            self.assertRegex(s.get("rss", ""), r"^https://www\.webtoons\.com/.+/rss\?title_no=\d+$")
        rss = [s["rss"] for s in series]
        self.assertEqual(len(rss), len(set(rss)), "duplicate feed in series.json")


if __name__ == "__main__":
    unittest.main()
