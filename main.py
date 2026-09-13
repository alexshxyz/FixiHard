from browser import start_browser
from logger import logger
from scraper import scrape_matches


def main():
    playwright, browser, _, page = start_browser()
    try:
        scrape_matches(page)
    finally:
        browser.close()
        logger.info("Браузер закрыт.")
        playwright.stop()
        logger.info("Playwright остановлен.")


if __name__ == "__main__":
    main()
