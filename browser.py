import config
from logger import logger


def launch_browser(p):
    # Запускает Chromium с настройками проекта.
    browser = p.chromium.launch(
        headless=config.HEADLESS,
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
    logger.info("Bot started successfully!")

    return browser


def create_page(browser):
    # Создаёт контекст браузера и страницу с таймаутами проекта.
    context = browser.new_context()
    context.add_cookies(config.SITE_COOKIES)
    page = context.new_page()
    page.set_default_navigation_timeout(30_000)
    page.set_default_timeout(30_000)
    logger.info("Cookies set")

    return context, page


def open_site(page):
    # Открывает сайт.
    logger.info("Loading site..")
    page.goto(config.SITE_URL, wait_until="domcontentloaded")
    logger.info("OK")


def select_live_tab(page):
    # Выбирает Live и ждёт загрузки таблицы матчей.
    live_tab = page.locator("#li_FilterLive")
    live_tab.wait_for(state="visible")
    live_tab.click()
    page.wait_for_selector("#table_live tr.tds", state="attached", timeout=10_000)
    page.wait_for_timeout(1_000)


def refresh_live_table(page):
    # Обновляет таблицу матчей нажатием на вкладку Live без перезагрузки страницы.
    live_tab = page.locator("#li_FilterLive")
    live_tab.wait_for(state="visible")
    logger.info("Refreshing live table..")
    live_tab.click()
    page.locator("table#table_live").wait_for(timeout=10000)
    page.wait_for_timeout(1000)
    from scraper import wait_for_valid_match_odds

    if not wait_for_valid_match_odds(page):
        return False
    logger.info("Refreshed successfully")
    return True


def refresh_page(page):
    # Полностью перезагружает страницу и ждёт готовности данных Live.
    logger.info("Refreshing page...")
    try:
        page.reload(wait_until="domcontentloaded", timeout=30_000)
        page.locator("table#table_live").wait_for(timeout=20_000)

        from scraper import wait_for_valid_match_odds

        if not wait_for_valid_match_odds(page):
            return False
        page.wait_for_timeout(1_000)
        logger.info("Page refreshed")
        return True
    except Exception as error:
        logger.error("Failed to refresh page: %s", error, exc_info=True)
        raise


def start_browser():
    # Запускает Playwright и возвращает подготовленные ресурсы браузера.
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = None
    try:
        browser = launch_browser(playwright)
        context, page = create_page(browser)
        open_site(page)
        select_live_tab(page)
    except BaseException:
        if browser is not None:
            try:
                browser.close()
            except BaseException:
                logger.error("Failed to close browser after startup error", exc_info=True)
        try:
            playwright.stop()
        except BaseException:
            logger.error("Failed to stop Playwright after startup error", exc_info=True)
        raise

    return playwright, browser, context, page