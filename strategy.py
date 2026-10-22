from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import config


def _normalize_total(value: object) -> Decimal | None:
	if value is None:
		return None

	parts = str(value).strip().split("/")
	if len(parts) not in (1, 2):
		return None

	try:
		values = [Decimal(part.strip()) for part in parts]
	except InvalidOperation:
		return None

	if not all(part.is_finite() for part in values):
		return None
	return sum(values, Decimal(0)) / len(values)


def _entry_time(entry: dict) -> datetime | None:
	value = entry.get("observed_at")
	if not isinstance(value, str):
		return None

	try:
		return datetime.fromisoformat(value)
	except ValueError:
		return None


def _market_value(
	entry: dict,
	market_name: str,
	value_name: str,
	closed_value_names: tuple[str, ...],
) -> Decimal | None:
	market_data = entry.get("market_data")
	if not isinstance(market_data, dict):
		return None
	market = market_data.get(market_name)
	if not isinstance(market, dict):
		return None

	for key in (value_name, *closed_value_names):
		if str(market.get(key, "")).strip().casefold() == "closed":
			return None

	return _normalize_total(market.get(value_name))


def _market_total(entry: dict) -> Decimal | None:
	return _market_value(
		entry,
		"over",
		"total",
		("odd", "under_odd"),
	)


def _market_handicap(entry: dict) -> Decimal | None:
	return _market_value(
		entry,
		"ah",
		"handicap",
		("home_odd", "away_odd"),
	)


def _match_score(entry: dict) -> str:
	match_data = entry.get("match_data")
	if not isinstance(match_data, dict):
		return ""
	score = match_data.get("score")
	return score.strip() if isinstance(score, str) else ""


def _has_excluded_anchor_match_time(entry: dict) -> bool:
	match_data = entry.get("match_data")
	if not isinstance(match_data, dict):
		return False
	match_time = match_data.get("match_time")
	if not isinstance(match_time, str):
		return False
	match_time = match_time.casefold()
	return any(
		value.casefold() in match_time
		for value in config.EXCLUDED_ANCHOR_MATCH_TIME_VALUES
	)


def _redcard_count(entry: dict) -> Decimal | None:
	match_data = entry.get("match_data")
	if not isinstance(match_data, dict):
		return None
	value = match_data.get("redcards", match_data.get("redcard"))
	if value is None:
		return None

	try:
		count = Decimal(str(value))
	except InvalidOperation:
		return None
	return count if count.is_finite() else None


def _find_cumulative_movement(
	history: list[dict],
	anchor_index: int,
	anchor_value: Decimal,
	anchor_time: datetime,
	anchor_score: str,
	value_for_entry: Callable[[dict], Decimal | None],
	movement_for_step: Callable[[Decimal, Decimal], Decimal],
) -> int | None:
	threshold = Decimal(str(config.TOTAL_INCREASE))
	max_interval = timedelta(minutes=config.MAX_OBSERVATION_INTERVAL_MINUTES)
	newer_value = anchor_value
	accumulated_movement = Decimal(0)

	for index in range(anchor_index - 1, -1, -1):
		entry = history[index]
		if not isinstance(entry, dict):
			continue
		if _match_score(entry) != anchor_score:
			break

		older_value = value_for_entry(entry)
		if older_value is None:
			continue
		older_time = _entry_time(entry)
		if older_time is None:
			break
		if (anchor_time.tzinfo is None) != (older_time.tzinfo is None):
			break
		elapsed = anchor_time - older_time
		if elapsed < timedelta(0) or elapsed > max_interval:
			return None

		step = movement_for_step(older_value, newer_value)
		if step < 0 or step >= threshold:
			break
		accumulated_movement += step
		if accumulated_movement >= threshold:
			return index
		newer_value = older_value

	return None


def find_over_signal(match_id: str, history: list[dict]) -> dict | None:
	anchor_index = None
	anchor_time = None
	anchor_total = None

	for index in range(len(history) - 1, -1, -1):
		entry = history[index]
		if not isinstance(entry, dict) or not _match_score(entry):
			continue
		total = _market_total(entry)
		observed_at = _entry_time(entry)
		if total is None or observed_at is None:
			continue
		anchor_index = index
		anchor_time = observed_at
		anchor_total = total
		break

	if anchor_index is None or anchor_time is None or anchor_total is None:
		return None

	anchor = history[anchor_index]
	if _has_excluded_anchor_match_time(anchor):
		return None

	redcard_cutoff = anchor_time - timedelta(
		minutes=config.REDCARD_WINDOW_MINUTES
	)
	for entry in history:
		if not isinstance(entry, dict):
			continue
		observed_at = _entry_time(entry)
		if observed_at is None:
			continue
		if not redcard_cutoff <= observed_at <= anchor_time:
			continue
		redcards = _redcard_count(entry)
		if (
			redcards is not None
			and redcards > config.REDCARD_THRESHOLD
		):
			return None

	current_index = _find_cumulative_movement(
		history,
		anchor_index,
		anchor_total,
		anchor_time,
		_match_score(anchor),
		_market_total,
		lambda older, newer: newer - older,
	)
	if current_index is None:
		return None
	return {
		"match_id": match_id,
		"current": history[current_index],
		"anchor": anchor,
	}


def _match_team(entry: dict, key: str) -> str:
	match_data = entry.get("match_data")
	if not isinstance(match_data, dict):
		return ""
	value = match_data.get(key)
	return value.strip() if isinstance(value, str) else ""


def find_ah_signal(match_id: str, history: list[dict]) -> dict | None:
	anchor_index = None
	anchor_time = None
	anchor_handicap = None

	for index in range(len(history) - 1, -1, -1):
		entry = history[index]
		if not isinstance(entry, dict) or not _match_score(entry):
			continue
		handicap = _market_handicap(entry)
		observed_at = _entry_time(entry)
		if handicap is None or observed_at is None:
			continue
		anchor_index = index
		anchor_time = observed_at
		anchor_handicap = handicap
		break

	if (
		anchor_index is None
		or anchor_time is None
		or anchor_handicap is None
	):
		return None

	if anchor_handicap in {
		Decimal("-0.25"),
		Decimal("0.25"),
		Decimal("0"),
	}:
		return None

	anchor = history[anchor_index]
	if _has_excluded_anchor_match_time(anchor):
		return None

	redcard_cutoff = anchor_time - timedelta(
		minutes=config.REDCARD_WINDOW_MINUTES
	)
	for entry in history:
		if not isinstance(entry, dict):
			continue
		observed_at = _entry_time(entry)
		if observed_at is None:
			continue
		if not redcard_cutoff <= observed_at <= anchor_time:
			continue
		redcards = _redcard_count(entry)
		if redcards is not None and redcards > config.REDCARD_THRESHOLD:
			return None

	current_index = _find_cumulative_movement(
		history,
		anchor_index,
		anchor_handicap,
		anchor_time,
		_match_score(anchor),
		_market_handicap,
		lambda older, newer: (
			newer - older if anchor_handicap >= 0 else older - newer
		),
	)
	if current_index is None:
		return None

	team = (
		_match_team(anchor, "away_team")
		if anchor_handicap < 0
		else _match_team(anchor, "home_team")
	)
	if not team:
		return None
	return {
		"match_id": match_id,
		"current": history[current_index],
		"anchor": anchor,
		"team": team,
	}
