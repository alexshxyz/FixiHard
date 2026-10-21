import unittest
from unittest.mock import Mock, call, patch

import browser
from timing import seconds_to_milliseconds


class BrowserFunctionTests(unittest.TestCase):
    def setUp(self):
        self.logger_patcher = patch("browser.logger")
        self.logger = self.logger_patcher.start()
        self.addCleanup(self.logger_patcher.stop)

    def test_launch_browser_uses_project_configuration_and_returns_browser(self):
        playwright = Mock()
        expected_browser = Mock()
        playwright.chromium.launch.return_value = expected_browser

        with patch("browser.config.HEADLESS", False):
            result = browser.launch_browser(playwright)

        self.assertIs(result, expected_browser)
        playwright.chromium.launch.assert_called_once_with(
            headless=False,
            args=[
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-notifications",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-extensions",
                "--disable-sync",
                "--metrics-recording-only",
                "--mute-audio",
            ],
        )
        self.logger.info.assert_called_once_with("Bot started successfully!")

    def test_launch_browser_propagates_launch_failure(self):
        playwright = Mock()
        playwright.chromium.launch.side_effect = RuntimeError("launch failed")

        with self.assertRaisesRegex(RuntimeError, "launch failed"):
            browser.launch_browser(playwright)

        self.logger.info.assert_not_called()

    def test_create_page_configures_context_and_returns_context_and_page(self):
        context = Mock()
        page = Mock()
        browser_instance = Mock()
        browser_instance.new_context.return_value = context
        context.new_page.return_value = page
        cookies = [{"name": "session", "value": "test"}]

        with patch("browser.config.SITE_COOKIES", cookies):
            result = browser.create_page(browser_instance)

        self.assertEqual(result, (context, page))
        browser_instance.new_context.assert_called_once_with()
        context.add_cookies.assert_called_once_with(cookies)
        context.new_page.assert_called_once_with()
        page.set_default_navigation_timeout.assert_called_once_with(
            seconds_to_milliseconds(
                browser.config.PAGE_NAVIGATION_TIMEOUT_SECONDS
            )
        )
        page.set_default_timeout.assert_called_once_with(
            seconds_to_milliseconds(
                browser.config.BROWSER_DEFAULT_TIMEOUT_SECONDS
            )
        )
        self.logger.info.assert_called_once_with("Cookies set")

    def test_create_page_accepts_empty_cookie_configuration(self):
        context = Mock()
        page = Mock()
        browser_instance = Mock()
        browser_instance.new_context.return_value = context
        context.new_page.return_value = page

        with patch("browser.config.SITE_COOKIES", []):
            result = browser.create_page(browser_instance)

        self.assertEqual(result, (context, page))
        context.add_cookies.assert_called_once_with([])

    def test_create_page_propagates_cookie_error_without_creating_page(self):
        context = Mock()
        browser_instance = Mock()
        browser_instance.new_context.return_value = context
        context.add_cookies.side_effect = ValueError("invalid cookies")

        with self.assertRaisesRegex(ValueError, "invalid cookies"):
            browser.create_page(browser_instance)

        context.new_page.assert_not_called()
        self.logger.info.assert_not_called()

    def test_open_site_navigates_and_logs_success(self):
        page = Mock()

        with patch("browser.config.SITE_URL", "https://example.test/"):
            browser.open_site(page)

        page.goto.assert_called_once_with(
            "https://example.test/", wait_until="domcontentloaded"
        )
        self.logger.info.assert_has_calls([call("Loading site.."), call("OK")])

    def test_open_site_propagates_navigation_error_without_success_log(self):
        page = Mock()
        page.goto.side_effect = RuntimeError("navigation failed")

        with self.assertRaisesRegex(RuntimeError, "navigation failed"):
            browser.open_site(page)

        self.logger.info.assert_called_once_with("Loading site..")

    def test_select_live_tab_waits_clicks_and_waits_for_table(self):
        page = Mock()

        browser.select_live_tab(page)

        page.locator.assert_called_once_with("#li_FilterLive")
        page.locator.return_value.wait_for.assert_called_once_with(state="visible")
        page.locator.return_value.click.assert_called_once_with()
        page.wait_for_selector.assert_called_once_with(
            "#table_live tr.tds",
            state="attached",
            timeout=seconds_to_milliseconds(
                browser.config.TABLE_TIMEOUT_SECONDS
            ),
        )
        page.wait_for_timeout.assert_called_once_with(
            seconds_to_milliseconds(browser.config.POST_REFRESH_WAIT_SECONDS)
        )

    def test_select_live_tab_does_not_click_when_tab_is_not_visible(self):
        page = Mock()
        page.locator.return_value.wait_for.side_effect = TimeoutError(
            "tab did not appear"
        )

        with self.assertRaisesRegex(TimeoutError, "tab did not appear"):
            browser.select_live_tab(page)

        page.locator.return_value.click.assert_not_called()
        page.wait_for_selector.assert_not_called()
        page.wait_for_timeout.assert_not_called()

    def test_select_live_tab_propagates_missing_table_error_without_final_wait(self):
        page = Mock()
        page.wait_for_selector.side_effect = TimeoutError("table did not appear")

        with self.assertRaisesRegex(TimeoutError, "table did not appear"):
            browser.select_live_tab(page)

        page.locator.return_value.click.assert_called_once_with()
        page.wait_for_timeout.assert_not_called()

    def test_refresh_live_table_checks_odds_after_click(self):
        page = Mock()

        with patch("scraper.wait_for_valid_match_odds", return_value=True) as wait_odds:
            result = browser.refresh_live_table(page)

        self.assertTrue(result)
        self.assertEqual(
            page.locator.call_args_list,
            [call("#li_FilterLive"), call("table#table_live")],
        )
        page.locator.return_value.wait_for.assert_has_calls(
            [
                call(state="visible"),
                call(
                    timeout=seconds_to_milliseconds(
                        browser.config.TABLE_TIMEOUT_SECONDS
                    )
                ),
            ]
        )
        page.locator.return_value.click.assert_called_once_with()
        page.wait_for_timeout.assert_called_once_with(
            seconds_to_milliseconds(browser.config.POST_REFRESH_WAIT_SECONDS)
        )
        wait_odds.assert_called_once_with(page)
        self.logger.info.assert_has_calls(
            [call("Refreshing live table.."), call("Refreshed successfully")]
        )

    def test_refresh_live_table_returns_false_when_odds_are_missing(self):
        page = Mock()

        with patch("scraper.wait_for_valid_match_odds", return_value=False):
            result = browser.refresh_live_table(page)

        self.assertFalse(result)
        self.logger.info.assert_called_once_with("Refreshing live table..")

    def test_refresh_live_table_propagates_click_error_without_success_log(self):
        page = Mock()
        page.locator.return_value.click.side_effect = RuntimeError("click failed")

        with self.assertRaisesRegex(RuntimeError, "click failed"):
            browser.refresh_live_table(page)

        page.wait_for_timeout.assert_not_called()
        self.logger.info.assert_called_once_with("Refreshing live table..")

    def test_refresh_page_reloads_and_waits_for_valid_data(self):
        page = Mock()

        with patch("scraper.wait_for_valid_match_odds", return_value=True) as wait_odds:
            result = browser.refresh_page(page)

        self.assertTrue(result)
        page.reload.assert_called_once_with(
            wait_until="domcontentloaded",
            timeout=seconds_to_milliseconds(
                browser.config.PAGE_NAVIGATION_TIMEOUT_SECONDS
            ),
        )
        page.locator.assert_called_once_with("table#table_live")
        page.locator.return_value.wait_for.assert_called_once_with(
            timeout=seconds_to_milliseconds(
                browser.config.PAGE_TABLE_TIMEOUT_SECONDS
            )
        )
        wait_odds.assert_called_once_with(page)
        page.wait_for_timeout.assert_called_once_with(
            seconds_to_milliseconds(browser.config.POST_REFRESH_WAIT_SECONDS)
        )
        self.logger.info.assert_any_call("Page refreshed")

    def test_refresh_page_returns_false_when_odds_are_missing(self):
        page = Mock()

        with patch("scraper.wait_for_valid_match_odds", return_value=False):
            result = browser.refresh_page(page)

        self.assertFalse(result)
        page.reload.assert_called_once_with(
            wait_until="domcontentloaded",
            timeout=seconds_to_milliseconds(
                browser.config.PAGE_NAVIGATION_TIMEOUT_SECONDS
            ),
        )
        page.wait_for_timeout.assert_not_called()
        self.logger.info.assert_called_once_with("Refreshing page...")

    def test_refresh_page_logs_and_reraises_refresh_errors(self):
        page = Mock()
        page.reload.side_effect = RuntimeError("navigation failed")

        with self.assertRaisesRegex(RuntimeError, "navigation failed"):
            browser.refresh_page(page)

        self.logger.error.assert_called_once_with(
            "Failed to refresh page: %s",
            page.reload.side_effect,
            exc_info=True,
        )

class StartBrowserTests(unittest.TestCase):
    def setUp(self):
        self.playwright = Mock()
        self.browser_instance = Mock()
        self.context = Mock()
        self.page = Mock()
        self.sync_playwright = Mock()
        self.sync_playwright.return_value.start.return_value = self.playwright
        self.patchers = [
            patch("playwright.sync_api.sync_playwright", self.sync_playwright),
            patch("browser.launch_browser", return_value=self.browser_instance),
            patch(
                "browser.create_page",
                return_value=(self.context, self.page),
            ),
            patch("browser.open_site"),
            patch("browser.select_live_tab"),
            patch("browser.logger"),
        ]
        self.mocks = [patcher.start() for patcher in self.patchers]
        self.addCleanup(self._stop_patchers)
        (
            self.launch_browser,
            self.create_page,
            self.open_site,
            self.select_live_tab,
            self.logger,
        ) = self.mocks[1:]

    def _stop_patchers(self):
        for patcher in reversed(self.patchers):
            patcher.stop()

    def test_start_browser_returns_resources_after_startup(self):
        result = browser.start_browser()

        self.assertEqual(
            result,
            (
                self.playwright,
                self.browser_instance,
                self.context,
                self.page,
            ),
        )
        self.sync_playwright.return_value.start.assert_called_once_with()
        self.launch_browser.assert_called_once_with(self.playwright)
        self.create_page.assert_called_once_with(self.browser_instance)
        self.open_site.assert_called_once_with(self.page)
        self.select_live_tab.assert_called_once_with(self.page)
        self.browser_instance.close.assert_not_called()
        self.playwright.stop.assert_not_called()

    def test_start_browser_stops_playwright_when_browser_launch_fails(self):
        self.launch_browser.side_effect = RuntimeError("launch failed")

        with self.assertRaisesRegex(RuntimeError, "launch failed"):
            browser.start_browser()

        self.browser_instance.close.assert_not_called()
        self.playwright.stop.assert_called_once_with()
        self.create_page.assert_not_called()

    def test_start_browser_closes_browser_and_stops_playwright_after_page_setup_fails(
        self,
    ):
        self.create_page.side_effect = RuntimeError("page setup failed")

        with self.assertRaisesRegex(RuntimeError, "page setup failed"):
            browser.start_browser()

        self.browser_instance.close.assert_called_once_with()
        self.playwright.stop.assert_called_once_with()
        self.open_site.assert_not_called()

    def test_start_browser_cleans_up_after_site_or_live_tab_failure(self):
        for failing_step in (self.open_site, self.select_live_tab):
            with self.subTest(step=failing_step._mock_name or "startup step"):
                self.browser_instance.reset_mock()
                self.playwright.reset_mock()
                self.open_site.reset_mock()
                self.select_live_tab.reset_mock()
                failing_step.side_effect = RuntimeError("startup failed")

                with self.assertRaisesRegex(RuntimeError, "startup failed"):
                    browser.start_browser()

                self.browser_instance.close.assert_called_once_with()
                self.playwright.stop.assert_called_once_with()
                failing_step.side_effect = None

    def test_start_browser_preserves_startup_error_when_cleanup_also_fails(self):
        self.open_site.side_effect = RuntimeError("navigation failed")
        self.browser_instance.close.side_effect = RuntimeError("close failed")
        self.playwright.stop.side_effect = RuntimeError("stop failed")

        with self.assertRaisesRegex(RuntimeError, "navigation failed"):
            browser.start_browser()

        self.browser_instance.close.assert_called_once_with()
        self.playwright.stop.assert_called_once_with()
        self.logger.error.assert_has_calls(
            [
                call("Failed to close browser after startup error", exc_info=True),
                call("Failed to stop Playwright after startup error", exc_info=True),
            ]
        )


if __name__ == "__main__":
    unittest.main()
