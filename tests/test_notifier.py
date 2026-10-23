import unittest
from unittest.mock import Mock, call, patch

import requests

import config
from notifier import TelegramNotifier
from signal_formatter import format_signal


class TelegramNotifierTests(unittest.TestCase):
    def setUp(self):
        self.notifier = TelegramNotifier(
            "test-token",
            "-100123",
            "socks5h://user:pass@proxy.example:1080",
        )
        self.signal = {
            "match_id": "3037951",
            "team": "Tatran Presov",
            "anchor": {
                "match_data": {
                    "match_id": "3037951",
                    "league": "Slovakia 2. Liga",
                    "match_time": "40",
                    "home_team": "Tatran Presov",
                    "away_team": "MSK Zilina B",
                    "score": "0-1",
                },
                "market_data": {
                    "over": {"total": "1.5"},
                    "ah": {"handicap": "1.5"},
                },
            },
        }

    def test_format_signal_remains_available_on_notifier(self):
        self.assertEqual(
            self.notifier.format_signal("over", self.signal),
            format_signal("over", self.signal),
        )

    @patch("notifier.requests.post")
    def test_sends_preformatted_message_without_formatting_it_again(self, post_mock):
        post_mock.return_value = Mock(json=Mock(return_value={"ok": True}))

        with patch.object(self.notifier, "format_signal") as format_mock:
            sent = self.notifier.send_signal(
                "over",
                self.signal,
                formatted_message="Prepared prediction",
            )

        self.assertTrue(sent)
        format_mock.assert_not_called()
        self.assertEqual(
            post_mock.call_args.kwargs["data"]["text"],
            "Prepared prediction",
        )

    @patch("notifier.time.sleep")
    @patch("notifier.requests.post")
    def test_retries_twice_then_succeeds_using_socks_proxy(
        self, post_mock, sleep_mock
    ):
        post_mock.side_effect = [
            requests.ConnectionError("offline"),
            requests.Timeout("timed out"),
            Mock(status_code=200, json=Mock(return_value={"ok": True})),
        ]

        sent = self.notifier.send_signal("over", self.signal)

        self.assertTrue(sent)
        self.assertEqual(post_mock.call_count, 3)
        self.assertEqual(
            sleep_mock.call_args_list,
            [call(3), call(3)],
        )
        self.assertEqual(
            post_mock.call_args.kwargs["proxies"],
            {
                "http": "socks5h://user:pass@proxy.example:1080",
                "https": "socks5h://user:pass@proxy.example:1080",
            },
        )
        self.assertEqual(
            post_mock.call_args.kwargs["data"]["parse_mode"], "HTML"
        )
        self.assertEqual(
            post_mock.call_args.kwargs["data"]["text"],
            format_signal("over", self.signal),
        )
        self.assertEqual(
            post_mock.call_args.kwargs["timeout"],
            config.TELEGRAM_REQUEST_TIMEOUT_SECONDS,
        )

    @patch("notifier.time.sleep")
    @patch("notifier.requests.post")
    @patch("notifier.logger")
    def test_logs_error_after_three_failed_attempts(
        self, logger_mock, post_mock, sleep_mock
    ):
        post_mock.side_effect = requests.ConnectionError("network down")

        sent = self.notifier.send_signal("over", self.signal)

        self.assertFalse(sent)
        self.assertEqual(post_mock.call_count, 3)
        self.assertEqual(sleep_mock.call_args_list, [call(3), call(3)])
        logger_mock.error.assert_called_once()

    @patch("notifier.time.sleep")
    @patch("notifier.requests.post")
    def test_retries_when_telegram_returns_api_error(self, post_mock, sleep_mock):
        post_mock.side_effect = [
            Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "ok": False,
                        "description": "chat not found",
                    }
                ),
                raise_for_status=Mock(),
            ),
            Mock(
                status_code=200,
                json=Mock(return_value={"ok": True}),
                raise_for_status=Mock(),
            ),
        ]

        sent = self.notifier.send_signal("over", self.signal)

        self.assertTrue(sent)
        self.assertEqual(post_mock.call_count, 2)
        sleep_mock.assert_called_once_with(3)

    @patch("notifier.load_dotenv")
    @patch.dict(
        "os.environ",
        {
            "BOT_TOKEN": "test-token",
            "CHANNEL_ID": "-100123",
            "TELEGRAM_PROXY_HOST": "proxy.example",
            "TELEGRAM_PROXY_PORT": "1080",
            "TELEGRAM_PROXY_USERNAME": "user name",
            "TELEGRAM_PROXY_PASSWORD": "p@ss",
        },
        clear=True,
    )
    def test_loads_configuration_and_encodes_socks_proxy_auth(
        self, load_dotenv_mock
    ):
        notifier = TelegramNotifier.from_environment()

        load_dotenv_mock.assert_called_once()
        self.assertEqual(notifier.bot_token, "test-token")
        self.assertEqual(notifier.channel_id, "-100123")
        self.assertEqual(
            notifier.proxy_url,
            "socks5h://user%20name:p%40ss@proxy.example:1080",
        )

    def test_rejects_empty_bot_credentials(self):
        for bot_token, channel_id, expected in (
            ("", "-100123", "BOT_TOKEN"),
            ("token", " ", "CHANNEL_ID"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    TelegramNotifier(bot_token, channel_id)

    def test_error_sanitization_without_optional_proxy_is_unchanged(self):
        notifier = TelegramNotifier("token", "channel")

        self.assertEqual(
            notifier._sanitize_error("network unavailable"),
            "network unavailable",
        )

    @patch("notifier.load_dotenv")
    def test_loads_without_proxy_and_accepts_boundary_ports(self, _load_dotenv):
        for port in ("1", "65535"):
            with self.subTest(port=port):
                environment = {
                    "BOT_TOKEN": "test-token",
                    "CHANNEL_ID": "-100123",
                    "TELEGRAM_PROXY_HOST": "proxy.example",
                    "TELEGRAM_PROXY_PORT": port,
                }
                with patch.dict("os.environ", environment, clear=True):
                    notifier = TelegramNotifier.from_environment()
                self.assertEqual(
                    notifier.proxy_url,
                    f"socks5h://proxy.example:{port}",
                )

        with patch.dict(
            "os.environ",
            {"BOT_TOKEN": "test-token", "CHANNEL_ID": "-100123"},
            clear=True,
        ):
            notifier = TelegramNotifier.from_environment()
        self.assertIsNone(notifier.proxy_url)

    @patch("notifier.load_dotenv")
    def test_rejects_incomplete_proxy_settings_and_invalid_ports(
        self, _load_dotenv
    ):
        cases = (
            ({"TELEGRAM_PROXY_HOST": "proxy.example"}, "set together"),
            ({"TELEGRAM_PROXY_PORT": "1080"}, "set together"),
            (
                {"TELEGRAM_PROXY_USERNAME": "user"},
                "must be set together",
            ),
            (
                {"TELEGRAM_PROXY_PASSWORD": "password"},
                "must be set together",
            ),
            (
                {
                    "TELEGRAM_PROXY_HOST": "proxy.example",
                    "TELEGRAM_PROXY_PORT": "nope",
                },
                "must be a number",
            ),
            (
                {
                    "TELEGRAM_PROXY_HOST": "proxy.example",
                    "TELEGRAM_PROXY_PORT": "0",
                },
                "between 1 and 65535",
            ),
            (
                {
                    "TELEGRAM_PROXY_HOST": "proxy.example",
                    "TELEGRAM_PROXY_PORT": "65536",
                },
                "between 1 and 65535",
            ),
        )
        for additions, expected in cases:
            with self.subTest(additions=additions):
                environment = {
                    "BOT_TOKEN": "test-token",
                    "CHANNEL_ID": "-100123",
                    **additions,
                }
                with patch.dict("os.environ", environment, clear=True):
                    with self.assertRaisesRegex(ValueError, expected):
                        TelegramNotifier.from_environment()

    @patch("notifier.time.sleep")
    @patch("notifier.requests.post")
    @patch("notifier.logger")
    def test_rejects_non_object_telegram_response_after_retries(
        self, logger_mock, post_mock, sleep_mock
    ):
        post_mock.return_value = Mock(
            json=Mock(return_value=["invalid"]),
            raise_for_status=Mock(),
        )

        sent = self.notifier.send_signal(
            "over",
            self.signal,
            formatted_message="preformatted",
        )

        self.assertFalse(sent)
        self.assertEqual(post_mock.call_count, config.TELEGRAM_MAX_ATTEMPTS)
        self.assertEqual(
            sleep_mock.call_count,
            config.TELEGRAM_MAX_ATTEMPTS - 1,
        )
        logger_mock.error.assert_called_once()

    @patch("notifier.time.sleep")
    @patch("notifier.requests.post")
    @patch("notifier.logger")
    def test_redacts_bot_and_proxy_secrets_from_final_error(
        self, logger_mock, post_mock, _sleep_mock
    ):
        error = requests.HTTPError(
            f"failed for {self.notifier.bot_token} via {self.notifier.proxy_url}"
        )
        post_mock.side_effect = error

        self.assertFalse(
            self.notifier.send_signal(
                "over",
                self.signal,
                formatted_message="preformatted",
            )
        )

        logged_error = logger_mock.error.call_args.args[-1]
        self.assertNotIn(self.notifier.bot_token, logged_error)
        self.assertNotIn(self.notifier.proxy_url, logged_error)
        self.assertEqual(logged_error.count("[REDACTED]"), 2)


if __name__ == "__main__":
    unittest.main()
