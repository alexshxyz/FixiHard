
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
