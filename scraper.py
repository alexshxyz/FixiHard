from logger import logger
from models import Match


def _clean_text(value):
    """Очищает текст до нормального отображения."""
    if value is None:
        return ""
    return str(value).strip()


def _text(locator):
    """Возвращает очищенный текст первого найденного элемента."""
    if locator.count() == 0:
        return ""
    return _clean_text(locator.nth(0).text_content() or "")


def _read_match_value(match, selectors):
    """Возвращает первое непустое значение среди указанных селекторов."""
    for selector in selectors:
        value = _text(match.locator(selector))
        if value and value != "-":
            return value
    return ""


def _league_names(page):
    """Возвращает отображаемые названия лиг по их идентификаторам."""
    leagues = {}
    headers = page.locator("#gameList .group-title[data-leaid]")

    for index in range(headers.count()):
        header = headers.nth(index)
        league_id = header.get_attribute("data-leaid")
        if not league_id:
            continue

        league_name = _text(header.locator(".leaRow"))
        if league_name:
            leagues[league_id] = league_name

    return leagues


def _load_match_element_data(match) -> Match | None:
    """Извлекает все нужные данные для одного матча и возвращает Match-объект."""
    match_id = match.get_attribute("data-mid") or ""
    if not match_id:
        item = match.locator(".item[data-mid]").first
        match_id = item.get_attribute("data-mid") or ""

    league_id = match.get_attribute("data-mlid") or ""

    total = _read_match_value(match, ['span[id^="o5_"]'])
    if not total:
        return None

    home_team = _read_match_value(match, ['span[id^="ht_"]', '.homeTeam .name'])
    away_team = _read_match_value(match, ['span[id^="gt_"]', '.guestTeam .name'])
    home_score = _read_match_value(match, ['span[id^="hsc_"]', '.homeS'])
    away_score = _read_match_value(match, ['span[id^="gsc_"]', '.guestS'])
    over_odd = _read_match_value(match, ['span[id^="o4_"]'])
    under_odd = _read_match_value(match, ['span[id^="o6_"]'])

    return Match(
        match_id=match_id,
        league_id=league_id,
        league="",
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        over_odd=over_odd,
        under_odd=under_odd,
        total=total,
    )


def scrape_matches(page):
    """Собирает уникальные матчи с заполненным тоталом и выводит их в лог."""
    try:
        page.wait_for_selector("#gameList .matchDiv", state="visible", timeout=30_000)

        league_names = _league_names(page)
        match_elements = page.locator("#gameList .matchDiv")
        matches = []
        seen_match_ids = set()

        for index in range(match_elements.count()):
            match = match_elements.nth(index)
            match_data = _load_match_element_data(match)
            if not match_data:
                continue

            match_id = match_data.match_id
            if not match_id or match_id in seen_match_ids:
                continue

            seen_match_ids.add(match_id)
            match_data.league = league_names.get(match_data.league_id, "")

            if not match_data.teams:
                logger.warning("Матч %s не содержит данные о командах, пропускаем.", match_id)
                continue

            matches.append(match_data)
            logger.info(
                "Матч: match_id=%s | league=%s | teams=%s | score=%s | over_odd=%s | under_odd=%s | total=%s",
                match_data.match_id,
                match_data.league,
                match_data.teams,
                match_data.score,
                match_data.over_odd,
                match_data.under_odd,
                match_data.total,
            )

        logger.info("Собрано матчей: %d.", len(matches))
        return matches
    except Exception:
        logger.error("Не удалось собрать данные матчей.", exc_info=True)
        raise
