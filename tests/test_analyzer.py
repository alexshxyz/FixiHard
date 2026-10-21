import unittest
from datetime import datetime
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from analyzer import MatchAnalyzer
from models import Match


class MatchAnalyzerTests(unittest.TestCase):
    def test_new_history_entries_use_sortable_datetime_format(self):
        with TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "matches_history.json"
            analyzer = MatchAnalyzer(history_path)
            now = datetime(2026, 10, 21, 20, 30, 9)

            with patch("analyzer.datetime") as datetime_mock:
                datetime_mock.now.return_value = now
                analyzer.initialize([Match(match_id="match-1")])

            self.assertEqual(
                analyzer.histories["match-1"][0]["observed_at"],
                "2026-10-21 20:30:09",
            )


if __name__ == "__main__":
    unittest.main()
