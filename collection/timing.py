# Преобразует секунды в миллисекунды для Playwright.
def seconds_to_milliseconds(seconds: float) -> int:
    return int(seconds * 1000)


# Ожидает заданное время средствами страницы Playwright.
def wait_for_seconds(page, seconds: float) -> None:
    page.wait_for_timeout(seconds_to_milliseconds(seconds))
