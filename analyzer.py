import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

import config
from logger import logger
from models import Match
from notifier import TelegramNotifier
from signal_formatter import format_signal_details
from strategy import find_ah_signal, find_over_signal


def _is_valid_saved_state(state: object) -> bool:
	if not isinstance(state, dict):
		return False

	active_match_ids = state.get("active_match_ids")
	histories = state.get("histories")
	copy_histories = state.get("copy_histories")
	closed_markets_until = state.get("closed_markets_until")
	if (
		not isinstance(active_match_ids, list)
		or not all(isinstance(match_id, str) for match_id in active_match_ids)
		or not isinstance(histories, dict)
		or not isinstance(copy_histories, dict)
		or not isinstance(closed_markets_until, dict)
	):
		return False
	if (
		set(active_match_ids) != set(histories)
		or set(histories) != set(copy_histories)
	):
		return False

	for match_histories in (histories, copy_histories):
		for match_id, entries in match_histories.items():
			if not isinstance(match_id, str) or not isinstance(entries, list):
				return False
			if any(
				not isinstance(entry, dict)
				or not isinstance(entry.get("observed_at"), str)
				or not isinstance(entry.get("match_data"), dict)
				or not isinstance(entry.get("market_data"), dict)
				for entry in entries
			):
				return False

	for match_id, deadline in closed_markets_until.items():
		if not isinstance(match_id, str) or not isinstance(deadline, str):
			return False
		try:
			datetime.fromisoformat(deadline)
		except ValueError:
			return False

	return True


def load_state_from_json(path: str | Path | None = None) -> dict | None:
	state_path = Path(path) if path is not None else config.STATE_SAVE_FILE
	if not state_path.exists():
		return None

	try:
		saved_state = json.loads(state_path.read_text(encoding="utf-8"))
		if not _is_valid_saved_state(saved_state):
			raise ValueError("saved state has an invalid structure")
		state_path.unlink()
		logger.info("Loaded and removed saved state file %s", state_path)
		return saved_state
	except (OSError, ValueError, TypeError) as error:
		logger.error("Failed to load state from %s: %s", state_path, error)
		return None


class MatchAnalyzer:
	# Настраивает хранение истории и уже отправленных сигналов.
	def __init__(
		self,
		history_path: str | Path | None = None,
		database_path: str | Path | None = None,
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
		self.database_path = (
			Path(database_path)
			if database_path is not None
			else Path(__file__).with_name("matches.sqlite3")
		)
		self.notifier = notifier
		self._initialize_signals_database()

	# Создаёт историю и проверяет начальные данные матчей.
	def initialize(
		self,
		matches: list[Match],
		saved_state: dict | None = None,
	) -> None:
		self.histories.clear()
		self.copy_histories.clear()
		self._closed_markets_until.clear()

		if saved_state is not None:
			self._restore_state(saved_state, matches)
		else:
			for match in matches:
				self._append_match(match)

		self._write_history()
		for match in matches:
			if match.match_id:
				self._analyze_match(match.match_id)

	# Восстанавливает историю активных матчей из сохранённого состояния.
	def _restore_state(
		self,
		saved_state: dict,
		matches: list[Match],
	) -> None:
		if not _is_valid_saved_state(saved_state):
			raise ValueError("saved state has an invalid structure")

		current_matches = {
			match.match_id: match for match in matches if match.match_id
		}
		saved_match_ids = set(saved_state["active_match_ids"])
		current_match_ids = set(current_matches)
		synchronized_match_ids = saved_match_ids & current_match_ids
		new_match_ids = [
			match_id
			for match_id in current_matches
			if match_id not in saved_match_ids
		]
		removed_match_ids = [
			match_id
			for match_id in saved_state["active_match_ids"]
			if match_id not in current_match_ids
		]

		self.histories.update(
			{
				match_id: deepcopy(saved_state["histories"][match_id])
				for match_id in current_matches
				if match_id in synchronized_match_ids
			}
		)
		self.copy_histories.update(
			{
				match_id: deepcopy(saved_state["copy_histories"][match_id])
				for match_id in current_matches
				if match_id in synchronized_match_ids
			}
		)
		self._closed_markets_until.update(
			{
				match_id: datetime.fromisoformat(deadline)
				for match_id, deadline in saved_state[
					"closed_markets_until"
				].items()
				if match_id in current_match_ids
			}
		)

		for match in current_matches.values():
			self._append_match(match)

		logger.info(
			"Matches synchronized: Active %d (%s) New %d (%s) "
			"Removed %d (%s)",
			len(self.histories),
			", ".join(self.histories) or "-",
			len(new_match_ids),
			", ".join(new_match_ids) or "-",
			len(removed_match_ids),
			", ".join(removed_match_ids) or "-",
		)

	# Сохраняет историю матчей, чтобы продолжить анализ после перезапуска.
	def save_state(self, path: str | Path | None = None) -> bool:
		state_path = Path(path) if path is not None else config.STATE_SAVE_FILE
		payload = {
			"active_match_ids": list(self.histories),
			"histories": self.histories,
			"copy_histories": self.copy_histories,
			"closed_markets_until": {
				match_id: deadline.isoformat()
				for match_id, deadline in self._closed_markets_until.items()
			},
		}

		try:
			state_path.write_text(
				json.dumps(payload, ensure_ascii=False, indent=2),
				encoding="utf-8",
			)
		except (OSError, TypeError, ValueError) as error:
			logger.error("Failed to save state to %s: %s", state_path, error)
			return False

		logger.info("Saved state to %s", state_path)
		return True

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
		if config.DEBUG_MODE != 1:
			return
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

	# Создаёт таблицу сигналов, если база ещё не инициализирована.
	def _initialize_signals_database(self) -> None:
		with closing(sqlite3.connect(self.database_path)) as connection:
			with connection:
				connection.execute(
					"""
					CREATE TABLE IF NOT EXISTS signals (
						date TEXT NOT NULL,
						league TEXT NOT NULL,
						home_team TEXT NOT NULL,
						away_team TEXT NOT NULL,
						prediction TEXT NOT NULL,
						final_score TEXT NOT NULL DEFAULT '',
						result TEXT NOT NULL DEFAULT '',
						match_id TEXT NOT NULL,
						strategy TEXT NOT NULL,
						source TEXT NOT NULL,
						UNIQUE (strategy, match_id)
					)
					"""
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
				telegram_message = self._save_signal("over", over_signal)
				if telegram_message is not None:
					logger.info(over_signal["message"])
					self._notify("over", over_signal, telegram_message)

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
				telegram_message = self._save_signal("ah", ah_signal)
				if telegram_message is not None:
					logger.info(ah_signal["message"])
					self._notify("ah", ah_signal, telegram_message)

	# Проверяет, был ли уже сохранён сигнал этой стратегии для матча.
	def _has_signal(self, strategy: str, match_id: str) -> bool:
		with closing(sqlite3.connect(self.database_path)) as connection:
			return connection.execute(
				"""
				SELECT 1 FROM signals
				WHERE strategy = ? AND match_id = ?
				LIMIT 1
				""",
				(strategy, match_id),
			).fetchone() is not None

	# Сохраняет отправляемый сигнал с данными матча.
	def _save_signal(self, strategy: str, signal: dict) -> str | None:
		match_data = signal["anchor"]["match_data"]
		match_id = str(match_data.get("match_id", signal.get("match_id", "")))
		history = self.copy_histories.get(match_id, [])
		latest_match_time = None
		if history:
			latest_match_data = history[-1].get("match_data")
			if isinstance(latest_match_data, dict):
				latest_match_time = latest_match_data.get("match_time")
		telegram_message, prediction = format_signal_details(
			strategy,
			signal,
			latest_match_time=latest_match_time,
		)
		record = (
			date.today().isoformat(),
			str(match_data.get("league", "")),
			str(match_data.get("home_team", "")),
			str(match_data.get("away_team", "")),
			prediction,
			"",
			"",
			match_id,
			strategy,
			config.SIGNAL_SOURCE,
		)
		with closing(sqlite3.connect(self.database_path)) as connection:
			with connection:
				cursor = connection.execute(
					"""
					INSERT INTO signals (
						date, league, home_team, away_team, prediction,
						final_score, result, match_id, strategy, source
					)
					VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
					ON CONFLICT(strategy, match_id) DO NOTHING
					""",
					record,
				)
		return telegram_message if cursor.rowcount == 1 else None

	# Отправляет сигнал через настроенный notifier.
	def _notify(
		self,
		strategy: str,
		signal: dict,
		formatted_message: str,
	) -> None:
		if self.notifier is not None:
			self.notifier.send_signal(
				strategy,
				signal,
				formatted_message=formatted_message,
			)
