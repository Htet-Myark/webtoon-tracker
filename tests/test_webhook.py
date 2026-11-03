"""Tests for the Telegram webhook (api/telegram.py).

The handler is served on a real local HTTP server, so auth and routing are
tested the way Telegram actually calls it. Outgoing sendMessage calls are mocked.
"""

import importlib.util
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("webhook", ROOT / "api" / "telegram.py")
webhook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(webhook)

SECRET = "test-secret"
OWNER = "6020634121"
ENV = {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": OWNER, "TELEGRAM_WEBHOOK_SECRET": SECRET}


class ReplyForTest(unittest.TestCase):
    def test_list_and_start_return_the_series_list(self):
        for cmd in ("/list", "/start", "/LIST", "  /list  extra words"):
            with self.subTest(cmd=cmd):
                self.assertTrue(webhook.reply_for(cmd).startswith("📚 Tracking"))

    def test_command_addressed_to_bot_username(self):
        self.assertTrue(webhook.reply_for("/list@Webtoon_tracker_bot").startswith("📚"))

    def test_unknown_command_gets_help(self):
        self.assertEqual(webhook.reply_for("/nope"), webhook.HELP)

    def test_plain_text_is_ignored(self):
        for text in ("hi", "", None):
            with self.subTest(text=text):
                self.assertIsNone(webhook.reply_for(text))

    def test_list_links_to_series_pages_not_feeds(self):
        out = webhook.format_list([{"name": "X", "rss": "https://www.webtoons.com/en/a/x/rss?title_no=5"}])
        self.assertIn("1. X", out)
        self.assertIn("/list?title_no=5", out)
        self.assertNotIn("/rss?", out)


class WebhookServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), webhook.handler)
        webhook.handler.log_message = lambda *a, **k: None  # keep test output clean
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/api/telegram"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        patcher = mock.patch.dict("os.environ", ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        send = mock.patch.object(webhook, "send_message")
        self.send = send.start()
        self.addCleanup(send.stop)

    def post(self, update, secret=SECRET, raw=None):
        req = urllib.request.Request(self.url, data=raw or json.dumps(update).encode(), method="POST")
        if secret is not None:
            req.add_header("X-Telegram-Bot-Api-Secret-Token", secret)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code

    @staticmethod
    def message(text, chat_id=OWNER):
        return {"update_id": 1, "message": {"chat": {"id": int(chat_id)}, "text": text}}

    def test_health_check(self):
        with urllib.request.urlopen(self.url) as resp:
            self.assertEqual(resp.status, 200)

    def test_owner_list_command_is_answered(self):
        self.assertEqual(self.post(self.message("/list")), 200)
        self.send.assert_called_once()
        chat_id, text = self.send.call_args.args
        self.assertEqual(chat_id, OWNER)
        self.assertTrue(text.startswith("📚 Tracking"))

    def test_missing_secret_is_rejected(self):
        self.assertEqual(self.post(self.message("/list"), secret=None), 401)
        self.send.assert_not_called()

    def test_wrong_secret_is_rejected(self):
        self.assertEqual(self.post(self.message("/list"), secret="guess"), 401)
        self.send.assert_not_called()

    def test_rejects_everything_when_secret_not_configured(self):
        with mock.patch.dict("os.environ", {"TELEGRAM_WEBHOOK_SECRET": ""}):
            self.assertEqual(self.post(self.message("/list"), secret=""), 401)
        self.send.assert_not_called()

    def test_strangers_are_ignored(self):
        self.assertEqual(self.post(self.message("/list", chat_id="999")), 200)
        self.send.assert_not_called()

    def test_plain_chat_gets_no_reply(self):
        self.assertEqual(self.post(self.message("hello")), 200)
        self.send.assert_not_called()

    def test_non_message_updates_are_acknowledged(self):
        self.assertEqual(self.post({"update_id": 2, "edited_message": {}}), 200)
        self.send.assert_not_called()

    def test_malformed_body_does_not_crash(self):
        # 200 so Telegram doesn't keep retrying a broken update.
        self.assertEqual(self.post(None, raw=b"{not json"), 200)
        self.send.assert_not_called()

    def test_telegram_send_failure_still_returns_200(self):
        self.send.side_effect = OSError("telegram down")
        with mock.patch("builtins.print"):
            self.assertEqual(self.post(self.message("/list")), 200)


if __name__ == "__main__":
    unittest.main()
