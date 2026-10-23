import unittest

from signal_formatter import format_signal


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
            '🧊 40’ <a href="https://www.goaloo.com/oddscomp/3037951">'
            "Tatran Presov 0 - 1 MSK Zilina B</a>\n\n"
            "Тотал больше 1.5",
        )

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


if __name__ == "__main__":
    unittest.main()
