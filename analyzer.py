import json
from datetime import datetime, timezone
from pathlib import Path

from models import Match


class MatchAnalyzer:
	def __init__(self, history_path: str | Path | None = None):
		self.histories: dict[str, list[dict]] = {}
		self.history_path = (
			Path(history_path)
			if history_path is not None
			else Path(__file__).with_name("match_history.json")
		)

	def initialize(self, matches: list[Match]) -> None:
		self.histories.clear()
		for match in matches:
			self._append_match(match)
		self._write_sample_history()

	def record_updates(self, matches: list[Match]) -> None:
		changed = False
		for match in matches:
			changed = self._append_match(match) or changed
		if changed:
			self._write_sample_history()

	def remove_matches(self, match_ids: list[str]) -> None:
		changed = False
		for match_id in match_ids:
			if self.histories.pop(match_id, None) is not None:
				changed = True
		if changed:
			self._write_sample_history()

	def _append_match(self, match: Match) -> bool:
		if not match.match_id:
			return False

		history = self.histories.setdefault(match.match_id, [])
		match_data = match.to_dict()
		if history and history[-1]["match"] == match_data:
			return False

		history.append(
			{
				"observed_at": datetime.now(timezone.utc).isoformat(),
				"match": match_data,
			}
		)
		return True

	def _write_sample_history(self) -> None:
		match_id = next(iter(self.histories), None)
		document = {
			"match_id": match_id,
			"history": self.histories.get(match_id, []),
		}
		self.history_path.write_text(
			json.dumps(document, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)
