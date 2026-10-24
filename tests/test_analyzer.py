import unittest
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock, call, patch

from analyzer import MatchAnalyzer, load_state_from_json
from models import Match


class MatchAnalyzerTests(unittest.TestCase):
    def test_signal_uses_latest_observed_match_time(self):
        with TemporaryDirectory() as temp_dir:
            analyzer = MatchAnalyzer(
                history_path=Path(temp_dir) / "matches_history.json",
                database_path=Path(temp_dir) / "matches.sqlite3",
            )
            analyzer.initialize(
                [
                    Match(
                        match_id="match-1",
                        league="Test League",
                        home_team="Home",
                        away_team="Away",
                        match_time="23",
                        score="1-0",
                        total="3.5",
                    )
                ]
            )
            signal = {
                "match_id": "match-1",
                "anchor": {
                    "match_data": {
                        "match_id": "match-1",
                        "league": "Test League",
                        "home_team": "Home",
                        "away_team": "Away",
                        "match_time": "12",
                        "score": "1-0",
                    },
                    "market_data": {"over": {"total": "3.5"}},
                },
            }

            message = analyzer._save_signal("over", signal)

            self.assertIsNotNone(message)
            self.assertIn("⚡ 23’", message)
            self.assertNotIn("⚡ 12’", message)

    def test_saves_signal_before_sending_telegram_notification(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            database_path = Path(temp_dir) / "matches.sqlite3"
            notifier = Mock()
            analyzer = MatchAnalyzer(
                history_path=history_path,
                database_path=database_path,
                notifier=notifier,
            )
            start = datetime(2026, 10, 22, 12, 0)

            def assert_signal_saved_before_notification(*_args, **_kwargs):
                with closing(sqlite3.connect(database_path)) as connection:
                    row = connection.execute(
                        "SELECT match_id, strategy FROM signals"
                    ).fetchone()
                self.assertEqual(row, ("match-1", "over"))

            notifier.send_signal.side_effect = (
                assert_signal_saved_before_notification
            )
            match_data = {
                "match_id": "match-1",
                "league": "Test League",
                "home_team": "Home",
                "away_team": "Away",
                "match_time": "40",
                "score": "1-0",
            }

            with (
                patch("analyzer.datetime") as datetime_mock,
                patch("analyzer.logger"),
            ):
                datetime_mock.now.side_effect = [
                    start,
                    start.replace(second=10),
                    start.replace(second=20),
                ]
                analyzer.initialize(
                    [
                        Match(
                            **match_data,
                            total="1",
                        )
                    ]
                )
                analyzer.record_updates(
                    [
                        Match(
                            **match_data,
                            total="1.25",
                        )
                    ]
                )
                analyzer.record_updates(
                    [
                        Match(
                            **match_data,
                            total="1.5",
                        )
                    ]
                )

            notifier.send_signal.assert_called_once()
            self.assertEqual(
                notifier.send_signal.call_args.args[0],
                "over",
            )

    def test_score_change_closes_markets_in_copy_for_one_minute(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            copy_path = Path(temp_dir) / "matches_history_copy.json"
            analyzer = MatchAnalyzer(
                history_path=history_path,
                history_copy_path=copy_path,
            )
            start = datetime(2026, 10, 22, 12, 0)

            with (
                patch("analyzer.datetime") as datetime_mock,
                patch("analyzer.logger") as logger_mock,
            ):
                datetime_mock.now.side_effect = [
                    start,
                    start.replace(second=10),
                    start.replace(second=40),
                    start.replace(minute=1, second=10),
                ]
                analyzer.initialize(
                    [
                        Match(
                            match_id="match-1",
                            score="1-0",
                            total="3.5",
                            over_odd="1.9",
                            under_odd="1.9",
                            ah_handicap="-1",
                            ah_home_odd="1.9",
                            ah_away_odd="1.9",
                        )
                    ]
                )
                analyzer.record_updates(
                    [
                        Match(
                            match_id="match-1",
                            score="2-0",
                            total="3.5",
                            over_odd="1.9",
                            under_odd="1.9",
                            ah_handicap="-1",
                            ah_home_odd="1.9",
                            ah_away_odd="1.9",
                        )
                    ]
                )
                analyzer.record_updates(
                    [
                        Match(
                            match_id="match-1",
                            score="2-0",
                            total="4",
                            over_odd="1.8",
                            under_odd="2",
                            ah_handicap="-1.5",
                            ah_home_odd="1.9",
                            ah_away_odd="1.9",
                        )
                    ]
                )
                analyzer.record_updates(
                    [
                        Match(
                            match_id="match-1",
                            score="2-0",
                            total="4.5",
                            over_odd="1.8",
                            under_odd="2",
                            ah_handicap="-1.5",
                            ah_home_odd="1.9",
                            ah_away_odd="1.9",
                        )
                    ]
                )

            original = json.loads(history_path.read_text(encoding="utf-8"))
            copied = json.loads(copy_path.read_text(encoding="utf-8"))
            original_history = original["matches"][0]["history"]
            copy_history = copied["matches"][0]["history"]

            self.assertEqual(
                original_history[1]["market_data"]["over"]["total"], "3.5"
            )
            for entry in copy_history[1:3]:
                self.assertEqual(
                    entry["market_data"]["over"],
                    {"odd": "-", "under_odd": "-", "total": "Closed"},
                )
                self.assertEqual(
                    entry["market_data"]["ah"],
                    {
                        "home_odd": "-",
                        "away_odd": "-",
                        "handicap": "Closed",
                    },
                )
            self.assertEqual(
                copy_history[3]["market_data"]["over"]["total"], "4.5"
            )
            self.assertEqual(
                copy_history[3]["market_data"]["ah"]["handicap"], "-1.5"
            )
            logger_mock.info.assert_not_called()

    def test_signal_database_has_text_columns_and_expected_fields(self):
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "matches.sqlite3"
            analyzer = MatchAnalyzer(database_path=database_path)
            signal = {
                "match_id": "match-1",
                "team": "Home",
                "anchor": {
                    "match_data": {
                        "match_id": "match-1",
                        "league": "Test League",
                        "home_team": "Home",
                        "away_team": "Away",
                        "match_time": "40",
                        "score": "0-0",
                    },
                    "market_data": {
                        "over": {"total": "3.25"},
                        "ah": {"handicap": "0.5"},
                    },
                },
            }

            analyzer._save_signal("over", signal)

            with closing(sqlite3.connect(database_path)) as connection:
                columns = connection.execute(
                    "PRAGMA table_info(signals)"
                ).fetchall()
                row = connection.execute(
                    "SELECT * FROM signals"
                ).fetchone()

            self.assertEqual(
                [column[1] for column in columns],
                [
                    "date",
                    "league",
                    "home_team",
                    "away_team",
                    "prediction",
                    "final_score",
                    "result",
                    "match_id",
                    "strategy",
                    "source",
                ],
            )
            self.assertTrue(all(column[2] == "TEXT" for column in columns))
            self.assertEqual(row[0], datetime.now().date().isoformat())
            self.assertEqual(row[1:5], (
                "Test League",
                "Home",
                "Away",
                "Тотал больше 3.5",
            ))
            self.assertEqual(row[5:], (
                "",
                "",
                "match-1",
                "over",
                "Bet365",
            ))

    def test_legacy_json_signals_are_not_migrated(self):
        with TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "matches.json"
            database_path = Path(temp_dir) / "matches.sqlite3"
            legacy_path.write_text(
                '{"over": ["match-1 2 -> 3"], "ah": []}',
                encoding="utf-8",
            )

            analyzer = MatchAnalyzer(database_path=database_path)

            self.assertFalse(analyzer._has_signal("over", "match-1"))
            self.assertTrue(legacy_path.exists())

    def test_new_history_entries_use_sortable_datetime_format(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            database_path = Path(temp_dir) / "matches.sqlite3"
            analyzer = MatchAnalyzer(history_path, database_path)
            now = datetime(2026, 10, 21, 20, 30, 9)

            with patch("analyzer.datetime") as datetime_mock:
                datetime_mock.now.return_value = now
                analyzer.initialize([Match(match_id="match-1")])

            self.assertEqual(
                analyzer.histories["match-1"][0]["observed_at"],
                "2026-10-21 20:30:09",
            )

    def test_debug_mode_off_keeps_histories_in_memory_without_writing_files(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            copy_path = Path(temp_dir) / "matches_history_copy.json"
            database_path = Path(temp_dir) / "matches.sqlite3"
            analyzer = MatchAnalyzer(
                history_path=history_path,
                history_copy_path=copy_path,
                database_path=database_path,
            )
            match = Match(match_id="match-1", score="1-0", total="3.5")
            updated_match = Match(
                match_id="match-1",
                score="1-0",
                total="4",
                over_odd="1.8",
                under_odd="2",
            )

            with (
                patch("analyzer.config.DEBUG_MODE", 0),
                patch.object(analyzer, "_analyze_match") as analyze_match,
            ):
                analyzer.initialize([match])
                analyzer.record_updates([updated_match])

                self.assertEqual(len(analyzer.histories["match-1"]), 2)
                self.assertEqual(len(analyzer.copy_histories["match-1"]), 2)
                analyze_match.assert_has_calls(
                    [call("match-1"), call("match-1")]
                )
                self.assertFalse(history_path.exists())
                self.assertFalse(copy_path.exists())

                analyzer.remove_matches(["match-1"])

                self.assertNotIn("match-1", analyzer.histories)
                self.assertNotIn("match-1", analyzer.copy_histories)
                self.assertFalse(history_path.exists())
                self.assertFalse(copy_path.exists())

    def test_over_signal_is_persisted_and_not_repeated_after_restart(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            database_path = Path(temp_dir) / "matches.sqlite3"
            analyzer = MatchAnalyzer(history_path, database_path)
            start = datetime(2026, 10, 22, 12, 0)
            match_details = {
                "league": "Test League",
                "home_team": "Home",
                "away_team": "Away",
                "match_time": "40",
                "score": "1-0",
            }

            with (
                patch("analyzer.datetime") as datetime_mock,
                patch("analyzer.logger") as logger_mock,
            ):
                datetime_mock.now.side_effect = [
                    start,
                    start.replace(minute=1),
                    start.replace(minute=2),
                ]
                analyzer.initialize(
                    [
                        Match(
                            match_id="match-1",
                            total="3.5",
                            **match_details,
                        )
                    ]
                )
                analyzer.record_updates(
                    [
                        Match(
                            match_id="match-1",
                            total="3.75",
                            **match_details,
                        )
                    ]
                )
                analyzer.record_updates(
                    [
                        Match(
                            match_id="match-1",
                            total="4",
                            **match_details,
                        )
                    ]
                )

            logger_mock.info.assert_called_once()
            with closing(sqlite3.connect(database_path)) as connection:
                saved = connection.execute(
                    "SELECT match_id, strategy FROM signals"
                ).fetchall()
            self.assertEqual(saved, [("match-1", "over")])
            self.assertEqual(
                logger_mock.info.call_args.args,
                ("match-1 3.5 -> 4",),
            )

            restarted = MatchAnalyzer(history_path, database_path)
            with (
                patch("analyzer.datetime") as datetime_mock,
                patch("analyzer.logger") as logger_mock,
            ):
                datetime_mock.now.side_effect = [
                    start.replace(minute=2),
                    start.replace(minute=3),
                    start.replace(minute=4),
                ]
                restarted.initialize(
                    [
                        Match(
                            match_id="match-1",
                            total="4.5",
                            **match_details,
                        )
                    ]
                )
                restarted.record_updates(
                    [
                        Match(
                            match_id="match-1",
                            total="4.75",
                            **match_details,
                        )
                    ]
                )
                restarted.record_updates(
                    [
                        Match(
                            match_id="match-1",
                            total="5",
                            **match_details,
                        )
                    ]
                )

            logger_mock.info.assert_not_called()
            with closing(sqlite3.connect(database_path)) as connection:
                saved = connection.execute(
                    "SELECT match_id, strategy FROM signals"
                ).fetchall()
            self.assertEqual(saved, [("match-1", "over")])

    def test_duplicates_are_scoped_to_strategy_and_match_id(self):
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "matches.sqlite3"
            analyzer = MatchAnalyzer(database_path=database_path)
            signal = {
                "match_id": "match-1",
                "team": "Home",
                "anchor": {
                    "match_data": {
                        "match_id": "match-1",
                        "league": "League",
                        "home_team": "Home",
                        "away_team": "Away",
                        "match_time": "40",
                        "score": "0-0",
                    },
                    "market_data": {
                        "over": {"total": "3"},
                        "ah": {"handicap": "-0.5"},
                    },
                },
            }

            analyzer._save_signal("over", signal)
            analyzer._save_signal("over", signal)
            analyzer._save_signal("ah", signal)

            with closing(sqlite3.connect(database_path)) as connection:
                saved = connection.execute(
                    "SELECT strategy, match_id FROM signals ORDER BY strategy"
                ).fetchall()
            self.assertEqual(
                saved,
                [("ah", "match-1"), ("over", "match-1")],
            )

    def test_analyzes_and_notifies_a_new_handicap_signal(self):
        with TemporaryDirectory() as temp_dir:
            notifier = Mock()
            analyzer = MatchAnalyzer(
                database_path=Path(temp_dir) / "matches.sqlite3",
                notifier=notifier,
            )
            current = {
                "market_data": {"ah": {"handicap": "-1"}},
            }
            anchor = {
                "market_data": {"ah": {"handicap": "-1.5"}},
            }
            signal = {
                "match_id": "match-1",
                "team": "Away",
                "current": current,
                "anchor": anchor,
            }

            with (
                patch("analyzer.find_over_signal", return_value=None),
                patch("analyzer.find_ah_signal", return_value=signal),
                patch.object(
                    analyzer, "_save_signal", return_value="formatted"
                ) as save_signal,
                patch("analyzer.logger") as logger_mock,
            ):
                analyzer.copy_histories["match-1"] = [current, anchor]
                analyzer._analyze_match("match-1")

            save_signal.assert_called_once_with("ah", signal)
            logger_mock.info.assert_called_once_with(
                "match-1 -1 -> -1.5 | team: Away"
            )
            notifier.send_signal.assert_called_once_with(
                "ah",
                signal,
                formatted_message="formatted",
            )

    def test_does_not_notify_when_handicap_signal_was_not_inserted(self):
        with TemporaryDirectory() as temp_dir:
            notifier = Mock()
            analyzer = MatchAnalyzer(
                database_path=Path(temp_dir) / "matches.sqlite3",
                notifier=notifier,
            )
            current = {"market_data": {"ah": {"handicap": "1"}}}
            anchor = {"market_data": {"ah": {"handicap": "1.5"}}}
            signal = {
                "match_id": "match-1",
                "team": "Home",
                "current": current,
                "anchor": anchor,
            }

            with (
                patch("analyzer.find_over_signal", return_value=None),
                patch("analyzer.find_ah_signal", return_value=signal),
                patch.object(analyzer, "_save_signal", return_value=None),
                patch("analyzer.logger") as logger_mock,
            ):
                analyzer.copy_histories["match-1"] = [current, anchor]
                analyzer._analyze_match("match-1")

            logger_mock.info.assert_not_called()
            notifier.send_signal.assert_not_called()

    def test_ignores_matches_without_ids_and_unchanged_updates(self):
        with TemporaryDirectory() as temp_dir:
            analyzer = MatchAnalyzer(
                history_path=Path(temp_dir) / "history.json",
                database_path=Path(temp_dir) / "matches.sqlite3",
            )
            match = Match(match_id="match-1", score="0-0", total="3.5")

            self.assertFalse(analyzer._append_match(Match()))
            self.assertTrue(analyzer._append_match(match))
            self.assertFalse(analyzer._append_match(match))
            self.assertEqual(len(analyzer.histories["match-1"]), 1)

    def test_state_round_trip_continues_only_current_match_histories(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "match_state.json"
            database_path = Path(temp_dir) / "matches.sqlite3"
            original = MatchAnalyzer(database_path=database_path)
            original.initialize(
                [
                    Match(match_id="active", score="0-0", total="3.5"),
                    Match(match_id="finished", score="1-0", total="2.5"),
                ]
            )
            original.record_updates(
                [Match(match_id="active", score="0-0", total="3.75")]
            )
            active_deadline = datetime.now() + timedelta(minutes=1)
            original._closed_markets_until["active"] = active_deadline
            original._closed_markets_until["finished"] = active_deadline

            self.assertTrue(original.save_state(state_path))
            saved_state = load_state_from_json(state_path)

            self.assertIsNotNone(saved_state)
            self.assertFalse(state_path.exists())
            restarted = MatchAnalyzer(database_path=database_path)
            with patch.object(restarted, "_analyze_match"):
                restarted.initialize(
                    [
                        Match(
                            match_id="active",
                            score="0-0",
                            total="4",
                        ),
                        Match(match_id="new", score="0-0", total="1"),
                    ],
                    saved_state=saved_state,
                )

            self.assertEqual(
                [entry["market_data"]["over"]["total"]
                 for entry in restarted.histories["active"]],
                ["3.5", "3.75", "4"],
            )
            self.assertEqual(len(restarted.copy_histories["active"]), 3)
            self.assertNotIn("finished", restarted.histories)
            self.assertNotIn("finished", restarted.copy_histories)
            self.assertNotIn("finished", restarted._closed_markets_until)
            self.assertEqual(
                restarted._closed_markets_until["active"],
                active_deadline,
            )
            self.assertEqual(len(restarted.histories["new"]), 1)
            self.assertEqual(
                set(restarted.histories),
                set(restarted.copy_histories),
            )
            self.assertEqual(set(restarted.histories), {"active", "new"})

    def test_restore_keeps_an_unchanged_snapshot_and_expired_market_deadline(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "match_state.json"
            database_path = Path(temp_dir) / "matches.sqlite3"
            match = Match(match_id="match-1", score="1-0", total="3.5")
            original = MatchAnalyzer(database_path=database_path)
            with patch.object(original, "_analyze_match"):
                original.initialize([match])
            expired_deadline = datetime(2026, 10, 23, 12, 0)
            original._closed_markets_until["match-1"] = expired_deadline
            self.assertTrue(original.save_state(state_path))
            saved_state = load_state_from_json(state_path)

            restarted = MatchAnalyzer(database_path=database_path)
            with patch.object(restarted, "_analyze_match"):
                restarted.initialize([match], saved_state=saved_state)

            self.assertEqual(len(restarted.histories["match-1"]), 1)
            self.assertEqual(
                restarted._closed_markets_until["match-1"],
                expired_deadline,
            )

    def test_empty_state_round_trip_is_supported(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "match_state.json"
            analyzer = MatchAnalyzer(
                database_path=Path(temp_dir) / "matches.sqlite3"
            )

            self.assertTrue(analyzer.save_state(state_path))
            saved_state = load_state_from_json(state_path)

            self.assertEqual(
                saved_state,
                {
                    "active_match_ids": [],
                    "histories": {},
                    "copy_histories": {},
                    "closed_markets_until": {},
                },
            )
            with patch.object(analyzer, "_analyze_match") as analyze_match:
                analyzer.initialize([], saved_state=saved_state)
            analyze_match.assert_not_called()
            self.assertEqual(analyzer.histories, {})

    def test_load_state_returns_none_for_missing_file(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing.json"

            self.assertIsNone(load_state_from_json(path))

    def test_load_state_leaves_invalid_json_for_inspection(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text("{invalid", encoding="utf-8")
            with patch("analyzer.logger") as logger_mock:
                self.assertIsNone(load_state_from_json(path))

            self.assertTrue(path.exists())
            logger_mock.error.assert_called_once()

    def test_load_state_leaves_invalid_structure_for_inspection(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "active_match_ids": ["match-1"],
                        "histories": {"match-1": [{"broken": True}]},
                        "copy_histories": {"match-1": []},
                        "closed_markets_until": {},
                    }
                ),
                encoding="utf-8",
            )
            with patch("analyzer.logger") as logger_mock:
                self.assertIsNone(load_state_from_json(path))

            self.assertTrue(path.exists())
            logger_mock.error.assert_called_once()

    def test_load_state_preserves_file_when_removal_fails(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "active_match_ids": [],
                        "histories": {},
                        "copy_histories": {},
                        "closed_markets_until": {},
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(Path, "unlink", side_effect=OSError("denied")),
                patch("analyzer.logger") as logger_mock,
            ):
                self.assertIsNone(load_state_from_json(path))

            self.assertTrue(path.exists())
            logger_mock.error.assert_called_once()

    def test_save_state_reports_write_failure(self):
        with TemporaryDirectory() as temp_dir:
            analyzer = MatchAnalyzer(
                database_path=Path(temp_dir) / "matches.sqlite3"
            )
            with (
                patch.object(
                    Path,
                    "write_text",
                    side_effect=OSError("permission denied"),
                ),
                patch("analyzer.logger") as logger_mock,
            ):
                self.assertFalse(
                    analyzer.save_state(Path(temp_dir) / "state.json")
                )

            logger_mock.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
