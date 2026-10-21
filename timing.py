def seconds_to_milliseconds(seconds: float) -> int:
    return int(seconds * 1000)


def wait_for_seconds(page, seconds: float) -> None:
    page.wait_for_timeout(seconds_to_milliseconds(seconds))
