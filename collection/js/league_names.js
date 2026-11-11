
        () => Object.fromEntries(
            Array.from(document.querySelectorAll('#table_live tr.Leaguestitle[sclassid]'))
                .map((header) => {
                    const leagueId = header.getAttribute('sclassid');
                    const name = header.querySelector('.l1 .LGname, .l1 .fbsclass');
                    return [leagueId, (name?.textContent || '').trim()];
                })
                .filter(([leagueId, name]) => leagueId && name)
        )
