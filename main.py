import random
import time

from analyzer import MatchAnalyzer
import config
from browser import refresh_live_table, start_browser
from logger import logger
from scraper import _log_matches_updated, scrape_matches, start_live_watch


def main():
    playwright, browser, _, page = start_browser()
    live_watch = None
    try:
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
        while True:
            page.wait_for_timeout(1_000)
            live_watch.process_pending()
            if time.monotonic() >= next_refresh_at:
                refresh_live_table(page)
                refreshed_matches = scrape_matches(page)
                live_watch.reconcile_after_refresh(refreshed_matches)
                next_refresh_at = time.monotonic() + random.randint(
                    *config.LIVE_REFRESH_INTERVAL_SECONDS
                )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    finally:
        if live_watch is not None:
            live_watch.stop()
        browser.close()
        logger.info("Browser closed.")
        playwright.stop()
        logger.info("Playwright stopped.")


if __name__ == "__main__":
    main()
