import config
from logger import logger


def launch_browser(p):
    """Запускает Chromium с настройками проекта."""

    try:
        browser = p.chromium.launch(
            headless=config.HEADLESS,
            args=[
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
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
        logger.info("Browser started successfully.")
    except Exception:
        logger.error("Failed to start browser.", exc_info=True)
        raise

    return browser


def create_page(browser):
    """Создаёт контекст браузера и страницу с таймаутами проекта."""
    try:
        context = browser.new_context()
        context.add_cookies(config.SITE_COOKIES)
        page = context.new_page()
        page.set_default_navigation_timeout(30_000)
        page.set_default_timeout(30_000)
        logger.info("Cookies set.")
    except Exception:
        logger.error("Failed to create browser context or page.", exc_info=True)
        raise

    return context, page


def open_site(page):
    """Открывает сайт."""
    try:
        logger.info("Loading site...")
        page.goto(config.SITE_URL, wait_until="domcontentloaded")
        logger.info("Site opened.")
    except Exception:
        logger.error("Failed to open site.", exc_info=True)
        raise


def select_live_tab(page):
    """Выбирает вкладку Live."""
    try:
        live_tab = page.locator("#tabLive")
        live_tab.wait_for(state="visible")
        live_tab.click()
        page.wait_for_timeout(500)
        logger.info("Live tab selected successfully.")
    except Exception:
        logger.error("Failed to select Live tab.", exc_info=True)
        raise


def start_browser():
    """Запускает Playwright и возвращает подготовленные ресурсы браузера."""
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = None
    try:
        browser = launch_browser(playwright)
        context, page = create_page(browser)
        open_site(page)
        select_live_tab(page)
    except Exception:
        if browser is not None:
            browser.close()
        playwright.stop()
        raise

    return playwright, browser, context, page