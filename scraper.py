import json
import time
from pathlib import Path

import config
import scripts
from logger import logger
from live_watch import _LiveWatch
from models import Match
from timing import seconds_to_milliseconds, wait_for_seconds


# Ждём появления строк матчей.
def wait_for_match_data(page):
    page.wait_for_selector(
        "#table_live tr.tds",
        state="attached",
        timeout=seconds_to_milliseconds(config.MATCH_DATA_TIMEOUT_SECONDS),
    )


# Ждём появления валидных строк с коэффициентами Bet365.
def wait_for_match_odds(page, log_success=True):
    page.wait_for_function(
        scripts._MATCH_ODDS_READY_JS,
        timeout=seconds_to_milliseconds(config.MATCH_ODDS_TIMEOUT_SECONDS),
    )
    if log_success:
        logger.info("Bet365 odds found")


def wait_for_valid_match_odds(
    page, timeout_seconds=config.VALID_MATCH_ODDS_TIMEOUT_SECONDS
):
    deadline = time.monotonic() + timeout_seconds
    while True:
        if page.evaluate(scripts._MATCH_ODDS_READY_JS):
            return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        wait_for_seconds(
            page, min(config.ODDS_POLL_INTERVAL_SECONDS, remaining)
        )


# Получаем названия лиг по их ID.
def _league_names(page):
    return page.evaluate(scripts._LEAGUE_NAMES_JS)


# Загружаем данные всех подходящих матчей из DOM.
def _load_all_matches_data(page) -> list[Match]:
    raw_matches = page.evaluate(scripts._MATCH_DATA_JS)
    return [
        Match(
            match_id=match_data["match_id"],
            league_id=match_data["league_id"],
            league="",
            home_team=match_data["home_team"],
            away_team=match_data["away_team"],
            match_time=match_data["match_time"],
            score=match_data["score"],
            redcards=match_data["redcards"],
            over_odd=match_data["over_odd"],
            under_odd=match_data["under_odd"],
            total=match_data["total"],
            ah_home_odd=match_data["ah_home_odd"],
            ah_away_odd=match_data["ah_away_odd"],
            ah_handicap=match_data["ah_handicap"],
        )
        for match_data in raw_matches
    ]


# Собираем текущий snapshot уникальных матчей.
def _collect_current_matches(page):
    league_names = _league_names(page)
    match_data_list = _load_all_matches_data(page)
    matches = []
    seen_match_ids = set()

    for match_data in match_data_list:
        match_id = match_data.match_id
        if match_id and match_id in seen_match_ids:
            continue

        if match_id:
            seen_match_ids.add(match_id)
        match_data.league = league_names.get(match_data.league_id, "")

        if not match_data.teams:
            logger.warning("Match %s has no team data; skipping", match_id)
            continue

        matches.append(match_data)

    return matches


# Сохраняем команды из того же списка, который выводится в Matches found.
def _write_matches_total(matches, output_path: Path | None = None):
    if output_path is None:
        output_path = Path(__file__).with_name("matches_total.json")
    output_path.write_text(
        json.dumps(
            [match.to_dict() for match in matches],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# Ждём и собираем матчи при первоначальном запуске.
def scrape_matches(page, log_odds_found=True):
    wait_for_match_data(page)
    wait_for_match_odds(page, log_success=log_odds_found)
    matches = _collect_current_matches(page)
    _write_matches_total(matches)
    match_ids = ", ".join(match.match_id for match in matches)
    logger.info(
        "Active matches: %d%s",
        len(matches),
        f" ({match_ids})" if match_ids else "",
    )
    return matches


    # Логируем количество и ID обновлённых матчей.
def _log_matches_updated(matches):
    match_ids = ", ".join(match.match_id for match in matches)
    logger.info(
        "Matches updated: %d%s",
        len(matches),
        f" ({match_ids})" if match_ids else "",
    )


# Запускаем наблюдение за изменениями DOM матчей.
def start_live_watch(
    page,
    on_matches_update,
    initial_matches=None,
    on_matches_deleted=None,
):
    if not callable(on_matches_update):
        raise TypeError("on_matches_update must be a callable object.")
    if on_matches_deleted is not None and not callable(on_matches_deleted):
        raise TypeError("on_matches_deleted must be a callable object.")
    if initial_matches is None:
        initial_matches = _collect_current_matches(page)

    callback_name = f"__scraper_dom_changed_{id(page)}"
    observer_key = f"__scraper_live_observer_{id(page)}"
    live_watch = _LiveWatch(
        page,
        observer_key,
        on_matches_update,
        initial_matches,
        _collect_current_matches,
        on_matches_deleted,
    )

    # Отмечаем изменение DOM для обработки в основном цикле.
    def on_dom_change():
        live_watch._mark_dom_change()

    page.expose_function(callback_name, on_dom_change)
    _install_live_watch_observer(page, callback_name, observer_key)

    return live_watch


def reattach_live_watch(page):
    callback_name = f"__scraper_dom_changed_{id(page)}"
    observer_key = f"__scraper_live_observer_{id(page)}"
    _install_live_watch_observer(page, callback_name, observer_key)


def _install_live_watch_observer(page, callback_name, observer_key):
    page.evaluate(
        scripts._LIVE_WATCH_OBSERVER_JS,
        [callback_name, observer_key],
    )
