import json
from datetime import datetime, timedelta
from pathlib import Path

import config
from logger import logger
from models import Match
from notifier import TelegramNotifier
from strategy import find_ah_signal, find_over_signal


class MatchAnalyzer:
	# Настраивает хранение истории и уже отправленных сигналов.
	def __init__(
		self,
		history_path: str | Path | None = None,
		signals_path: str | Path | None = None,
		history_copy_path: str | Path | None = None,
		notifier: TelegramNotifier | None = None,
	):
		self.histories: dict[str, list[dict]] = {}
		self.copy_histories: dict[str, list[dict]] = {}
		self._closed_markets_until: dict[str, datetime] = {}
		self.history_path = (
			Path(history_path)
			if history_path is not None
			else Path(__file__).with_name("matches_history.json")
		)
		self.history_copy_path = (
			Path(history_copy_path)
			if history_copy_path is not None
			else self.history_path.with_name("matches_history_copy.json")
		)
		self.signals_path = (
			Path(signals_path)
			if signals_path is not None
			else Path(__file__).with_name("matches.json")
		)
		self.notifier = notifier
		self.signals = self._read_signals()

	# Создаёт историю и проверяет начальные данные матчей.
	def initialize(self, matches: list[Match]) -> None:
		self.histories.clear()
		self.copy_histories.clear()
		self._closed_markets_until.clear()
		for match in matches:
			self._append_match(match)
		self._write_history()
		for match in matches:
			if match.match_id:
				self._analyze_match(match.match_id)

	# Добавляет обновления матчей и анализирует изменившиеся записи.
	def record_updates(self, matches: list[Match]) -> None:
		changed_match_ids = set()
		for match in matches:
			if self._append_match(match):
				changed_match_ids.add(match.match_id)
		if changed_match_ids:
			self._write_history()
			for match_id in changed_match_ids:
				self._analyze_match(match_id)

	# Удаляет завершившиеся матчи из текущих историй.
	def remove_matches(self, match_ids: list[str]) -> None:
		changed = False
		for match_id in match_ids:
			if self.histories.pop(match_id, None) is not None:
				self.copy_histories.pop(match_id, None)
				self._closed_markets_until.pop(match_id, None)
				changed = True
		if changed:
			self._write_history()

	# Добавляет снимок матча в основную и фильтрованную историю.
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

		observed_at = datetime.now()
		if history:
			previous_score = history[-1]["match_data"].get("score", "")
			if previous_score and match.score and previous_score != match.score:
				self._closed_markets_until[match.match_id] = (
					observed_at
					+ timedelta(minutes=config.GOAL_MARKET_CLOSE_MINUTES)
				)

		entry = {
			"observed_at": observed_at.strftime("%Y-%m-%d %H:%M:%S"),
			"match_data": match_data,
			"market_data": market_data,
		}
		history.append(entry)

		copy_market_data = market_data
		closed_until = self._closed_markets_until.get(match.match_id)
		if closed_until is not None and observed_at < closed_until:
			copy_market_data = {
				"over": {
					**market_data["over"],
					"odd": "-",
					"under_odd": "-",
					"total": "Closed",
				},
				"ah": {
					**market_data["ah"],
					"home_odd": "-",
					"away_odd": "-",
					"handicap": "Closed",
				},
			}
		elif closed_until is not None:
			self._closed_markets_until.pop(match.match_id, None)

		self.copy_histories.setdefault(match.match_id, []).append(
			{
				**entry,
				"market_data": copy_market_data,
			}
		)
		return True

	# Записывает обе версии истории на диск.
	def _write_history(self) -> None:
		self._write_history_file(self.history_path, self.histories)
		self._write_history_file(self.history_copy_path, self.copy_histories)

	# Сериализует историю матчей в JSON-файл.
	@staticmethod
	def _write_history_file(path: Path, histories: dict[str, list[dict]]) -> None:
		document = {
			"matches": [
				{"match_id": match_id, "history": history}
				for match_id, history in histories.items()
			],
		}
		path.write_text(
			json.dumps(document, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)

	# Загружает и проверяет ранее сохранённые сигналы.
	def _read_signals(self) -> dict[str, list[str]]:
		if not self.signals_path.exists():
			return {"over": [], "ah": []}

		content = self.signals_path.read_text(encoding="utf-8")
		if not content.strip():
			return {"over": [], "ah": []}

		try:
			document = json.loads(content)
		except json.JSONDecodeError as error:
			raise ValueError(
				f"Invalid signals file: {self.signals_path}"
			) from error

		if document == []:
			return {"over": [], "ah": []}

		if not isinstance(document, dict) or not isinstance(
			document.get("over"), list
		):
			raise ValueError(
				f"Invalid signals file structure: {self.signals_path}"
			)

		signals = {}
		for strategy in ("over", "ah"):
			messages = document.get(strategy, [])
			if not isinstance(messages, list) or any(
				not isinstance(message, str) for message in messages
			):
				raise ValueError(
					f"Invalid {strategy} signals in {self.signals_path}"
				)
			signals[strategy] = messages
		signals.setdefault("ah", [])
		return signals

	# Сохраняет актуальный список сигналов в JSON-файл.
	def _write_signals(self, signals: dict[str, list[str]]) -> None:
		document = {"over": signals["over"], "ah": signals["ah"]}
		self.signals_path.write_text(
			json.dumps(document, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)

	# Ищет новые сигналы для матча и отправляет уведомления.
	def _analyze_match(self, match_id: str) -> None:
		history = self.copy_histories[match_id]
		if not self._has_signal("over", match_id):
			over_signal = find_over_signal(match_id, history)
			if over_signal is not None:
				current_total = over_signal["current"]["market_data"]["over"][
					"total"
				]
				anchor_total = over_signal["anchor"]["market_data"]["over"][
					"total"
				]
				over_signal["message"] = (
					f"{match_id} {current_total} -> {anchor_total}"
				)
				self._save_signal("over", over_signal["message"])
				logger.info(over_signal["message"])
				self._notify("over", over_signal)

		if not self._has_signal("ah", match_id):
			ah_signal = find_ah_signal(match_id, history)
			if ah_signal is not None:
				current_handicap = ah_signal["current"]["market_data"]["ah"][
					"handicap"
				]
				anchor_handicap = ah_signal["anchor"]["market_data"]["ah"][
					"handicap"
				]
				ah_signal["message"] = (
					f"{match_id} {current_handicap} -> {anchor_handicap}"
					f" | team: {ah_signal['team']}"
				)
				self._save_signal("ah", ah_signal["message"])
				logger.info(ah_signal["message"])
				self._notify("ah", ah_signal)

	# Проверяет, был ли уже сохранён сигнал для этого матча.
	def _has_signal(self, strategy: str, match_id: str) -> bool:
		return any(
			message.startswith(f"{match_id} ")
			for message in self.signals[strategy]
		)

	# Добавляет сигнал в файл и обновляет состояние анализатора.
	def _save_signal(self, strategy: str, message: str) -> None:
		updated_signals = {
			**self.signals,
			strategy: [*self.signals[strategy], message],
		}
		self._write_signals(updated_signals)
		self.signals = updated_signals

	# Отправляет сигнал через настроенный notifier.
	def _notify(self, strategy: str, signal: dict) -> None:
		if self.notifier is not None:
			self.notifier.send_signal(strategy, signal)
