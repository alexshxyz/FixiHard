import signal
import unittest
from unittest.mock import Mock, call, patch

import main


class MainTests(unittest.TestCase):
    def setUp(self):
        self.playwright = Mock()
        self.browser = Mock()
        self.page = Mock()
        self.live_watch = Mock()
        self.analyzer = Mock()
        self.matches = [Mock(name="match")]
        self.updated_matches = [Mock(name="updated_match")]
        self.deleted_ids = ["deleted-match"]
        self.wait_count = 0
        self.shutdown_handlers = {}
        self.previous_handlers = {
            signal.SIGINT: Mock(name="previous_sigint"),
            signal.SIGTERM: Mock(name="previous_sigterm"),
        }

        self.patches = [
            patch("main.start_browser", return_value=(
                self.playwright, self.browser, Mock(), self.page
            )),
            patch("main.scrape_matches", return_value=self.matches),
            patch("main.MatchAnalyzer", return_value=self.analyzer),
            patch("main.start_live_watch", return_value=self.live_watch),
            patch("main.refresh_live_table"),
            patch("main._log_matches_updated"),
            patch("main.logger"),
            patch("main.random.randint", return_value=10),
            patch("main.time.monotonic", return_value=0),
            patch("main.signal.signal", side_effect=self._signal),
        ]
        self.mocks = [patcher.start() for patcher in self.patches]
        self.addCleanup(self._stop_patches)

        (
            self.start_browser,
            self.scrape_matches,
            self.match_analyzer,
            self.start_live_watch,
            self.refresh_live_table,
            self.log_matches_updated,
            self.logger,
            self.randint,
            self.monotonic,
            self.signal_call,
        ) = self.mocks

    def _signal(self, signum, handler):
        if handler is self.previous_handlers[signum]:
            return None
        if callable(handler):
            self.shutdown_handlers[signum] = handler
            return self.previous_handlers[signum]
        return None

    def _interrupt_page_wait(self, timeout):
        self._request_shutdown()
        raise RuntimeError("page interrupted")

    def _shutdown_after_second_wait(self, _timeout):
        self.wait_count += 1
        if self.wait_count == 2:
            self._request_shutdown(signal.SIGTERM)

    def _stop_patches(self):
        for patcher in reversed(self.patches):
            patcher.stop()

    def _request_shutdown(self, signum=signal.SIGINT):
        self.shutdown_handlers[signum](signum, None)

    def _assert_handlers_restored(self):
        self.assertEqual(
            self.signal_call.call_args_list,
            [
                call(signal.SIGINT, unittest.mock.ANY),
                call(signal.SIGTERM, unittest.mock.ANY),
                call(signal.SIGINT, self.previous_handlers[signal.SIGINT]),
                call(signal.SIGTERM, self.previous_handlers[signal.SIGTERM]),
            ],
        )

    def test_main_processes_updates_and_refreshes_at_deadline(self):
        self.page.wait_for_timeout.side_effect = self._shutdown_after_second_wait
        self.monotonic.side_effect = [0, 10, 20, 20]

        def start_watch(_page, on_update, initial_matches, on_matches_deleted):
            self.assertIs(initial_matches, self.matches)
            on_update(self.updated_matches)
            on_matches_deleted(self.deleted_ids)
            return self.live_watch

        self.start_live_watch.side_effect = start_watch

        main.main()

        self.start_browser.assert_called_once_with()
        self.scrape_matches.assert_has_calls(
            [call(self.page), call(self.page, log_odds_found=False)]
        )
        self.analyzer.initialize.assert_called_once_with(self.matches)
        self.analyzer.record_updates.assert_called_once_with(self.updated_matches)
        self.analyzer.remove_matches.assert_called_once_with(self.deleted_ids)
        self.log_matches_updated.assert_called_once_with(self.updated_matches)
        self.live_watch.process_pending.assert_has_calls([call(), call()])
        self.refresh_live_table.assert_called_once_with(self.page)
        self.live_watch.reconcile_after_refresh.assert_called_once_with(self.matches)
        self.assertEqual(self.randint.call_count, 2)
        self.browser.close.assert_called_once_with()
        self.playwright.stop.assert_called_once_with()
        self._assert_handlers_restored()
        self.logger.info.assert_any_call("Shutdown requested")

    def test_main_reraises_operation_error_without_shutdown_and_cleans_up(self):
        self.page.wait_for_timeout.side_effect = RuntimeError("page failed")

        with self.assertRaisesRegex(RuntimeError, "page failed"):
            main.main()

        self.browser.close.assert_called_once_with()
        self.playwright.stop.assert_called_once_with()
        self._assert_handlers_restored()
        self.logger.warning.assert_not_called()

    def test_main_logs_interruption_during_shutdown_and_continues_cleanup(self):
        self.page.wait_for_timeout.side_effect = self._interrupt_page_wait
        self.browser.close.side_effect = RuntimeError("close failed")
        self.playwright.stop.side_effect = RuntimeError("stop failed")

        main.main()

        self.logger.warning.assert_called_once_with(
            "Browser operation was interrupted during shutdown",
            exc_info=True,
        )
        self.logger.error.assert_has_calls(
            [
                call("Failed to close browser", exc_info=True),
                call("Failed to stop Playwright", exc_info=True),
            ]
        )
        self._assert_handlers_restored()

    def test_main_restores_handlers_when_browser_startup_fails(self):
        self.start_browser.side_effect = RuntimeError("startup failed")

        with self.assertRaisesRegex(RuntimeError, "startup failed"):
            main.main()

        self.browser.close.assert_not_called()
        self.playwright.stop.assert_not_called()
        self._assert_handlers_restored()


if __name__ == "__main__":
    unittest.main()
