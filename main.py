import random
import signal
import threading
import time

from analyzer import MatchAnalyzer
import config
from browser import refresh_live_table, refresh_page, start_browser
from logger import logger
from scraper import (
    _log_matches_updated,
    reattach_live_watch,
    scrape_matches,
    start_live_watch,
)

NO_MATCHES_RETRY_DELAY_MS = 60_000
NO_MATCHES_RETRY_MESSAGE = (
    "No matches found. Waiting 60 seconds before reloading the page."
)


def _refresh_page_until_odds(page):
    while not refresh_page(page):
        logger.warning(NO_MATCHES_RETRY_MESSAGE)
        page.wait_for_timeout(NO_MATCHES_RETRY_DELAY_MS)
    reattach_live_watch(page)


def main():
    playwright = None
    browser = None
    shutdown_requested = threading.Event()

    def request_shutdown(_signum, _frame):
        shutdown_requested.set()

    previous_handlers = {
        signum: signal.signal(signum, request_shutdown)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        playwright, browser, _, page = start_browser()
        initial_matches = scrape_matches(page)
        analyzer = MatchAnalyzer()
        analyzer.initialize(initial_matches)

        def on_matches_update(matches):
            analyzer.record_updates(matches)
            _log_matches_updated(matches)

        live_watch = start_live_watch(
            page,
            on_matches_update,
            initial_matches,
            on_matches_deleted=analyzer.remove_matches,
        )
        next_refresh_at = time.monotonic() + random.randint(
            *config.LIVE_REFRESH_INTERVAL_SECONDS
        )
        next_page_refresh_at = (
            time.monotonic() + config.PAGE_REFRESH_INTERVAL_SECONDS
        )
        while not shutdown_requested.is_set():
            page.wait_for_timeout(1_000)
            live_watch.process_pending()
            now = time.monotonic()
            if now >= next_page_refresh_at:
                _refresh_page_until_odds(page)
                refreshed_matches = scrape_matches(page, log_odds_found=False)
                live_watch.reconcile_after_refresh(refreshed_matches)
                next_page_refresh_at = (
                    time.monotonic() + config.PAGE_REFRESH_INTERVAL_SECONDS
                )
                next_refresh_at = time.monotonic() + random.randint(
                    *config.LIVE_REFRESH_INTERVAL_SECONDS
                )
            elif now >= next_refresh_at:
                page_was_reloaded = False
                if not refresh_live_table(page):
                    logger.warning(NO_MATCHES_RETRY_MESSAGE)
                    page.wait_for_timeout(NO_MATCHES_RETRY_DELAY_MS)
                    _refresh_page_until_odds(page)
                    page_was_reloaded = True
                refreshed_matches = scrape_matches(page, log_odds_found=False)
                live_watch.reconcile_after_refresh(refreshed_matches)
                next_refresh_at = time.monotonic() + random.randint(
                    *config.LIVE_REFRESH_INTERVAL_SECONDS
                )
                if page_was_reloaded:
                    next_page_refresh_at = (
                        time.monotonic() + config.PAGE_REFRESH_INTERVAL_SECONDS
                    )
    except Exception:
        if not shutdown_requested.is_set():
            raise
        logger.warning(
            "Browser operation was interrupted during shutdown",
            exc_info=True,
        )
    finally:
        if shutdown_requested.is_set():
            logger.info("Shutdown requested")

        if browser is not None:
            try:
                browser.close()
                logger.info("Browser closed")
            except Exception:
                logger.error("Failed to close browser", exc_info=True)

        if playwright is not None:
            try:
                playwright.stop()
                logger.info("Playwright stopped")
            except Exception:
                logger.error("Failed to stop Playwright", exc_info=True)

        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)


if __name__ == "__main__":
    main()
