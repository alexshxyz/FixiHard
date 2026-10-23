import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import config
from logger import logger
from models import Match
from notifier import TelegramNotifier
from signal_formatter import format_signal_details
from strategy import find_ah_signal, find_over_signal


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
		telegram_message, prediction = format_signal_details(strategy, signal)
		record = (
			date.today().isoformat(),
			str(match_data.get("league", "")),
			str(match_data.get("home_team", "")),
			str(match_data.get("away_team", "")),
			prediction,
			"",
			"",
			str(match_data.get("match_id", signal.get("match_id", ""))),
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
