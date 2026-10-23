import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from strategy import (
    _entry_time,
    _find_cumulative_movement,
    _has_excluded_anchor_match_time,
    _is_valid_anchor,
    _market_handicap,
    _market_total,
    _match_score,
    _match_team,
    _normalize_handicap,
    _redcard_count,
    find_ah_signal,
    find_over_signal,
)


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

    def test_ignores_invalid_redcard_values_and_non_dictionary_history_items(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        invalid_redcard = self._entry(
            start + timedelta(minutes=1), "3.75", redcards="unknown"
        )
        anchor = self._entry(start + timedelta(minutes=2), "4")

        signal = find_over_signal(
            "match-1", [current, None, invalid_redcard, anchor]
        )

        self.assertIsNotNone(signal)
        self.assertIs(signal["current"], current)

    def test_redcard_alias_and_non_finite_count_are_handled(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        redcard = self._entry(
            start + timedelta(minutes=1), "3.75"
        )
        redcard["match_data"].pop("redcards")
        redcard["match_data"]["redcard"] = 1
        anchor = self._entry(start + timedelta(minutes=2), "4")

        self.assertIsNone(find_over_signal("match-1", [current, redcard, anchor]))

        redcard["match_data"]["redcard"] = "NaN"
        self.assertIsNotNone(
            find_over_signal("match-1", [current, redcard, anchor])
        )

    def test_rejects_mixed_timezone_and_out_of_order_observations(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "3.5")
        anchor = self._entry(start + timedelta(minutes=1), "4")
        current["observed_at"] = start.isoformat() + "+00:00"
        self.assertIsNone(find_over_signal("match-1", [current, anchor]))

        current = self._entry(start + timedelta(minutes=2), "3.5")
        anchor = self._entry(start + timedelta(minutes=1), "4")
        self.assertIsNone(find_over_signal("match-1", [current, anchor]))


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

    def test_normalizes_shorthand_negative_handicaps(self):
        self.assertEqual(_normalize_handicap("-1.5/2"), Decimal("-1.75"))
        self.assertEqual(_normalize_handicap("0/-0.5"), Decimal("-0.25"))
        self.assertEqual(_normalize_handicap("-1.5/-2"), Decimal("-1.75"))

    def test_shorthand_negative_handicap_movement_triggers_signal(self):
        start = datetime(2026, 10, 22, 12, 0)
        history = [
            self._entry(start, "-1.5"),
            self._entry(start + timedelta(minutes=1), "-1.5/2"),
            self._entry(start + timedelta(minutes=2), "-2"),
        ]

        signal = find_ah_signal("match-1", history)

        self.assertIs(signal["current"], history[0])
        self.assertIs(signal["anchor"], history[-1])
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

    def test_returns_none_when_anchor_has_no_matching_team(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "1")
        middle = self._entry(start + timedelta(seconds=30), "1.25")
        anchor = self._entry(
            start + timedelta(minutes=1),
            "1.5",
            home_team=" ",
        )

        self.assertIsNone(
            find_ah_signal("match-1", [current, middle, anchor])
        )

    def test_redcard_alias_rejects_anchor_and_invalid_latest_anchor_is_skipped(self):
        start = datetime(2026, 10, 22, 12, 0)
        current = self._entry(start, "-1")
        middle = self._entry(start + timedelta(seconds=30), "-1.25")
        anchor = self._entry(start + timedelta(minutes=1), "-1.5")
        redcard = self._entry(start + timedelta(minutes=2), "-1.75")
        redcard["match_data"].pop("redcards")
        redcard["match_data"]["redcard"] = "1"
        self.assertIsNone(
            find_ah_signal("match-1", [current, middle, anchor, redcard])
        )

        redcard["match_data"]["redcard"] = "not-a-count"
        redcard["market_data"]["ah"]["handicap"] = "Closed"
        signal = find_ah_signal(
            "match-1", [current, middle, anchor, redcard]
        )
        self.assertIsNotNone(signal)
        self.assertIs(signal["anchor"], anchor)

    def test_empty_history_has_no_signal(self):
        self.assertIsNone(find_ah_signal("match-1", []))


class StrategyInputValidationTests(unittest.TestCase):
    def test_malformed_timestamps_and_market_records_are_rejected(self):
        self.assertIsNone(_entry_time({"observed_at": None}))
        self.assertIsNone(_entry_time({"observed_at": 123}))
        self.assertIsNone(_entry_time({"observed_at": "not-a-time"}))
        self.assertIsNone(_market_total({"market_data": []}))
        self.assertIsNone(
            _market_total({"market_data": {"over": []}})
        )
        self.assertIsNone(_market_handicap({"market_data": []}))
        self.assertIsNone(
            _market_handicap({"market_data": {"ah": []}})
        )

    def test_malformed_match_fields_do_not_create_scores_or_redcards(self):
        self.assertEqual(_match_score({"match_data": []}), "")
        self.assertEqual(
            _match_score({"match_data": {"score": 1}}),
            "",
        )
        self.assertFalse(_has_excluded_anchor_match_time({}))
        self.assertFalse(
            _has_excluded_anchor_match_time(
                {"match_data": {"match_time": 45}}
            )
        )
        self.assertIsNone(_redcard_count({"match_data": []}))
        self.assertIsNone(_redcard_count({"match_data": {}}))
        self.assertIsNone(
            _redcard_count(
                {"match_data": {"redcards": "not-a-count"}}
            )
        )
        self.assertIsNone(
            _redcard_count(
                {"match_data": {"redcards": "Infinity"}}
            )
        )
        self.assertEqual(
            _redcard_count({"match_data": {"redcard": "2"}}),
            Decimal("2"),
        )

    def test_anchor_validation_skips_non_dictionary_history_entries(self):
        anchor_time = datetime(2026, 10, 22, 12, 0)
        anchor = {"match_data": {"match_time": "45"}}

        self.assertTrue(
            _is_valid_anchor(
                [None, "invalid", {"match_data": {}}],
                anchor,
                anchor_time,
            )
        )

    def test_cumulative_search_stops_at_matching_score_with_invalid_time(self):
        history = [
            {
                "observed_at": "invalid",
                "match_data": {"score": "0-0"},
                "market_data": {},
            },
            {
                "observed_at": "2026-10-22 12:01:00",
                "match_data": {"score": "0-0"},
                "market_data": {},
            },
        ]

        result = _find_cumulative_movement(
            history,
            anchor_index=1,
            anchor_value=Decimal("4"),
            anchor_time=datetime(2026, 10, 22, 12, 1),
            anchor_score="0-0",
            value_for_entry=lambda _entry: Decimal("4"),
            movement_for_step=lambda older, newer, _anchor: newer - older,
        )

        self.assertIsNone(result)

    def test_malformed_team_data_returns_empty_team_name(self):
        self.assertEqual(_match_team({"match_data": []}, "home_team"), "")
        self.assertEqual(
            _match_team(
                {"match_data": {"home_team": 1}},
                "home_team",
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
