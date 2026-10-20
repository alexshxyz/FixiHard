import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import scraper
from models import Match


class ScraperWaitTests(unittest.TestCase):
    def setUp(self):
        self.logger_patcher = patch("scraper.logger")
        self.logger = self.logger_patcher.start()
        self.addCleanup(self.logger_patcher.stop)

    def test_wait_for_match_data_waits_for_attached_match_rows(self):
        page = Mock()

        scraper.wait_for_match_data(page)

        page.wait_for_selector.assert_called_once_with(
            "#table_live tr.tds", state="attached", timeout=10_000
        )

    def test_wait_for_match_data_propagates_timeout(self):
        page = Mock()
        page.wait_for_selector.side_effect = TimeoutError("rows did not load")

        with self.assertRaisesRegex(TimeoutError, "rows did not load"):
            scraper.wait_for_match_data(page)

    def test_wait_for_match_odds_waits_and_logs_by_default(self):
        page = Mock()

        scraper.wait_for_match_odds(page)

        script, = page.wait_for_function.call_args.args
        self.assertIn("return hasBet365Odds && hasVisibleOdds", script)
        self.assertIn("#table_live tr.tds", script)
        self.assertNotIn("__GLOBAL_ODDS_READY__", script)
        page.wait_for_function.assert_called_once_with(script, timeout=30_000)
        self.logger.info.assert_called_once_with("Bet365 odds found")

    def test_wait_for_match_odds_can_suppress_success_log(self):
        page = Mock()

        scraper.wait_for_match_odds(page, log_success=False)

        page.wait_for_function.assert_called_once()
        self.logger.info.assert_not_called()

    def test_wait_for_match_odds_propagates_timeout_without_success_log(self):
        page = Mock()
        page.wait_for_function.side_effect = TimeoutError("odds unavailable")

        with self.assertRaisesRegex(TimeoutError, "odds unavailable"):
            scraper.wait_for_match_odds(page)

        self.logger.info.assert_not_called()


class ScraperCollectionTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock()
        self.logger_patcher = patch("scraper.logger")
        self.logger = self.logger_patcher.start()
        self.addCleanup(self.logger_patcher.stop)

    def test_league_names_evaluates_dom_and_returns_mapping(self):
        expected = {"league-1": "League One"}
        self.page.evaluate.return_value = expected

        result = scraper._league_names(self.page)

        self.assertIs(result, expected)
        script, = self.page.evaluate.call_args.args
        self.assertIn("tr.Leaguestitle[sclassid]", script)
        self.assertIn(".trim()", script)

    def test_load_all_matches_maps_every_scraped_field_to_model(self):
        self.page.evaluate.return_value = [
            {
                "match_id": "m-1",
                "league_id": "l-1",
                "match_time": "72",
                "home_team": "Home",
                "away_team": "Away",
                "score": "2-1",
                "redcards": 1,
                "over_odd": "1.8",
                "under_odd": "2.1",
                "total": "2.5",
                "ah_home_odd": "1.9",
                "ah_away_odd": "2.0",
                "ah_handicap": "-0.5",
            }
        ]

        matches = scraper._load_all_matches_data(self.page)

        self.assertEqual(
            matches,
            [
                Match(
                    match_id="m-1",
                    league_id="l-1",
                    home_team="Home",
                    away_team="Away",
                    match_time="72",
                    score="2-1",
                    redcards=1,
                    over_odd="1.8",
                    under_odd="2.1",
                    total="2.5",
                    ah_home_odd="1.9",
                    ah_away_odd="2.0",
                    ah_handicap="-0.5",
                )
            ],
        )

    def test_load_all_matches_returns_empty_list_for_empty_dom_result(self):
        self.page.evaluate.return_value = []

        self.assertEqual(scraper._load_all_matches_data(self.page), [])

    def test_load_all_matches_propagates_missing_field_error(self):
        self.page.evaluate.return_value = [{"match_id": "m-1"}]

        with self.assertRaises(KeyError):
            scraper._load_all_matches_data(self.page)

    def test_collect_current_matches_sets_leagues_and_skips_duplicate_ids(self):
        first = Match(
            match_id="m-1",
            league_id="l-1",
            home_team="Home",
            away_team="Away",
        )
        duplicate = Match(
            match_id="m-1",
            league_id="l-2",
            home_team="Duplicate",
            away_team="Ignored",
        )
        other = Match(
            match_id="m-2",
            league_id="unmapped",
            home_team="Other",
            away_team="Team",
        )
        with (
            patch("scraper._league_names", return_value={"l-1": "League One"}),
            patch(
                "scraper._load_all_matches_data",
                return_value=[first, duplicate, other],
            ),
        ):
            result = scraper._collect_current_matches(self.page)

        self.assertEqual(result, [first, other])
        self.assertEqual(first.league, "League One")
        self.assertEqual(other.league, "")
        self.logger.warning.assert_not_called()

    def test_collect_current_matches_skips_matches_missing_either_team(self):
        valid = Match(match_id="valid", home_team="Home", away_team="Away")
        missing_home = Match(match_id="missing-home", away_team="Away")
        missing_away = Match(match_id="missing-away", home_team="Home")
        with (
            patch("scraper._league_names", return_value={}),
            patch(
                "scraper._load_all_matches_data",
                return_value=[valid, missing_home, missing_away],
            ),
        ):
            result = scraper._collect_current_matches(self.page)

        self.assertEqual(result, [valid])
        self.logger.warning.assert_has_calls(
            [
                call("Match %s has no team data; skipping", "missing-home"),
                call("Match %s has no team data; skipping", "missing-away"),
            ]
        )

    def test_collect_current_matches_keeps_empty_ids_but_warns_for_missing_teams(self):
        first = Match(home_team="Home", away_team="Away")
        second = Match(home_team="Home 2", away_team="Away 2")
        missing_teams = Match()
        with (
            patch("scraper._league_names", return_value={}),
            patch(
                "scraper._load_all_matches_data",
                return_value=[first, second, missing_teams],
            ),
        ):
            result = scraper._collect_current_matches(self.page)

        self.assertEqual(result, [first, second])
        self.logger.warning.assert_called_once_with(
            "Match %s has no team data; skipping", ""
        )


class ScraperPersistenceAndLoggingTests(unittest.TestCase):
    def setUp(self):
        self.logger_patcher = patch("scraper.logger")
        self.logger = self.logger_patcher.start()
        self.addCleanup(self.logger_patcher.stop)

    def test_write_matches_total_writes_utf8_json_with_all_match_data(self):
        matches = [
            Match(
                match_id="m-1",
                home_team="Команда",
                away_team="Away",
                redcards=1,
            )
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "matches.json"

            scraper._write_matches_total(matches, output_path)

            written = json.loads(output_path.read_text(encoding="utf-8"))
            rendered = output_path.read_text(encoding="utf-8")

        self.assertEqual(written, [matches[0].to_dict()])
        self.assertIn("\u041a\u043e\u043c\u0430\u043d\u0434\u0430", rendered)

    def test_write_matches_total_writes_empty_list(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "matches.json"

            scraper._write_matches_total([], output_path)

            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")), []
            )

    def test_write_matches_total_uses_default_json_path(self):
        output_file = Mock()
        resolved_path = Mock()
        resolved_path.with_name.return_value = output_file

        with patch("scraper.Path", return_value=resolved_path) as path_constructor:
            scraper._write_matches_total([])

        path_constructor.assert_called_once_with(scraper.__file__)
        resolved_path.with_name.assert_called_once_with("matches_total.json")
        output_file.write_text.assert_called_once_with(
            "[]",
            encoding="utf-8",
        )

    def test_write_matches_total_propagates_file_error(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_parent_path = (
                Path(temporary_directory) / "missing" / "matches.json"
            )

            with self.assertRaises(FileNotFoundError):
                scraper._write_matches_total([], missing_parent_path)

    def test_scrape_matches_runs_waits_collects_writes_and_logs(self):
        page = Mock()
        matches = [
            Match(match_id="m-1"),
            Match(match_id="m-2"),
        ]
        with (
            patch("scraper.wait_for_match_data") as wait_data,
            patch("scraper.wait_for_match_odds") as wait_odds,
            patch("scraper._collect_current_matches", return_value=matches),
            patch("scraper._write_matches_total") as write_total,
        ):
            result = scraper.scrape_matches(page)

        self.assertIs(result, matches)
        wait_data.assert_called_once_with(page)
        wait_odds.assert_called_once_with(page, log_success=True)
        write_total.assert_called_once_with(matches)
        self.logger.info.assert_called_once_with(
            "Active matches: %d%s", 2, " (m-1, m-2)"
        )

    def test_scrape_matches_can_skip_odds_success_log(self):
        page = Mock()
        with (
            patch("scraper.wait_for_match_data") as wait_data,
            patch("scraper.wait_for_match_odds") as wait_odds,
            patch("scraper._collect_current_matches", return_value=[]),
            patch("scraper._write_matches_total") as write_total,
        ):
            result = scraper.scrape_matches(page, log_odds_found=False)

        self.assertEqual(result, [])
        wait_data.assert_called_once_with(page)
        wait_odds.assert_called_once_with(page, log_success=False)
        write_total.assert_called_once_with([])
        self.logger.info.assert_called_once_with("Active matches: %d%s", 0, "")

    def test_scrape_matches_stops_after_wait_failure_without_writing(self):
        page = Mock()
        with (
            patch("scraper.wait_for_match_data", side_effect=TimeoutError("no rows")),
            patch("scraper.wait_for_match_odds") as wait_odds,
            patch("scraper._collect_current_matches") as collect,
            patch("scraper._write_matches_total") as write_total,
        ):
            with self.assertRaisesRegex(TimeoutError, "no rows"):
                scraper.scrape_matches(page)

        wait_odds.assert_not_called()
        collect.assert_not_called()
        write_total.assert_not_called()

    def test_scrape_matches_stops_after_save_failure_without_success_log(self):
        page = Mock()
        matches = [Match(match_id="m-1")]
        with (
            patch("scraper.wait_for_match_data"),
            patch("scraper.wait_for_match_odds"),
            patch("scraper._collect_current_matches", return_value=matches),
            patch(
                "scraper._write_matches_total",
                side_effect=OSError("disk full"),
            ),
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                scraper.scrape_matches(page)

        self.logger.info.assert_not_called()

    def test_log_matches_updated_formats_ids_and_empty_list(self):
        scraper._log_matches_updated(
            [Match(match_id="m-1"), Match(match_id="m-2")]
        )
        scraper._log_matches_updated([])

        self.logger.info.assert_has_calls(
            [
                call("Matches updated: %d%s", 2, " (m-1, m-2)"),
                call("Matches updated: %d%s", 0, ""),
            ]
        )


class StartLiveWatchTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock()
        self.on_update = Mock()
        self.on_deleted = Mock()
        self.initial_matches = [Match(match_id="m-1")]
        self.live_watch = Mock()
        self.collect_patcher = patch(
            "scraper._collect_current_matches",
            return_value=self.initial_matches,
        )
        self.collect_matches = self.collect_patcher.start()
        self.addCleanup(self.collect_patcher.stop)
        self.watch_patcher = patch("scraper._LiveWatch", return_value=self.live_watch)
        self.watch_class = self.watch_patcher.start()
        self.addCleanup(self.watch_patcher.stop)

    def test_start_live_watch_registers_observer_and_callback(self):
        result = scraper.start_live_watch(
            self.page,
            self.on_update,
            self.initial_matches,
            self.on_deleted,
        )

        callback_name = f"__scraper_dom_changed_{id(self.page)}"
        observer_key = f"__scraper_live_observer_{id(self.page)}"
        self.assertIs(result, self.live_watch)
        self.collect_matches.assert_not_called()
        self.watch_class.assert_called_once_with(
            self.page,
            observer_key,
            self.on_update,
            self.initial_matches,
            scraper._collect_current_matches,
            self.on_deleted,
        )
        self.page.expose_function.assert_called_once()
        exposed_name, callback = self.page.expose_function.call_args.args
        self.assertEqual(exposed_name, callback_name)
        callback()
        self.live_watch._mark_dom_change.assert_called_once_with()
        script, args = self.page.evaluate.call_args.args
        self.assertEqual(args, [callback_name, observer_key])
        self.assertIn("new MutationObserver", script)
        self.assertIn("observer.observe(document.documentElement", script)
        self.assertIn("table#table_live", script)

    def test_start_live_watch_collects_initial_matches_only_when_none(self):
        result = scraper.start_live_watch(self.page, self.on_update)

        self.assertIs(result, self.live_watch)
        self.collect_matches.assert_called_once_with(self.page)
        self.watch_class.assert_called_once()
        self.assertEqual(
            self.watch_class.call_args.args[3],
            self.initial_matches,
        )

    def test_start_live_watch_preserves_explicit_empty_initial_matches(self):
        result = scraper.start_live_watch(
            self.page,
            self.on_update,
            initial_matches=[],
        )

        self.assertIs(result, self.live_watch)
        self.collect_matches.assert_not_called()
        self.assertEqual(self.watch_class.call_args.args[3], [])

    def test_start_live_watch_rejects_non_callable_update_callback(self):
        with self.assertRaisesRegex(
            TypeError, "on_matches_update must be a callable object"
        ):
            scraper.start_live_watch(self.page, None)

        self.collect_matches.assert_not_called()
        self.watch_class.assert_not_called()
        self.page.expose_function.assert_not_called()

    def test_start_live_watch_rejects_non_callable_delete_callback(self):
        with self.assertRaisesRegex(
            TypeError, "on_matches_deleted must be a callable object"
        ):
            scraper.start_live_watch(
                self.page,
                self.on_update,
                on_matches_deleted=False,
            )

        self.collect_matches.assert_not_called()
        self.watch_class.assert_not_called()
        self.page.expose_function.assert_not_called()

    def test_start_live_watch_propagates_missing_table_error(self):
        self.page.evaluate.side_effect = RuntimeError("#table_live not found.")

        with self.assertRaisesRegex(RuntimeError, "#table_live not found"):
            scraper.start_live_watch(self.page, self.on_update, [])

        self.page.expose_function.assert_called_once()
        self.watch_class.assert_called_once()

    def test_start_live_watch_propagates_expose_function_error(self):
        self.page.expose_function.side_effect = RuntimeError(
            "callback registration failed"
        )

        with self.assertRaisesRegex(
            RuntimeError, "callback registration failed"
        ):
            scraper.start_live_watch(self.page, self.on_update, [])

        self.page.evaluate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
