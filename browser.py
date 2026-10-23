import config
from logger import logger
from timing import seconds_to_milliseconds, wait_for_seconds


# Запускает Chromium с настройками проекта.
def launch_browser(p):
    if not config.BROWSER_PROXY_SERVER:
        raise RuntimeError("BROWSER_PROXY_SERVER is not configured")

    browser = p.chromium.launch(
        headless=config.HEADLESS,
        proxy={"server": config.BROWSER_PROXY_SERVER},
        args=list(config.BROWSER_ARGS),
    )
    logger.info("Bot started successfully!")

    return browser


# Создаёт контекст и страницу с таймаутами проекта.
def create_page(browser):
    context = browser.new_context()
    context.add_cookies(config.SITE_COOKIES)
    page = context.new_page()
    page.set_default_navigation_timeout(
        seconds_to_milliseconds(config.PAGE_NAVIGATION_TIMEOUT_SECONDS)
    )
    page.set_default_timeout(
        seconds_to_milliseconds(config.BROWSER_DEFAULT_TIMEOUT_SECONDS)
    )
    logger.info("Cookies set")

    return context, page


# Открывает стартовую страницу сайта.
def open_site(page):
    logger.info("Loading site..")
    page.goto(config.SITE_URL, wait_until="domcontentloaded")
    logger.info("OK")


# Переключает сайт на вкладку Live и ждёт таблицу.
def select_live_tab(page):
    live_tab = page.locator("#li_FilterLive")
    live_tab.wait_for(state="visible")
    live_tab.click()
    page.wait_for_selector(
        "#table_live tr.tds",
        state="attached",
        timeout=seconds_to_milliseconds(config.TABLE_TIMEOUT_SECONDS),
    )
    wait_for_seconds(page, config.POST_REFRESH_WAIT_SECONDS)


# Обновляет live-таблицу без полной перезагрузки страницы.
def refresh_live_table(page):
    live_tab = page.locator("#li_FilterLive")
    live_tab.wait_for(state="visible")
    logger.info("Refreshing live table..")
    live_tab.click()
    page.locator("table#table_live").wait_for(
        timeout=seconds_to_milliseconds(config.TABLE_TIMEOUT_SECONDS)
    )
    wait_for_seconds(page, config.POST_REFRESH_WAIT_SECONDS)
    from scraper import wait_for_valid_match_odds

    if not wait_for_valid_match_odds(page):
        return False
    logger.info("Refreshed successfully")
    return True


# Перезагружает страницу и проверяет готовность live-данных.
def refresh_page(page):
    logger.info("Refreshing page...")
    try:
        page.reload(
            wait_until="domcontentloaded",
            timeout=seconds_to_milliseconds(
                config.PAGE_NAVIGATION_TIMEOUT_SECONDS
            ),
        )
        page.locator("table#table_live").wait_for(
            timeout=seconds_to_milliseconds(config.PAGE_TABLE_TIMEOUT_SECONDS)
        )

        from scraper import wait_for_valid_match_odds

        if not wait_for_valid_match_odds(page):
            return False
        wait_for_seconds(page, config.POST_REFRESH_WAIT_SECONDS)
        logger.info("Page refreshed")
        return True
    except Exception as error:
        logger.error("Failed to refresh page: %s", error, exc_info=True)
        raise


# Запускает Playwright, браузер и начальную страницу.
def start_browser():
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