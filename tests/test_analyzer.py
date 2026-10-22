import unittest
import json
from datetime import datetime
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock, patch

from analyzer import MatchAnalyzer
from models import Match


class MatchAnalyzerTests(unittest.TestCase):
    def test_saves_signal_before_sending_telegram_notification(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            signals_path = Path(temp_dir) / "matches.json"
            notifier = Mock()
            analyzer = MatchAnalyzer(
                history_path=history_path,
                signals_path=signals_path,
                notifier=notifier,
            )
            start = datetime(2026, 10, 22, 12, 0)
            notifier.send_signal.side_effect = lambda *_args: self.assertEqual(
                json.loads(signals_path.read_text(encoding="utf-8")),
                {"over": ["match-1 1 -> 1.5"], "ah": []},
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

    def test_empty_signals_file_is_treated_as_no_previous_signals(self):
        with TemporaryDirectory() as temp_dir:
            signals_path = Path(temp_dir) / "matches.json"

            for content in ("", " \n\t", "[]", '{"over": [], "ah": []}'):
                with self.subTest(content=content):
                    signals_path.write_text(content, encoding="utf-8")

                    analyzer = MatchAnalyzer(signals_path=signals_path)

                    self.assertEqual(
                        analyzer.signals, {"over": [], "ah": []}
                    )

    def test_new_history_entries_use_sortable_datetime_format(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            analyzer = MatchAnalyzer(history_path)
            now = datetime(2026, 10, 21, 20, 30, 9)

            with patch("analyzer.datetime") as datetime_mock:
                datetime_mock.now.return_value = now
                analyzer.initialize([Match(match_id="match-1")])

            self.assertEqual(
                analyzer.histories["match-1"][0]["observed_at"],
                "2026-10-21 20:30:09",
            )

    def test_over_signal_is_persisted_and_not_repeated_after_restart(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            signals_path = Path(temp_dir) / "matches.json"
            analyzer = MatchAnalyzer(history_path, signals_path)
            start = datetime(2026, 10, 22, 12, 0)

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
                    [Match(match_id="match-1", score="1-0", total="3.5")]
                )
                analyzer.record_updates(
                    [Match(match_id="match-1", score="1-0", total="3.75")]
                )
                analyzer.record_updates(
                    [Match(match_id="match-1", score="1-0", total="4")]
                )

            logger_mock.info.assert_called_once()
            saved = json.loads(signals_path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved, {"over": ["match-1 3.5 -> 4"], "ah": []}
            )
            self.assertEqual(
                logger_mock.info.call_args.args,
                ("match-1 3.5 -> 4",),
            )

            restarted = MatchAnalyzer(history_path, signals_path)
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
                    [Match(match_id="match-1", score="1-0", total="4.5")]
                )
                restarted.record_updates(
                    [Match(match_id="match-1", score="1-0", total="4.75")]
                )
                restarted.record_updates(
                    [Match(match_id="match-1", score="1-0", total="5")]
                )

            logger_mock.info.assert_not_called()
            saved = json.loads(signals_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["over"], ["match-1 3.5 -> 4"])

    def test_writing_over_signal_preserves_existing_ah_signal(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            signals_path = Path(temp_dir) / "matches.json"
            signals_path.write_text(
                json.dumps(
                    {
                        "over": [],
                        "ah": ["match-1 -1 -> -1.5 | team: Away"],
                    }
                ),
                encoding="utf-8",
            )
            analyzer = MatchAnalyzer(history_path, signals_path)
            start = datetime(2026, 10, 22, 12, 0)

            with (
                patch("analyzer.datetime") as datetime_mock,
                patch("analyzer.logger"),
            ):
                datetime_mock.now.side_effect = [
                    start,
                    start.replace(minute=1),
                    start.replace(minute=2),
                ]
                analyzer.initialize(
                    [Match(match_id="match-1", score="1-0", total="3.5")]
                )
                analyzer.record_updates(
                    [Match(match_id="match-1", score="1-0", total="3.75")]
                )
                analyzer.record_updates(
                    [Match(match_id="match-1", score="1-0", total="4")]
                )

            saved = json.loads(signals_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["ah"], ["match-1 -1 -> -1.5 | team: Away"])
            self.assertEqual(saved["over"], ["match-1 3.5 -> 4"])

    def test_ah_signal_is_independent_of_existing_over_signal(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            signals_path = Path(temp_dir) / "matches.json"
            signals_path.write_text(
                json.dumps(
                    {
                        "over": ["match-1 2.5 -> 3"],
                        "ah": [],
                    }
                ),
                encoding="utf-8",
            )
            analyzer = MatchAnalyzer(history_path, signals_path)
            start = datetime(2026, 10, 22, 12, 0)

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
                            score="1-0",
                            away_team="Away",
                            total="2.5",
                            ah_handicap="-1.5",
                        )
                    ]
                )
                analyzer.record_updates(
                    [
                        Match(
                            match_id="match-1",
                            score="1-0",
                            away_team="Away",
                            total="2.75",
                            ah_handicap="-1.75",
                        )
                    ]
                )
                analyzer.record_updates(
                    [
                        Match(
                            match_id="match-1",
                            score="1-0",
                            away_team="Away",
                            total="3",
                            ah_handicap="-2",
                        )
                    ]
                )

            saved = json.loads(signals_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["over"], ["match-1 2.5 -> 3"])
            self.assertEqual(saved["ah"], ["match-1 -1.5 -> -2 | team: Away"])
            logger_mock.info.assert_called_once()
            self.assertEqual(
                logger_mock.info.call_args.args,
                ("match-1 -1.5 -> -2 | team: Away",),
            )

    def test_invalid_signals_file_raises_clear_error(self):
        with TemporaryDirectory() as temp_dir:
            signals_path = Path(temp_dir) / "matches.json"
            signals_path.write_text("{invalid", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid signals file"):
                MatchAnalyzer(signals_path=signals_path)


if __name__ == "__main__":
    unittest.main()
