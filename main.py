import random
import signal
import threading
import time
from functools import partial

from analyzer import MatchAnalyzer
import config
from browser import refresh_live_table, refresh_page, start_browser
from logger import logger
from notifier import TelegramNotifier
from scraper import (
    _log_matches_updated,
    reattach_live_watch,
    scrape_matches,
    start_live_watch,
)
from timing import wait_for_seconds

class ScriptRestartRequested(Exception):
    pass


def _wait_for_matches(page):
    logger.warning(
        "No matches found. Waiting %d seconds before reloading the page.",
        config.NO_MATCHES_RETRY_SECONDS,
    )
    wait_for_seconds(page, config.NO_MATCHES_RETRY_SECONDS)


def _refresh_live_table_with_retries(page):
    for attempt in range(1, config.REFRESH_RETRY_ATTEMPTS + 1):
        try:
            return refresh_live_table(page)
        except Exception:
            logger.exception(
                "Live table refresh failed (attempt %d/%d)",
                attempt,
                config.REFRESH_RETRY_ATTEMPTS,
            )
            if attempt < config.REFRESH_RETRY_ATTEMPTS:
                wait_for_seconds(page, config.LIVE_REFRESH_RETRY_SECONDS)
    return None


def _refresh_page_until_odds(page):
    failed_attempts = 0
    while True:
        try:
            refreshed = refresh_page(page)
        except Exception:
            failed_attempts += 1
            logger.exception(
                "Page refresh failed (attempt %d/%d)",
                failed_attempts,
                config.REFRESH_RETRY_ATTEMPTS,
            )
            if failed_attempts >= config.REFRESH_RETRY_ATTEMPTS:
                raise ScriptRestartRequested(
                    "Page refresh failed after all retries"
                )
            wait_for_seconds(page, config.PAGE_REFRESH_RETRY_SECONDS)
            continue

        if refreshed:
            reattach_live_watch(page)
            return

        failed_attempts = 0
        _wait_for_matches(page)


def _request_shutdown(shutdown_requested, _signum, _frame):
    shutdown_requested.set()


def _record_match_updates(analyzer, matches):
    analyzer.record_updates(matches)
    _log_matches_updated(matches)


def _refresh_page_and_reconcile(page, live_watch):
    _refresh_page_until_odds(page)
    refreshed_matches = scrape_matches(page, log_odds_found=False)
    live_watch.reconcile_after_refresh(refreshed_matches)


def _refresh_live_table_and_reconcile(page, live_watch):
    live_refresh_result = _refresh_live_table_with_retries(page)
    page_was_reloaded = live_refresh_result is not True
    if page_was_reloaded:
        if live_refresh_result is False:
            _wait_for_matches(page)
        else:
            logger.warning(
                "Live table refresh failed after all retries. "
                "Falling back to a page refresh."
            )
        _refresh_page_until_odds(page)

    refreshed_matches = scrape_matches(page, log_odds_found=False)
    live_watch.reconcile_after_refresh(refreshed_matches)
    return page_was_reloaded


def run_forever():
    while True:
        try:
            main()
            return
        except ScriptRestartRequested as error:
            logger.error("%s. Restarting bot from a clean state.", error)


def main():
    playwright = None
    browser = None
    shutdown_requested = threading.Event()

    previous_handlers = {
        signum: signal.signal(
            signum, partial(_request_shutdown, shutdown_requested)
        )
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        notifier = TelegramNotifier.from_environment()
        playwright, browser, _, page = start_browser()
        initial_matches = scrape_matches(page)
        analyzer = MatchAnalyzer(notifier=notifier)
        analyzer.initialize(initial_matches)

        live_watch = start_live_watch(
            page,
            partial(_record_match_updates, analyzer),
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
            wait_for_seconds(page, config.MAIN_LOOP_WAIT_SECONDS)
            live_watch.process_pending()
            now = time.monotonic()
            if now >= next_page_refresh_at:
                _refresh_page_and_reconcile(page, live_watch)
                next_page_refresh_at = (
                    time.monotonic() + config.PAGE_REFRESH_INTERVAL_SECONDS
                )
                next_refresh_at = time.monotonic() + random.randint(
                    *config.LIVE_REFRESH_INTERVAL_SECONDS
                )
            elif now >= next_refresh_at:
                page_was_reloaded = _refresh_live_table_and_reconcile(
                    page, live_watch
                )
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
    run_forever()
