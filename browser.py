import config
from logger import logger


def launch_browser(p):
    """Запускает Chromium с настройками проекта."""
    logger.info("Запуск браузера...")

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
        logger.info("Браузер успешно запущен.")
    except Exception:
        logger.error("Не удалось запустить браузер.", exc_info=True)
        raise

    return browser


def create_page(browser):
    """Создаёт контекст браузера и страницу с таймаутами проекта."""
    try:
        context = browser.new_context()
        page = context.new_page()
        page.set_default_navigation_timeout(30_000)
        page.set_default_timeout(30_000)
        logger.info("Контекст браузера и страница успешно созданы.")
    except Exception:
        logger.error("Не удалось создать контекст браузера или страницу.", exc_info=True)
        raise

    return context, page


def open_site(page, max_navigation_retries=3):
    """Открывает сайт."""
    for attempt in range(1, max_navigation_retries + 1):
        try:
            logger.info("Переход на сайт, попытка %d из %d...", attempt, max_navigation_retries)
            page.goto(config.SITE_URL, wait_until="domcontentloaded")
            logger.info("Сайт открыт.")
            break
        except Exception:
            logger.warning("Не удалось открыть сайт (попытка %d).", attempt, exc_info=True)
            if attempt == max_navigation_retries:
                logger.error("Превышено количество попыток открытия сайта.")
                raise


def select_live_tab(page):
    """Выбирает вкладку Live и дожидается обновления таблицы."""
    try:
        live_tab = page.locator("#tabLive")
        live_tab.wait_for(state="visible")
        live_tab.click()
        logger.info("Вкладка Live успешно выбрана.")

        page.wait_for_selector("#gameList .matchDiv", state="visible", timeout=30_000)

        page.wait_for_function(
            """
            () => {
                const firstMatch = document.querySelector('#gameList .matchDiv');
                if (!firstMatch) return false;
                const state = firstMatch.querySelector('text[id^="state_"]');
                if (!state) return false;
                const text = (state.textContent || '').replace(/\\s+/g, '').trim();
                return text !== '' && text !== '-' && text !== '0';
            }
            """,
            timeout=30_000,
        )

        page.wait_for_function(
            """
            () => {
                const matches = Array.from(document.querySelectorAll('#gameList .matchDiv'));
                return matches.some((match) => {
                    const o4 = match.querySelector('span[id^="o4_"]');
                    const o5 = match.querySelector('span[id^="o5_"]');
                    const o6 = match.querySelector('span[id^="o6_"]');
                    if (!o4 || !o5 || !o6) return false;

                    const values = [o4, o5, o6].map((node) => (node.textContent || '').replace(/\\s+/g, '').trim());
                    return values.every((text) => text !== '' && text !== '-');
                });
            }
            """,
            timeout=30_000,
        )

        page.wait_for_timeout(500)
        logger.info("Данные матчей загружены.")
    except Exception:
        logger.error("Не удалось выбрать вкладку Live или дождаться обновления таблицы.", exc_info=True)
        raise
# здесь позже будет логика с перезагузкой страницы, если данные не загрузились (ни одной строки с коэффициентами это ожидаемое поведение и мы должны обновлять страницу)

def start_browser(max_navigation_retries=3):
    """Запускает Playwright и возвращает подготовленные ресурсы браузера."""
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = None
    try:
        browser = launch_browser(playwright)
        context, page = create_page(browser)
        open_site(page, max_navigation_retries)
        select_live_tab(page)
    except Exception:
        if browser is not None:
            browser.close()
        playwright.stop()
        raise

    return playwright, browser, context, page