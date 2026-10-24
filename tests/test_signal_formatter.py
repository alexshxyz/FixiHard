import unittest
from unittest.mock import patch

from signal_formatter import format_signal, format_signal_details


class SignalFormatterTests(unittest.TestCase):
    def setUp(self):
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
        message = format_signal("over", self.signal)

        self.assertEqual(
            message,
            '<b>Slovakia 2. Liga</b>\n'
            '⚡ 40’ <a href="https://www.goaloo.com/oddscomp/3037951">'
            "Tatran Presov 0 - 1 MSK Zilina B</a>\n\n"
            "Тотал больше 1.5",
        )

    def test_formats_with_latest_match_time_when_provided(self):
        message, _ = format_signal_details(
            "over",
            self.signal,
            latest_match_time="45",
        )

        self.assertIn("⚡ 45’", message)
        self.assertNotIn("⚡ 40’", message)

    def test_rounds_quarter_over_total_up(self):
        for total, expected in (("3.25", "3.5"), ("3.75", "4")):
            with self.subTest(total=total):
                self.signal["anchor"]["market_data"]["over"]["total"] = total

                message = format_signal("over", self.signal)

                self.assertTrue(message.endswith(f"Тотал больше {expected}"))

    def test_normalizes_asian_over_total_before_rounding(self):
        self.signal["anchor"]["market_data"]["over"]["total"] = "3.0/3.5"

        message = format_signal("over", self.signal)

        self.assertTrue(message.endswith("Тотал больше 3.5"))

    def test_formats_ah_signal_with_home_or_away_side(self):
        self.signal["anchor"]["match_data"]["score"] = "0-0"
        home_message = format_signal("ah", self.signal)
        self.assertTrue(home_message.endswith("Фора 1 -1.5"))

        self.signal["team"] = "MSK Zilina B"
        away_message = format_signal("ah", self.signal)
        self.assertTrue(away_message.endswith("Фора 2 -1.5"))

    def test_rounds_quarter_handicap_away_from_zero(self):
        self.signal["anchor"]["match_data"]["score"] = "0-0"
        self.signal["anchor"]["market_data"]["ah"]["handicap"] = "1.5/2"

        message = format_signal("ah", self.signal)

        self.assertTrue(message.endswith("Фора 1 -2"))

    def test_rounds_negative_quarter_handicap_away_from_zero(self):
        self.signal["anchor"]["match_data"]["score"] = "0-0"
        self.signal["anchor"]["market_data"]["ah"]["handicap"] = "-1.5/2"

        message = format_signal("ah", self.signal)

        self.assertTrue(message.endswith("Фора 1 -2"))

    def test_preserves_existing_negative_handicap(self):
        self.signal["anchor"]["match_data"]["score"] = "0-0"
        self.signal["anchor"]["market_data"]["ah"]["handicap"] = "-1.5"

        message = format_signal("ah", self.signal)

        self.assertTrue(message.endswith("Фора 1 -1.5"))

    def test_does_not_add_a_minus_to_zero_handicap(self):
        self.signal["anchor"]["match_data"]["score"] = "0-0"
        self.signal["anchor"]["market_data"]["ah"]["handicap"] = "0"

        message = format_signal("ah", self.signal)

        self.assertTrue(message.endswith("Фора 1 0"))

    def test_recalculates_handicap_from_score_into_russian_outcomes(self):
        cases = (
            ("Tatran Presov", "1.5", "0-1", "Победа 1"),
            ("MSK Zilina B", "-1.5", "1-0", "Победа 2"),
            ("Tatran Presov", "0.5", "0-1", "1X"),
            ("MSK Zilina B", "-0.5", "1-0", "X2"),
        )
        for team, handicap, score, expected in cases:
            with self.subTest(team=team, handicap=handicap, score=score):
                self.signal["team"] = team
                self.signal["anchor"]["market_data"]["ah"]["handicap"] = handicap
                self.signal["anchor"]["match_data"]["score"] = score

                message = format_signal("ah", self.signal)

                self.assertTrue(message.endswith(expected))

    def test_uses_unadjusted_handicap_when_score_is_unavailable(self):
        self.signal["anchor"]["match_data"]["score"] = "Unknown"
        self.signal["anchor"]["market_data"]["ah"]["handicap"] = "1.25"

        message = format_signal("ah", self.signal)

        self.assertTrue(message.endswith("Фора 1 -1.25"))

    def test_escapes_user_supplied_html(self):
        self.signal["anchor"]["match_data"]["league"] = "Liga <A>"
        self.signal["anchor"]["match_data"]["home_team"] = "Team <One>"

        message = format_signal("over", self.signal)

        self.assertIn("<b>Liga &lt;A&gt;</b>", message)
        self.assertIn("Team &lt;One&gt;", message)

    def test_rejects_unsupported_strategy(self):
        with self.assertRaisesRegex(ValueError, "Unsupported signal strategy"):
            format_signal("unknown", self.signal)

    def test_preserves_unparseable_total_and_logs_warning(self):
        self.signal["anchor"]["market_data"]["over"]["total"] = "unknown"

        with patch("signal_formatter.logger") as logger_mock:
            message, prediction = format_signal_details("over", self.signal)

        self.assertTrue(message.endswith("Тотал больше unknown"))
        self.assertEqual(prediction, "Тотал больше unknown")
        logger_mock.warning.assert_called_once()

    def test_preserves_unparseable_and_non_finite_handicaps(self):
        for handicap in ("unknown", "Infinity"):
            with self.subTest(handicap=handicap):
                self.signal["anchor"]["market_data"]["ah"]["handicap"] = (
                    handicap
                )
                with patch("signal_formatter.logger") as logger_mock:
                    message = format_signal("ah", self.signal)

                self.assertTrue(message.endswith(f"Фора 1 {handicap}"))
                logger_mock.warning.assert_called_once()

    def test_rejects_missing_anchor_details_and_market_values(self):
        for signal, strategy, expected in (
            ({}, "over", "anchor record"),
            ({"anchor": {"match_data": []}}, "over", "match or market"),
            (
                {
                    "anchor": {
                        "match_data": self.signal["anchor"]["match_data"],
                        "market_data": {},
                    }
                },
                "over",
                "missing total",
            ),
            (
                {
                    "anchor": {
                        "match_data": self.signal["anchor"]["match_data"],
                        "market_data": {},
                    },
                    "team": "Tatran Presov",
                },
                "ah",
                "missing handicap",
            ),
        ):
            with self.subTest(strategy=strategy, expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    format_signal(strategy, signal)

    def test_rejects_empty_required_match_details(self):
        self.signal["anchor"]["match_data"]["league"] = ""

        with self.assertRaisesRegex(ValueError, "required match details"):
            format_signal("over", self.signal)

    def test_rejects_handicap_for_a_team_not_in_the_match(self):
        self.signal["team"] = "Unknown team"

        with self.assertRaisesRegex(ValueError, "does not match"):
            format_signal("ah", self.signal)

    def test_encodes_match_id_in_url_and_accepts_colon_score(self):
        self.signal["match_id"] = "match/one"
        self.signal["anchor"]["match_data"]["match_id"] = "match/one"
        self.signal["anchor"]["match_data"]["score"] = " 1 : 0 "

        message = format_signal("over", self.signal)

        self.assertIn("/oddscomp/match%2Fone", message)
        self.assertIn("1 : 0", message)


if __name__ == "__main__":
    unittest.main()
