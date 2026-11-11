
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
