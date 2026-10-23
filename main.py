import os
import random
import signal
import sys
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
    # Обозначает необходимость перезапустить главный цикл бота.
    pass


class ScheduledRestartRequested(Exception):
    # Обозначает необходимость планового перезапуска процесса.
    pass


# Ожидает появления матчей перед повторной загрузкой.
def _wait_for_matches(page, restart_deadline=None):
    logger.warning(
        "No matches found. Waiting %d seconds before reloading the page.",
        config.NO_MATCHES_RETRY_SECONDS,
    )
    if restart_deadline is None:
        wait_for_seconds(page, config.NO_MATCHES_RETRY_SECONDS)
        return

    remaining_seconds = restart_deadline - time.monotonic()
    if remaining_seconds <= 0:
        raise ScheduledRestartRequested
    wait_for_seconds(
        page,
        min(config.NO_MATCHES_RETRY_SECONDS, remaining_seconds),
    )
    if time.monotonic() >= restart_deadline:
        raise ScheduledRestartRequested


# Повторяет обновление live-таблицы при ошибках.
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


# Перезагружает страницу до появления актуальных коэффициентов.
def _refresh_page_until_odds(page, restart_deadline=None):
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
        _wait_for_matches(page, restart_deadline)


# Помечает запрос на штатное завершение бота.
def _request_shutdown(shutdown_requested, _signum, _frame):
    shutdown_requested.set()


# Записывает обновления матчей и логирует их.
def _record_match_updates(analyzer, matches):
    analyzer.record_updates(matches)
    _log_matches_updated(matches)


# Собирает актуальный snapshot матчей и сверяет его с наблюдателем.
def _reconcile_matches(page, live_watch):
    refreshed_matches = scrape_matches(page, log_odds_found=False)
    live_watch.reconcile_after_refresh(refreshed_matches)


# Обновляет страницу и сверяет список матчей.
def _refresh_page_and_reconcile(page, live_watch, restart_deadline=None):
    _refresh_page_until_odds(page, restart_deadline)
    _reconcile_matches(page, live_watch)


# Обновляет таблицу либо страницу и сверяет матчи.
def _refresh_live_table_and_reconcile(
    page, live_watch, restart_deadline=None
):
    live_refresh_result = _refresh_live_table_with_retries(page)
    page_was_reloaded = live_refresh_result is not True
    if page_was_reloaded:
        if live_refresh_result is False:
            _wait_for_matches(page, restart_deadline)
        else:
            logger.warning(
                "Live table refresh failed after all retries. "
                "Falling back to a page refresh."
            )
        _refresh_page_until_odds(page, restart_deadline)

    _reconcile_matches(page, live_watch)
    return page_was_reloaded


# Перезапускает основной цикл после запроса на восстановление.
def run_forever():
    restart_deadline = time.monotonic() + config.RESTART_HOURS * 3600
    while True:
        try:
            main(restart_deadline)
            return
        except ScheduledRestartRequested:
            logger.info(
                "Restart interval reached (%s hours). Restarting script...",
                config.RESTART_HOURS,
            )
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except ScriptRestartRequested as error:
            logger.error("%s. Restarting bot from a clean state.", error)


# Инициализирует сервисы и выполняет основной цикл бота.
def main(restart_deadline=None):
    if restart_deadline is None:
        restart_deadline = time.monotonic() + config.RESTART_HOURS * 3600

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
            now = time.monotonic()
            if now >= restart_deadline:
                raise ScheduledRestartRequested
            wait_for_seconds(
                page,
                min(config.MAIN_LOOP_WAIT_SECONDS, restart_deadline - now),
            )
            if time.monotonic() >= restart_deadline:
                raise ScheduledRestartRequested
            live_watch.process_pending()
            now = time.monotonic()
            if now >= restart_deadline:
                raise ScheduledRestartRequested
            if now >= next_page_refresh_at:
                _refresh_page_and_reconcile(
                    page, live_watch, restart_deadline
                )
                next_page_refresh_at = (
                    time.monotonic() + config.PAGE_REFRESH_INTERVAL_SECONDS
                )
                next_refresh_at = time.monotonic() + random.randint(
                    *config.LIVE_REFRESH_INTERVAL_SECONDS
                )
            elif now >= next_refresh_at:
                page_was_reloaded = _refresh_live_table_and_reconcile(
                    page, live_watch, restart_deadline
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
