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


def wait_for_match_data(page): # Возможно стоит убрать функцию
    """Ожидает появления хотя бы одного матча с непустым временем."""
    try:
        page.wait_for_selector("#gameList .matchDiv", state="visible", timeout=30_000)
        page.wait_for_function(
            r"""
            () => Array.from(document.querySelectorAll('#gameList .matchDiv')).some((match) => {
                const state = match.querySelector('text[id^="state_"]');
                if (!state) return false;
                const text = (state.textContent || '').replace(/\s+/g, '').trim();
                return text !== '' && text !== '-' && text !== '0';
            })
            """,
            timeout=30_000,
        )
    except Exception:
        logger.error("Live matches not found or failed to load.", exc_info=True)
        raise


def wait_for_match_odds(page):
    """Ожидает появления заполненных коэффициентов."""
    try:
        page.wait_for_function(
            r"""
            () => Array.from(document.querySelectorAll('#gameList .matchDiv')).some((match) => {
                const odds = ['o4_', 'o5_', 'o6_'].map((prefix) => match.querySelector(`span[id^="${prefix}"]`));
                if (odds.some((node) => !node)) return false;

                const oddsText = odds.map((node) => (node.textContent || '').replace(/\s+/g, '').trim());
                return oddsText.every((text) => text !== '' && text !== '-');
            })
            """,
            timeout=30_000,
        )
        logger.info("Odds found.")
    except Exception:
        logger.error("Odds not found or failed to load.", exc_info=True)
        raise


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


_MATCH_DATA_JS = r"""
() => {
    // Эта логика дублирует прежнюю Python-версию отбора значений; при правках
    // верстки или условий фильтрации нужно синхронизировать оба места.
    const cleanText = (value) => (value == null ? '' : String(value).trim());

    const readValue = (match, selectors) => {
        for (const selector of selectors) {
            const element = match.querySelector(selector);
            const value = cleanText(element ? element.textContent : '');
            if (value && value !== '-') {
                return value;
            }
        }
        return '';
    };

    return Array.from(document.querySelectorAll('#gameList .matchDiv'))
        .map((match) => {
            let matchId = match.getAttribute('data-mid') || '';
            if (!matchId) {
                const nestedMatch = match.querySelector('.item[data-mid]');
                matchId = nestedMatch ? nestedMatch.getAttribute('data-mid') || '' : '';
            }

            const leagueId = match.getAttribute('data-mlid') || '';
            const matchTime = readValue(match, ['text[id^="state_"]']);
            if (!matchId || !matchTime) {
                return null;
            }

            const overOdd = readValue(match, ['span[id^="o4_"]']);
            const total = readValue(match, ['span[id^="o5_"]']);
            const underOdd = readValue(match, ['span[id^="o6_"]']);
            if (!overOdd || !total || !underOdd) {
                return null;
            }

            return {
                match_id: matchId,
                league_id: leagueId,
                match_time: matchTime,
                over_odd: overOdd,
                total: total,
                under_odd: underOdd,
                home_team: readValue(match, ['span[id^="ht_"]', '.homeTeam .name']),
                away_team: readValue(match, ['span[id^="gt_"]', '.guestTeam .name']),
                home_score: readValue(match, ['span[id^="hsc_"]', '.homeS']),
                away_score: readValue(match, ['span[id^="gsc_"]', '.guestS']),
            };
        })
        .filter((match) => match !== null);
}
"""


def _load_all_matches_data(page) -> list[Match]:
    """Собирает данные всех подходящих матчей одним чтением DOM."""
    try:
        raw_matches = page.evaluate(_MATCH_DATA_JS)
        return [
            Match(
                match_id=match_data["match_id"],
                league_id=match_data["league_id"],
                league="",
                home_team=match_data["home_team"],
                away_team=match_data["away_team"],
                match_time=match_data["match_time"],
                home_score=match_data["home_score"],
                away_score=match_data["away_score"],
                over_odd=match_data["over_odd"],
                under_odd=match_data["under_odd"],
                total=match_data["total"],
            )
            for match_data in raw_matches
        ]
    except Exception:
        logger.error("Cannot load all matches data from DOM.", exc_info=True)
        raise


def _collect_current_matches(page):
    """Собирает текущий snapshot матчей без ожидания загрузки данных."""
    try:
        league_names = _league_names(page)
        match_data_list = _load_all_matches_data(page)
        matches = []
        seen_match_ids = set()

        for match_data in match_data_list:
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
                "Матч: match_id=%s | league=%s | teams=%s | match_time=%s | score=%s | over_odd=%s | under_odd=%s | total=%s",
                match_data.match_id,
                match_data.league,
                match_data.teams,
                match_data.match_time,
                match_data.score,
                match_data.over_odd,
                match_data.under_odd,
                match_data.total,
            )

        logger.info("Собрано матчей: %d.", len(matches))
        return matches
    except Exception:
        logger.error("Не удалось собрать текущий snapshot матчей.", exc_info=True)
        raise


def scrape_matches(page):
    """Собирает уникальные матчи с заполненным тоталом и выводит их в лог."""
    try:
        wait_for_match_data(page)
        wait_for_match_odds(page)
        return _collect_current_matches(page)
    except Exception:
        logger.error("Не удалось собрать данные матчей.", exc_info=True)
        raise


class _LiveWatch:
    """Управляет подпиской на изменения списка live-матчей."""

    def __init__(self, page, observer_key, on_matches_update):
        self._page = page
        self._observer_key = observer_key
        self._on_matches_update = on_matches_update
        self._pending_update = False
        self._stopped = False

    def _mark_dom_change(self):
        """Запоминает изменение DOM для обработки в основном цикле Playwright."""
        self._pending_update = True

    def process_pending(self):
        """Обрабатывает накопленные изменения DOM текущими данными матчей."""
        try:
            if not self._pending_update:
                return

            self._pending_update = False
            matches = _collect_current_matches(self._page)
            self._on_matches_update(matches)
        except Exception:
            logger.error("Не удалось обработать изменение live-матчей.", exc_info=True)
            raise

    def stop(self):
        """Останавливает наблюдение за изменениями DOM."""
        try:
            if self._stopped:
                return

            self._page.evaluate(
                """
                (observerKey) => {
                    const observer = window[observerKey];
                    if (observer) {
                        observer.disconnect();
                        delete window[observerKey];
                    }
                }
                """,
                self._observer_key,
            )
            self._stopped = True
            logger.info("Наблюдение за live-матчами остановлено.")
        except Exception:
            logger.error("Не удалось остановить наблюдение за live-матчами.", exc_info=True)
            raise


def start_live_watch(page, on_matches_update):
    """Запускает постоянное наблюдение за изменениями live-матчей."""
    try:
        if not callable(on_matches_update):
            raise TypeError("on_matches_update должен быть вызываемым объектом.")

        callback_name = f"__scraper_dom_changed_{id(page)}"
        observer_key = f"__scraper_live_observer_{id(page)}"
        live_watch = _LiveWatch(page, observer_key, on_matches_update)

        def on_dom_change():
            live_watch._mark_dom_change()
            logger.info("Изменение DOM live-матчей обнаружено.")

        page.expose_function(callback_name, on_dom_change)
        page.evaluate(
            """
            ([callbackName, observerKey]) => {
                const gameList = document.querySelector('#gameList');
                if (!gameList) {
                    throw new Error('#gameList не найден.');
                }

                const observer = new MutationObserver(() => {
                    window[callbackName]();
                });
                observer.observe(gameList, {
                    childList: true,
                    subtree: true,
                    characterData: true,
                });
                window[observerKey] = observer;
            }
            """,
            [callback_name, observer_key],
        )

        logger.info("Наблюдение за live-матчами запущено.")
        return live_watch
    except Exception:
        logger.error("Не удалось запустить наблюдение за live-матчами.", exc_info=True)
        raise
