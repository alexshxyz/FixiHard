import unittest
from unittest.mock import Mock, call, patch

from live_watch import _LiveWatch
from models import Match


_DEFAULT_DELETE_CALLBACK = object()


class LiveWatchTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock()
        self.on_update = Mock()
        self.on_deleted = Mock()
        self.collect_matches = Mock()
        self.logger_patcher = patch("live_watch.logger")
        self.logger = self.logger_patcher.start()
        self.addCleanup(self.logger_patcher.stop)
        self.initial = Match(match_id="match-1", score="0:0")
        self.watch = self._make_watch([self.initial])

    def _make_watch(self, initial_matches, on_deleted=_DEFAULT_DELETE_CALLBACK):
        if on_deleted is _DEFAULT_DELETE_CALLBACK:
            on_deleted = self.on_deleted
        return _LiveWatch(
            self.page,
            "observer-key",
            self.on_update,
            initial_matches,
            self.collect_matches,
            on_deleted,
        )

    def test_initializes_current_and_snapshot_maps_from_initial_matches(self):
        second_match = Match(match_id="match-2")

        watch = self._make_watch([self.initial, second_match])

        self.assertEqual(
            watch._matches_by_id,
            {"match-1": self.initial, "match-2": second_match},
        )
        self.assertEqual(watch._snapshot_by_id, watch._matches_by_id)
        self.assertFalse(watch._pending_update)
        self.assertFalse(watch._stopped)

    def test_duplicate_match_ids_keep_last_match(self):
        replacement = Match(match_id="match-1", score="1:0")

        watch = self._make_watch([self.initial, replacement])

        self.assertEqual(watch._matches_by_id, {"match-1": replacement})
        self.assertEqual(watch._snapshot_by_id, {"match-1": replacement})

    def test_process_pending_does_nothing_when_dom_has_not_changed(self):
        self.watch.process_pending()

        self.collect_matches.assert_not_called()
        self.on_update.assert_not_called()

    def test_process_pending_collects_and_reports_only_changed_or_new_matches(self):
        unchanged = Match(match_id="match-1", score="0:0")
        changed = Match(match_id="match-1", score="1:0")
        added = Match(match_id="match-2", score="0:0")
        self.collect_matches.return_value = [unchanged, changed, added]

        self.watch._mark_dom_change()
        self.watch.process_pending()

        self.collect_matches.assert_called_once_with(self.page)
        self.on_update.assert_called_once_with([changed, added])
        self.assertEqual(
            self.watch._matches_by_id,
            {"match-1": changed, "match-2": added},
        )
        self.assertFalse(self.watch._pending_update)

    def test_process_pending_with_no_effective_changes_skips_update_callback(self):
        self.collect_matches.return_value = [
            Match(match_id="match-1", score="0:0")
        ]

        self.watch._mark_dom_change()
        self.watch.process_pending()

        self.collect_matches.assert_called_once_with(self.page)
        self.on_update.assert_not_called()

    def test_process_pending_empty_snapshot_does_not_emit_empty_update(self):
        self.collect_matches.return_value = []

        self.watch._mark_dom_change()
        self.watch.process_pending()

        self.on_update.assert_not_called()
        self.assertEqual(self.watch._matches_by_id, {"match-1": self.initial})

    def test_process_pending_clears_pending_flag_before_collection_error(self):
        self.collect_matches.side_effect = RuntimeError("collection failed")
        self.watch._mark_dom_change()

        with self.assertRaisesRegex(RuntimeError, "collection failed"):
            self.watch.process_pending()

        self.assertFalse(self.watch._pending_update)
        self.on_update.assert_not_called()

    def test_dom_change_marks_update_pending(self):
        self.watch._mark_dom_change()

        self.assertTrue(self.watch._pending_update)

    def test_reconcile_reports_added_changed_and_deleted_matches(self):
        changed = Match(match_id="match-1", score="1:0")
        added = Match(match_id="match-2", score="0:0")

        self.watch.reconcile_after_refresh([changed, added])

        self.on_update.assert_called_once_with([changed, added])
        self.on_deleted.assert_not_called()
        self.assertEqual(
            self.watch._matches_by_id,
            {"match-1": changed, "match-2": added},
        )
        self.assertEqual(self.watch._snapshot_by_id, self.watch._matches_by_id)
        self.logger.info.assert_called_once_with(
            "Matches updated: Added %d (%s) Deleted %d (%s)",
            1,
            "match-2",
            0,
            "",
        )

    def test_reconcile_logs_match_counts_before_update_callbacks(self):
        watch = self._make_watch(
            [self.initial, Match(match_id="match-2", score="0:0")]
        )
        events = []
        changed = Match(match_id="match-1", score="1:0")
        added = Match(match_id="match-3", score="0:0")
        self.logger.info.side_effect = lambda *args: events.append("summary")
        self.on_update.side_effect = lambda _matches: events.append("update")
        self.on_deleted.side_effect = lambda _ids: events.append("delete")

        watch.reconcile_after_refresh([changed, added])

        self.assertEqual(events, ["summary", "update", "delete"])

    def test_reconcile_reports_deleted_matches_and_updates_snapshot(self):
        self.watch.reconcile_after_refresh([])

        self.on_update.assert_not_called()
        self.on_deleted.assert_called_once_with(["match-1"])
        self.assertEqual(self.watch._matches_by_id, {})
        self.assertEqual(self.watch._snapshot_by_id, {})
        self.logger.info.assert_called_once_with(
            "Matches updated: Added %d (%s) Deleted %d (%s)",
            0,
            "",
            1,
            "match-1",
        )

    def test_reconcile_without_delete_callback_still_forgets_missing_matches(self):
        watch = self._make_watch([self.initial], on_deleted=None)

        watch.reconcile_after_refresh([])

        self.assertEqual(watch._matches_by_id, {})
        self.assertEqual(watch._snapshot_by_id, {})
        self.on_update.assert_not_called()
        self.logger.info.assert_called_once()

    def test_reconcile_empty_or_unchanged_snapshot_skips_callbacks(self):
        self.watch.reconcile_after_refresh(
            [Match(match_id="match-1", score="0:0")]
        )

        self.on_update.assert_not_called()
        self.on_deleted.assert_not_called()
        self.logger.info.assert_called_once_with(
            "Matches updated: Added %d (%s) Deleted %d (%s)",
            0,
            "",
            0,
            "",
        )

    def test_reconcile_detects_later_reappearance_as_added(self):
        self.watch.reconcile_after_refresh([])
        self.on_deleted.reset_mock()
        self.logger.info.reset_mock()
        reappeared = Match(match_id="match-1", score="0:0")

        self.watch.reconcile_after_refresh([reappeared])

        self.on_update.assert_called_once_with([reappeared])
        self.on_deleted.assert_not_called()
        self.logger.info.assert_called_once_with(
            "Matches updated: Added %d (%s) Deleted %d (%s)",
            1,
            "match-1",
            0,
            "",
        )

    def test_reconcile_propagates_update_callback_error_after_refreshing_state(self):
        self.on_update.side_effect = RuntimeError("update callback failed")
        updated = Match(match_id="match-1", score="1:0")

        with self.assertRaisesRegex(RuntimeError, "update callback failed"):
            self.watch.reconcile_after_refresh([updated])

        self.assertEqual(self.watch._matches_by_id, {"match-1": updated})
        self.assertEqual(self.watch._snapshot_by_id, {"match-1": updated})
        self.logger.info.assert_called_once_with(
            "Matches updated: Added %d (%s) Deleted %d (%s)",
            0,
            "",
            0,
            "",
        )

    def test_stop_disconnects_observer_and_logs(self):
        self.watch.stop()

        self.page.evaluate.assert_called_once()
        self.assertEqual(
            self.page.evaluate.call_args.args[1],
            "observer-key",
        )
        self.logger.info.assert_called_once_with("Live match monitoring stopped")
        self.assertTrue(self.watch._stopped)

    def test_stop_is_idempotent(self):
        self.watch.stop()

        self.page.evaluate.reset_mock()
        self.logger.info.reset_mock()
        self.watch.stop()

        self.page.evaluate.assert_not_called()
        self.logger.info.assert_not_called()

    def test_stop_propagates_disconnect_error_and_can_be_retried(self):
        self.page.evaluate.side_effect = [
            RuntimeError("disconnect failed"),
            None,
        ]

        with self.assertRaisesRegex(RuntimeError, "disconnect failed"):
            self.watch.stop()

        self.assertFalse(self.watch._stopped)
        self.watch.stop()

        self.assertTrue(self.watch._stopped)
        self.assertEqual(self.page.evaluate.call_count, 2)
        self.logger.info.assert_called_once_with("Live match monitoring stopped")


if __name__ == "__main__":
    unittest.main()
