from logger import logger


class _LiveWatch:
    # Управляет подпиской на изменения списка live-матчей.

    # Инициализируем наблюдатель и сохраняем начальный snapshot.
    def __init__(
        self,
        page,
        observer_key,
        on_matches_update,
        initial_matches,
        collect_current_matches,
        on_matches_deleted=None,
    ):
        self._page = page
        self._observer_key = observer_key
        self._on_matches_update = on_matches_update
        self._on_matches_deleted = on_matches_deleted
        self._collect_current_matches = collect_current_matches
        self._matches_by_id = {match.match_id: match for match in initial_matches}
        self._snapshot_by_id = dict(self._matches_by_id)
        self._pending_update = False
        self._stopped = False

    # Помечаем наличие изменений DOM для основного цикла.
    def _mark_dom_change(self):
        self._pending_update = True

    # Собираем snapshot и передаём только изменённые матчи.
    def process_pending(self):
        if not self._pending_update:
            return

        self._pending_update = False
        current_matches = self._collect_current_matches(self._page)
        updated_matches = []
        for match in current_matches:
            if self._matches_by_id.get(match.match_id) != match:
                updated_matches.append(match)
                self._matches_by_id[match.match_id] = match

        if updated_matches:
            self._on_matches_update(updated_matches)

    # Сверяем полный снимок после обновления и забываем исчезнувшие матчи.
    def reconcile_after_refresh(self, current_matches):
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
        if deleted_ids and self._on_matches_deleted is not None:
            self._on_matches_deleted(deleted_ids)

        logger.info(
            "Matches updated: Added %d (%s) Deleted %d (%s)",
            len(added_ids),
            ", ".join(added_ids),
            len(deleted_ids),
            ", ".join(deleted_ids),
        )

    # Останавливаем наблюдатель за изменениями DOM.
    def stop(self):
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
        logger.info("Live match monitoring stopped")
