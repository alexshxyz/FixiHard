import json
from pathlib import Path

from logger import logger
from live_watch import _LiveWatch
from models import Match


_GLOBAL_ODDS_READY_JS = r"""
(() => {
    const hasBet365Odds = Array.from(
        document.querySelectorAll('td.oddstd[onclick]')
    ).some((cell) => /,\s*["']8["']\s*,/.test(
        cell.getAttribute('onclick') || ''
    ));
    const hasVisibleOdds = Array.from(
        document.querySelectorAll('td.oddstd')
    ).some((cell) => {
        if (cell.offsetParent === null) return false;
        const odds1 = cell.querySelector('p.odds1');
        const odds3 = cell.querySelector('p.odds3');
        return (odds1 && odds1.offsetParent !== null) ||
            (odds3 && odds3.offsetParent !== null);
    });
    return hasBet365Odds && hasVisibleOdds;
})()
"""


# Ждём появления строк матчей.
def wait_for_match_data(page):
    try:
        page.wait_for_selector("#table_live tr.tds", state="attached", timeout=30_000)
    except Exception:
        logger.error("Live matches not found or failed to load", exc_info=True)
        raise


# Ждём появления валидных строк с коэффициентами Bet365.
def wait_for_match_odds(page, log_success=True):
    try:
        page.wait_for_function(
            r"""
            () => {
                if (!__GLOBAL_ODDS_READY__) return false;

                return Array.from(
                    document.querySelectorAll('#table_live tr.tds')
                ).some((match) => {
                    const style = window.getComputedStyle(match);
                    if (!match.getClientRects().length ||
                        style.display === 'none' ||
                        style.visibility === 'hidden') {
                        return false;
                    }

                    const matchId = match.id.match(/^tr1_(.+)$/)?.[1] ||
                        match.getAttribute('matchid') ||
                        match.querySelector('[id^="favM_"]')?.getAttribute('mid');
                    const hasOdds = Array.from(
                        match.querySelectorAll('p.odds1, p.odds3')
                    ).some((odds) => odds.offsetParent !== null);
                    return Boolean(matchId && hasOdds);
                });
            }
            """.replace("__GLOBAL_ODDS_READY__", _GLOBAL_ODDS_READY_JS),
            timeout=30_000,
        )
        if log_success:
            logger.info("Bet365 odds found")
    except Exception:
        logger.error("Odds not found or failed to load", exc_info=True)
        raise


# Получаем названия лиг по их ID.
def _league_names(page):
    return page.evaluate(
        """
        () => Object.fromEntries(
            Array.from(document.querySelectorAll('#table_live tr.Leaguestitle[sclassid]'))
                .map((header) => {
                    const leagueId = header.getAttribute('sclassid');
                    const name = header.querySelector('.l1 .LGname, .l1 .fbsclass');
                    return [leagueId, (name?.textContent || '').trim()];
                })
                .filter(([leagueId, name]) => leagueId && name)
        )
        """
    )


_MATCH_DATA_JS = r"""
() => {
    const cleanText = (value) => (value == null ? '' : String(value).replace(/\s+/g, ' ').trim());
    const readText = (root, selector) => cleanText(root.querySelector(selector)?.textContent);
    const isVisible = (element) => {
        if (!element?.getClientRects().length) return false;
        const style = window.getComputedStyle(element);
        return style.display !== 'none' && style.visibility !== 'hidden';
    };
    const teamName = (node) => {
        if (!node) return '';
        const clone = node.cloneNode(true);
        clone.querySelectorAll('.neutraity').forEach((item) => item.remove());
        return cleanText(clone.textContent);
    };
    const globalReady = __GLOBAL_ODDS_READY__;

    return Array.from(document.querySelectorAll('#table_live tr.tds'))
        .map((match) => {
            if (!isVisible(match)) return null;

            const favorite = match.querySelector('[id^="favM_"]');
            const rowMatchId = match.id.match(/^tr1_(.+)$/)?.[1];
            const matchId = rowMatchId || match.getAttribute('matchid') || favorite?.getAttribute('mid') || '';
            const leagueId = match.getAttribute('sclassid') || '';
            const status = match.querySelector('td.status');
            const matchTime =
                readText(match, 'td.status span[id^="got_"]') ||
                cleanText(status?.textContent);

            const oddsCells = Array.from(match.querySelectorAll('td.oddstd'));
            const overOdd = cleanText(oddsCells[0]?.querySelector('p.odds3')?.textContent);
            const total = cleanText(oddsCells[1]?.querySelector('p.odds3')?.textContent);
            const underOdd = cleanText(oddsCells[2]?.querySelector('p.odds3')?.textContent);
            const ahHomeOdd = cleanText(oddsCells[0]?.querySelector('p.odds1')?.textContent);
            const ahHandicap = cleanText(oddsCells[1]?.querySelector('p.odds1')?.textContent);
            const ahAwayOdd = cleanText(oddsCells[2]?.querySelector('p.odds1')?.textContent);
            const hasOdds = Array.from(
                match.querySelectorAll('p.odds1, p.odds3')
            ).some((odds) => odds.offsetParent !== null);
            if (!globalReady || !matchId || !hasOdds) {
                return null;
            }

            const homeCell = match.querySelector('td[id^="ht_"]');
            const awayCell = match.querySelector('td[id^="gt_"]');
            const redCardCount = (cell, selector) => {
                const count = Number.parseInt(
                    cleanText(cell?.querySelector(selector)?.textContent),
                    10
                );
                return Number.isNaN(count) ? 0 : count;
            };
            const redcards =
                redCardCount(homeCell, '[id^="redcard1_"] .redcard') +
                redCardCount(awayCell, '[id^="redcard2_"] .redcard');
            const scoreText = cleanText(
                match.querySelector(
                    'td.blue.handpoint[onclick*="soccerInPage.detail"]'
                )?.textContent
            );
            const score = scoreText.match(/(\d+)\s*[-:]\s*(\d+)/);

            return {
                match_id: matchId,
                league_id: leagueId,
                match_time: matchTime,
                over_odd: overOdd,
                total: total,
                under_odd: underOdd,
                ah_home_odd: ahHomeOdd,
                ah_away_odd: ahAwayOdd,
                ah_handicap: ahHandicap,
                home_team: teamName(homeCell?.querySelector('[id^="team1_"]')),
                away_team: teamName(awayCell?.querySelector('[id^="team2_"]')),
                home_score: score ? score[1] : '',
                away_score: score ? score[2] : '',
                redcards: redcards,
            };
        })
        .filter((match) => match !== null);
}
""".replace("__GLOBAL_ODDS_READY__", _GLOBAL_ODDS_READY_JS)


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
    except Exception:
        logger.error("Cannot load all matches data from DOM", exc_info=True)
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
    except Exception:
        logger.error("Failed to collect current match snapshot", exc_info=True)
        raise


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
    try:
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
    except Exception:
        logger.error("Failed to scrape match data", exc_info=True)
        raise


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
    try:
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
        page.evaluate(
            """
            ([callbackName, observerKey]) => {
                const liveTable = document.querySelector('#table_live');
                if (!liveTable) {
                    throw new Error('#table_live not found.');
                }
                const belongsToLiveTable = (node) => {
                    const element = node.nodeType === Node.ELEMENT_NODE
                        ? node
                        : node.parentElement;
                    return Boolean(
                        element && element.closest('table#table_live')
                    );
                };
                const containsLiveTable = (node) => {
                    const element = node.nodeType === Node.ELEMENT_NODE
                        ? node
                        : node.parentElement;
                    return Boolean(
                        element && (
                            element.matches('table#table_live') ||
                            element.querySelector('table#table_live')
                        )
                    );
                };

                const observer = new MutationObserver((records) => {
                    const liveTableChanged = records.some((record) => {
                        if (belongsToLiveTable(record.target)) return true;
                        return [...record.addedNodes, ...record.removedNodes].some(
                            (node) => belongsToLiveTable(node) ||
                                containsLiveTable(node)
                        );
                    });
                    if (liveTableChanged) window[callbackName]();
                });
                observer.observe(document.documentElement, {
                    childList: true,
                    subtree: true,
                    characterData: true,
                    attributes: true,
                    attributeFilter: ['class', 'style'],
                });
                window[observerKey] = observer;
            }
            """,
            [callback_name, observer_key],
        )

        return live_watch
    except Exception:
        logger.error("Failed to start live match monitoring", exc_info=True)
        raise
