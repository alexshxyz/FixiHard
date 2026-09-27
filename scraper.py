from logger import logger
from models import Match


# Очищаем значение до строки без пробелов по краям.
def _clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


# Читаем текст первого найденного элемента.
def _text(locator):
    if locator.count() == 0:
        return ""
    return _clean_text(locator.nth(0).text_content() or "")


# Ждём live-матчи с заполненным временем.
def wait_for_match_data(page):
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


# Ждём заполненные коэффициенты матчей.
def wait_for_match_odds(page):
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


# Получаем названия лиг по их ID.
def _league_names(page):
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


# Загружаем данные всех подходящих матчей из DOM.
def _load_all_matches_data(page) -> list[Match]:
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


# Собираем текущий snapshot уникальных матчей.
def _collect_current_matches(page):
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
                logger.warning("Match %s has no team data; skipping.", match_id)
                continue

            matches.append(match_data)

        return matches
    except Exception:
        logger.error("Failed to collect current match snapshot.", exc_info=True)
        raise


    # Ждём и собираем матчи при первоначальном запуске.
def scrape_matches(page):
    try:
        wait_for_match_data(page)
        wait_for_match_odds(page)
        matches = _collect_current_matches(page)
        match_ids = ", ".join(match.match_id for match in matches)
        logger.info(
            "Matches found: %d%s",
            len(matches),
            f" ({match_ids})" if match_ids else "",
        )
        return matches
    except Exception:
        logger.error("Failed to scrape match data.", exc_info=True)
        raise


    # Логируем количество и ID обновлённых матчей.
def _log_matches_updated(matches):
    match_ids = ", ".join(match.match_id for match in matches)
    logger.info(
        "Matches updated: %d%s",
        len(matches),
        f" ({match_ids})" if match_ids else "",
    )


class _LiveWatch:
    # Управляет подпиской на изменения списка live-матчей.

    # Инициализируем наблюдатель и сохраняем начальный snapshot.
    def __init__(self, page, observer_key, on_matches_update, initial_matches):
        self._page = page
        self._observer_key = observer_key
        self._on_matches_update = on_matches_update
        self._matches_by_id = {match.match_id: match for match in initial_matches}
        self._snapshot_by_id = dict(self._matches_by_id)
        self._pending_update = False
        self._stopped = False

    # Помечаем наличие изменений DOM для основного цикла.
    def _mark_dom_change(self):
        self._pending_update = True

    # Собираем snapshot и передаём только изменённые матчи.
    def process_pending(self):
        try:
            if not self._pending_update:
                return

            self._pending_update = False
            logger.info("Live match DOM change detected.")
            current_matches = _collect_current_matches(self._page)
            updated_matches = []
            for match in current_matches:
                if self._matches_by_id.get(match.match_id) != match:
                    updated_matches.append(match)
                    self._matches_by_id[match.match_id] = match

            if updated_matches:
                self._on_matches_update(updated_matches)
        except Exception:
            logger.error("Failed to process live match update.", exc_info=True)
            raise

    # Сверяем полный снимок после обновления и забываем исчезнувшие матчи.
    def reconcile_after_refresh(self, current_matches):
        try:
            current_by_id = {match.match_id: match for match in current_matches}
            added_ids = [
                match_id
                for match_id in current_by_id
                if match_id not in self._snapshot_by_id
            ]
            deleted_ids = [
                match_id
                for match_id in self._snapshot_by_id
                if match_id not in current_by_id
            ]
            changed_matches = [
                match
                for match in current_matches
                if self._matches_by_id.get(match.match_id) != match
            ]

            self._matches_by_id = current_by_id
            self._snapshot_by_id = dict(current_by_id)

            if changed_matches:
                self._on_matches_update(changed_matches)

            logger.info(
                "Matches updated: added %d (%s) deleted %d (%s)",
                len(added_ids),
                ", ".join(added_ids),
                len(deleted_ids),
                ", ".join(deleted_ids),
            )
        except Exception:
            logger.error("Failed to reconcile matches after refresh.", exc_info=True)
            raise

    # Останавливаем наблюдатель за изменениями DOM.
    def stop(self):
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
            logger.info("Live match monitoring stopped.")
        except Exception:
            logger.error("Failed to stop live match monitoring.", exc_info=True)
            raise


# Запускаем наблюдение за изменениями DOM матчей.
def start_live_watch(page, on_matches_update, initial_matches=None):
    try:
        if not callable(on_matches_update):
            raise TypeError("on_matches_update must be a callable object.")
        if initial_matches is None:
            initial_matches = _collect_current_matches(page)

        callback_name = f"__scraper_dom_changed_{id(page)}"
        observer_key = f"__scraper_live_observer_{id(page)}"
        live_watch = _LiveWatch(page, observer_key, on_matches_update, initial_matches)

        # Отмечаем изменение DOM для обработки в основном цикле.
        def on_dom_change():
            live_watch._mark_dom_change()

        page.expose_function(callback_name, on_dom_change)
        page.evaluate(
            """
            ([callbackName, observerKey]) => {
                const gameList = document.querySelector('#gameList');
                if (!gameList) {
                    throw new Error('#gameList not found.');
                }
                const observationRoot = gameList.parentElement || gameList;

                const observer = new MutationObserver(() => {
                    window[callbackName]();
                });
                observer.observe(observationRoot, {
                    childList: true,
                    subtree: true,
                    characterData: true,
                });
                window[observerKey] = observer;
            }
            """,
            [callback_name, observer_key],
        )

        logger.info("Live match monitoring started.")
        return live_watch
    except Exception:
        logger.error("Failed to start live match monitoring.", exc_info=True)
        raise
