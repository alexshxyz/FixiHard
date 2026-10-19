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
			else Path(__file__).with_name("matches_history.json")
		)

	def initialize(self, matches: list[Match]) -> None:
		self.histories.clear()
		for match in matches:
			self._append_match(match)
		self._write_history()

	def record_updates(self, matches: list[Match]) -> None:
		changed = False
		for match in matches:
			changed = self._append_match(match) or changed
		if changed:
			self._write_history()

	def remove_matches(self, match_ids: list[str]) -> None:
		changed = False
		for match_id in match_ids:
			if self.histories.pop(match_id, None) is not None:
				changed = True
		if changed:
			self._write_history()

	def _append_match(self, match: Match) -> bool:
		if not match.match_id:
			return False

		history = self.histories.setdefault(match.match_id, [])
		match_data = match.to_match_data_dict()
		market_data = match.to_market_data_dict()
		if history and (
			history[-1]["match_data"] == match_data
			and history[-1]["market_data"] == market_data
		):
			return False

		history.append(
			{
				"observed_at": datetime.now(timezone.utc).isoformat(),
				"match_data": match_data,
				"market_data": market_data,
			}
		)
		return True

	def _write_history(self) -> None:
		document = {
			"matches": [
				{"match_id": match_id, "history": history}
				for match_id, history in self.histories.items()
			],
		}
		self.history_path.write_text(
			json.dumps(document, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)
