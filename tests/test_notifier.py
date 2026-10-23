import unittest
from unittest.mock import Mock, call, patch

import requests

import config
from notifier import TelegramNotifier


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

    def test_formats_over_signal_using_html_and_anchor_details(self):
        message = self.notifier.format_signal("over", self.signal)

        self.assertEqual(
            message,
            '<b>Slovakia 2. Liga</b>\n'
            '🧊 40’ <a href="https://www.goaloo.com/oddscomp/3037951">'
            "Tatran Presov 0 - 1 MSK Zilina B</a>\n\n"
            "Over 1.5",
        )

    def test_normalizes_asian_over_total(self):
        self.signal["anchor"]["market_data"]["over"]["total"] = "3.0/3.5"

        message = self.notifier.format_signal("over", self.signal)

        self.assertTrue(message.endswith("Over 3.25"))

    def test_formats_ah_signal_with_home_or_away_side(self):
        home_message = self.notifier.format_signal("ah", self.signal)
        self.assertTrue(home_message.endswith("Handicap -1.5 Home"))

        self.signal["team"] = "MSK Zilina B"
        away_message = self.notifier.format_signal("ah", self.signal)
        self.assertTrue(away_message.endswith("Handicap -1.5 Away"))

    def test_formats_positive_asian_handicap_with_a_leading_minus(self):
        self.signal["anchor"]["market_data"]["ah"]["handicap"] = "1.5/2"

        message = self.notifier.format_signal("ah", self.signal)

        self.assertTrue(message.endswith("Handicap -1.75 Home"))

    def test_normalizes_negative_asian_handicap(self):
        self.signal["anchor"]["market_data"]["ah"]["handicap"] = "-1.5/2"

        message = self.notifier.format_signal("ah", self.signal)

        self.assertTrue(message.endswith("Handicap -1.75 Home"))

    def test_preserves_existing_negative_handicap(self):
        self.signal["anchor"]["market_data"]["ah"]["handicap"] = "-1.5"

        message = self.notifier.format_signal("ah", self.signal)

        self.assertTrue(message.endswith("Handicap -1.5 Home"))

    def test_does_not_add_a_minus_to_zero_handicap(self):
        self.signal["anchor"]["market_data"]["ah"]["handicap"] = "0"

        message = self.notifier.format_signal("ah", self.signal)

        self.assertTrue(message.endswith("Handicap 0 Home"))

    def test_escapes_user_supplied_html(self):
        self.signal["anchor"]["match_data"]["league"] = "Liga <A>"
        self.signal["anchor"]["match_data"]["home_team"] = "Team <One>"

        message = self.notifier.format_signal("over", self.signal)

        self.assertIn("<b>Liga &lt;A&gt;</b>", message)
        self.assertIn("Team &lt;One&gt;", message)

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


if __name__ == "__main__":
    unittest.main()
