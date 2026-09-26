from browser import start_browser
from logger import logger
from scraper import scrape_matches, start_live_watch


def main():
    playwright, browser, _, page = start_browser()
    live_watch = None
    try:
        scrape_matches(page)
        live_watch = start_live_watch(page, lambda matches: logger.info("Получено обновление матчей: %d.", len(matches)))
        while True:
            page.wait_for_timeout(1_000)
            live_watch.process_pending()
    except KeyboardInterrupt:
        logger.info("Мониторинг live-матчей остановлен пользователем.")
    finally:
        if live_watch is not None:
            live_watch.stop()
        browser.close()
        logger.info("Браузер закрыт.")
        playwright.stop()
        logger.info("Playwright остановлен.")


if __name__ == "__main__":
    main()
