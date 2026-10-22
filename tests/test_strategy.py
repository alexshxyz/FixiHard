import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from strategy import find_ah_signal, find_over_signal


class OverStrategyTests(unittest.TestCase):
    def _entry(
        self,
        observed_at,
        total,
        score="1-0",
        redcards=0,
        odds=None,
        handicap="0",
        ah_odds=None,
        home_team="Home",
        away_team="Away",
        match_time="45",
    ):
        over = {
            "odd": "1.9",
            "under_odd": "1.9",
            "total": total,
        }
        if odds:
            over.update(odds)
        return {
            "observed_at": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
            "match_data": {
                "score": score,
                "redcards": redcards,
                "home_team": home_team,
                "away_team": away_team,
                "match_time": match_time,
            },
            "market_data": {
                "over": over,
                "ah": {
                    "home_odd": "1.9",
                    "away_odd": "1.9",
                    "handicap": handicap,
                    **(ah_odds or {}),
                },
            },
        }

    def test_finds_cumulative_increase_within_inclusive_five_minutes(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        middle = self._entry(start + timedelta(minutes=2), "3.75")
        anchor = self._entry(start + timedelta(minutes=5), "4")

        signal = find_over_signal("match-1", [current, middle, anchor])

        self.assertEqual(signal["match_id"], "match-1")
        self.assertIs(signal["current"], current)
        self.assertIs(signal["anchor"], anchor)

    def test_normalizes_fractional_totals_before_comparing(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3/3.5")
        middle = self._entry(start + timedelta(seconds=30), "3.25/3.75")
        anchor = self._entry(start + timedelta(minutes=1), "3.5/4")

        self.assertIsNotNone(
            find_over_signal("match-1", [current, middle, anchor])
        )

    def test_finds_cumulative_total_movement_with_repeated_values(self):
        start = datetime(2026, 10, 22, 12, 0)
        history = [
            self._entry(start, "3.5"),
            self._entry(start + timedelta(minutes=1), "3.75"),
            self._entry(start + timedelta(minutes=2), "3.75"),
            self._entry(start + timedelta(minutes=3), "4"),
        ]

        signal = find_over_signal("match-1", history)

        self.assertIs(signal["current"], history[0])
        self.assertIs(signal["anchor"], history[-1])

    def test_rejects_single_step_total_jump_at_threshold(self):
        start = datetime(2026, 10, 22, 12, 0)
        history = [
            self._entry(start, "3.5"),
            self._entry(start + timedelta(minutes=1), "4"),
        ]

        self.assertIsNone(find_over_signal("match-1", history))

    def test_rejects_total_movement_with_a_reversal(self):
        start = datetime(2026, 10, 22, 12, 0)
        history = [
            self._entry(start, "3.5"),
            self._entry(start + timedelta(minutes=1), "3.75"),
            self._entry(start + timedelta(minutes=2), "3.5"),
            self._entry(start + timedelta(minutes=3), "4"),
        ]

        self.assertIsNone(find_over_signal("match-1", history))

    def test_rejects_anchor_when_match_time_contains_excluded_value(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        for match_time in ("90", "90+5", "Penalty", "FT", "ET", "penalty"):
            with self.subTest(match_time=match_time):
                anchor = self._entry(
                    start + timedelta(minutes=1),
                    "4",
                    match_time=match_time,
                )
                self.assertIsNone(
                    find_over_signal("match-1", [current, anchor])
                )

    def test_redcard_inside_inclusive_twenty_minute_window_rejects_anchor(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        anchor = self._entry(
            start + timedelta(minutes=20), "4", redcards=1
        )

        self.assertIsNone(find_over_signal("match-1", [current, anchor]))

    def test_redcard_older_than_twenty_minutes_does_not_reject_anchor(self):
        start = datetime(2026, 10, 22, 12, 0)
        redcard = self._entry(start, "3.5", redcards=1)
        current = self._entry(start + timedelta(minutes=17), "3.5")
        middle = self._entry(start + timedelta(minutes=19), "3.75")
        anchor = self._entry(start + timedelta(minutes=21), "4")

        self.assertIsNotNone(
            find_over_signal("match-1", [redcard, current, middle, anchor])
        )

    def test_changed_score_stops_search(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        score_change = self._entry(
            start + timedelta(minutes=1), "3.5", score="2-0"
        )
        anchor = self._entry(start + timedelta(minutes=2), "4")

        self.assertIsNone(
            find_over_signal("match-1", [current, score_change, anchor])
        )

    def test_closed_current_market_is_skipped(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        middle = self._entry(start + timedelta(minutes=1), "3.75")
        closed = self._entry(
            start + timedelta(minutes=2),
            "3.875",
            odds={"odd": "Closed"},
        )
        anchor = self._entry(start + timedelta(minutes=3), "4")

        signal = find_over_signal(
            "match-1", [current, middle, closed, anchor]
        )

        self.assertIsNotNone(signal)
        self.assertIs(signal["current"], current)

    def test_closed_latest_market_is_not_used_as_anchor(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        middle = self._entry(start + timedelta(minutes=1), "3.75")
        anchor = self._entry(start + timedelta(minutes=2), "4")
        closed = self._entry(
            start + timedelta(minutes=3),
            "4.5",
            odds={"under_odd": "Closed"},
        )

        signal = find_over_signal("match-1", [current, middle, anchor, closed])

        self.assertIsNotNone(signal)
        self.assertIs(signal["anchor"], anchor)

    def test_matching_total_more_than_five_minutes_ago_rejects_anchor(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        anchor = self._entry(start + timedelta(minutes=6), "4")

        self.assertIsNone(find_over_signal("match-1", [current, anchor]))

    def test_strategy_thresholds_can_be_changed_in_config(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        middle = self._entry(start + timedelta(minutes=2), "3.625")
        anchor = self._entry(start + timedelta(minutes=4), "3.75")

        with (
            patch("config.TOTAL_INCREASE", "0.25"),
            patch("config.MAX_OBSERVATION_INTERVAL_MINUTES", 4),
        ):
            signal = find_over_signal("match-1", [current, middle, anchor])

        self.assertIsNotNone(signal)

    def test_malformed_total_and_time_are_skipped_without_raising(self):
        start = datetime(2026, 10, 22, 12, 0)
        malformed_total = self._entry(start, "not-a-total")
        malformed_time = self._entry(start + timedelta(minutes=1), "4")
        malformed_time["observed_at"] = "invalid-time"

        self.assertIsNone(
            find_over_signal("match-1", [malformed_total, malformed_time])
        )


class AHStrategyTests(unittest.TestCase):
    def _entry(
        self,
        observed_at,
        handicap,
        score="1-0",
        redcards=0,
        home_team="Home",
        away_team="Away",
        odds=None,
        match_time="45",
    ):
        return {
            "observed_at": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
            "match_data": {
                "score": score,
                "redcards": redcards,
                "home_team": home_team,
                "away_team": away_team,
                "match_time": match_time,
            },
            "market_data": {
                "ah": {
                    "home_odd": "1.9",
                    "away_odd": "1.9",
                    "handicap": handicap,
                    **(odds or {}),
                }
            },
        }

    def test_finds_cumulative_handicap_change_for_negative_anchor(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        middle = self._entry(start + timedelta(minutes=2), "-1.25")
        anchor = self._entry(start + timedelta(minutes=5), "-1.5")

        signal = find_ah_signal("match-1", [current, middle, anchor])

        self.assertIs(signal["current"], current)
        self.assertIs(signal["anchor"], anchor)
        self.assertEqual(signal["team"], "Away")

    def test_selects_home_team_for_positive_anchor(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "1")
        middle = self._entry(start + timedelta(seconds=30), "1.25")
        anchor = self._entry(start + timedelta(minutes=1), "1.5")

        signal = find_ah_signal("match-1", [current, middle, anchor])

        self.assertEqual(signal["team"], "Home")

    def test_finds_cumulative_handicap_movement_away_from_zero_for_both_signs(self):
        start = datetime(2026, 10, 22, 12, 0)
        negative_history = [
            self._entry(start, "-1"),
            self._entry(start + timedelta(minutes=1), "-1.25"),
            self._entry(start + timedelta(minutes=2), "-1.25"),
            self._entry(start + timedelta(minutes=3), "-1.5"),
        ]
        positive_history = [
            self._entry(start, "1"),
            self._entry(start + timedelta(minutes=1), "1.25"),
            self._entry(start + timedelta(minutes=2), "1.25"),
            self._entry(start + timedelta(minutes=3), "1.5"),
        ]

        negative_signal = find_ah_signal("match-1", negative_history)
        positive_signal = find_ah_signal("match-1", positive_history)

        self.assertIs(negative_signal["current"], negative_history[0])
        self.assertIs(negative_signal["anchor"], negative_history[-1])
        self.assertIs(positive_signal["current"], positive_history[0])
        self.assertIs(positive_signal["anchor"], positive_history[-1])

    def test_rejects_single_step_handicap_jump_at_threshold(self):
        start = datetime(2026, 10, 22, 12, 0)
        history = [
            self._entry(start, "-1"),
            self._entry(start + timedelta(minutes=1), "-1.5"),
        ]

        self.assertIsNone(find_ah_signal("match-1", history))

    def test_rejects_handicap_movement_toward_zero(self):
        start = datetime(2026, 10, 22, 12, 0)
        cases = (("1.5", "1"), ("-1.5", "-1"))
        for current_handicap, anchor_handicap in cases:
            with self.subTest(anchor_handicap=anchor_handicap):
                current = self._entry(start, current_handicap)
                anchor = self._entry(
                    start + timedelta(minutes=1), anchor_handicap
                )

                self.assertIsNone(
                    find_ah_signal("match-1", [current, anchor])
                )

    def test_normalizes_signed_quarter_handicaps(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1/-1.5")
        middle = self._entry(start + timedelta(seconds=30), "-1.25/-1.5")
        anchor = self._entry(start + timedelta(minutes=1), "-1.5/-2")

        signal = find_ah_signal("match-1", [current, middle, anchor])

        self.assertIsNotNone(signal)
        self.assertEqual(signal["team"], "Away")

    def test_rejects_anchor_when_match_time_contains_excluded_value(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        for match_time in ("90", "90+5", "Penalty", "FT", "ET", "penalty"):
            with self.subTest(match_time=match_time):
                anchor = self._entry(
                    start + timedelta(minutes=1),
                    "-1.5",
                    match_time=match_time,
                )
                self.assertIsNone(
                    find_ah_signal("match-1", [current, anchor])
                )

    def test_rejects_raw_and_normalized_anchor_handicaps_around_zero(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        for handicap in (
            "-0.25",
            "0",
            "0.25",
            "-0.5/0",
            "0/0",
            "0/0.5",
        ):
            with self.subTest(handicap=handicap):
                anchor = self._entry(
                    start + timedelta(minutes=1), handicap
                )
                self.assertIsNone(
                    find_ah_signal("match-1", [current, anchor])
                )

    def test_rejects_normalized_quarter_anchor_without_falling_back(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        previous_anchor = self._entry(start + timedelta(minutes=1), "-1.5")
        excluded_anchor = self._entry(
            start + timedelta(minutes=2), "0/0.5"
        )

        self.assertIsNone(
            find_ah_signal(
                "match-1", [current, previous_anchor, excluded_anchor]
            )
        )

    def test_handicap_movement_toward_zero_is_rejected_for_both_signs(self):
        start = datetime(2026, 10, 22, 12, 0)
        cases = (("1.5", "1"), ("-1.5", "-1"))
        for current_handicap, anchor_handicap in cases:
            with self.subTest(anchor_handicap=anchor_handicap):
                current = self._entry(start, current_handicap)
                anchor = self._entry(
                    start + timedelta(minutes=1), anchor_handicap
                )
                self.assertIsNone(
                    find_ah_signal("match-1", [current, anchor])
                )

    def test_redcard_inside_window_rejects_ah_anchor(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        anchor = self._entry(
            start + timedelta(minutes=1), "-1.5", redcards=1
        )

        self.assertIsNone(find_ah_signal("match-1", [current, anchor]))

    def test_score_change_stops_ah_search(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        changed_score = self._entry(
            start + timedelta(minutes=1), "-1", score="2-0"
        )
        anchor = self._entry(start + timedelta(minutes=2), "-1.5")

        self.assertIsNone(
            find_ah_signal("match-1", [current, changed_score, anchor])
        )

    def test_closed_ah_current_record_is_skipped(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        middle = self._entry(start + timedelta(minutes=1), "-1.25")
        closed = self._entry(
            start + timedelta(minutes=2),
            "-1.375",
            odds={"home_odd": "Closed"},
        )
        anchor = self._entry(start + timedelta(minutes=3), "-1.5")

        signal = find_ah_signal(
            "match-1", [current, middle, closed, anchor]
        )

        self.assertIs(signal["current"], current)

    def test_closed_latest_ah_record_is_not_anchor(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        middle = self._entry(start + timedelta(minutes=1), "-1.25")
        anchor = self._entry(start + timedelta(minutes=2), "-1.5")
        closed = self._entry(
            start + timedelta(minutes=3),
            "-2",
            odds={"handicap": "Closed"},
        )

        signal = find_ah_signal(
            "match-1", [current, middle, anchor, closed]
        )

        self.assertIs(signal["anchor"], anchor)

    def test_matching_handicap_older_than_time_limit_rejects_anchor(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        anchor = self._entry(start + timedelta(minutes=6), "-1.5")

        self.assertIsNone(find_ah_signal("match-1", [current, anchor]))

    def test_malformed_handicap_and_time_are_skipped(self):
        start = datetime(2026, 10, 22, 12, 0)
        malformed_handicap = self._entry(start, "invalid")
        malformed_time = self._entry(start + timedelta(minutes=1), "-1.5")
        malformed_time["observed_at"] = "invalid"

        self.assertIsNone(
            find_ah_signal("match-1", [malformed_handicap, malformed_time])
        )


if __name__ == "__main__":
    unittest.main()
