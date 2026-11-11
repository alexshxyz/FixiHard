# Проверяет, что глобальные коэффициенты Bet365 загружены и видимы.
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

# Проверяет, что появилась видимая строка матча с коэффициентами.
_MATCH_ODDS_READY_JS = r"""
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
        const hasOddsElement = Boolean(
            match.querySelector('p.odds1, p.odds3')
        );
        return Boolean(matchId && hasOddsElement);
    });
}
""".replace("__GLOBAL_ODDS_READY__", _GLOBAL_ODDS_READY_JS)

# Получает названия лиг по их ID из таблицы матчей.
_LEAGUE_NAMES_JS = r"""
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

# Извлекает видимые матчи, счёт, карточки и коэффициенты из таблицы.
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
            const hasOddsElement = Boolean(
                match.querySelector('p.odds1, p.odds3')
            );
            if (!globalReady || !matchId || !hasOddsElement) {
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
                    'td.blue.handpoint[onclick*="soccerInPage.detail"] b'
                )?.textContent
            );
            const score = scoreText.match(/(\d+)\s*-\s*(\d+)/);

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
                score: score ? `${score[1]}-${score[2]}` : '',
                redcards: redcards,
            };
        })
        .filter((match) => match !== null);
}
""".replace("__GLOBAL_ODDS_READY__", _GLOBAL_ODDS_READY_JS)

# Отслеживает изменения DOM и сообщает о переменах в таблице Live.
_LIVE_WATCH_OBSERVER_JS = r"""
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
        """
