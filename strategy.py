from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import config
from line_utils import normalize_handicap as _normalize_handicap
from line_utils import normalize_total as _normalize_total


# Читает время наблюдения из записи истории.
def _entry_time(entry: dict) -> datetime | None:
	value = entry.get("observed_at")
	if not isinstance(value, str):
		return None

	try:
		return datetime.fromisoformat(value)
	except ValueError:
		return None


# Возвращает числовое значение рынка, если рынок открыт.
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


# Возвращает линию тотала из записи матча.
def _market_total(entry: dict) -> Decimal | None:
	return _market_value(
		entry,
		"over",
		"total",
		("odd", "under_odd"),
	)


# Возвращает фору из записи матча.
def _market_handicap(entry: dict) -> Decimal | None:
	market_data = entry.get("market_data")
	if not isinstance(market_data, dict):
		return None
	market = market_data.get("ah")
	if not isinstance(market, dict):
		return None

	for key in ("handicap", "home_odd", "away_odd"):
		if str(market.get(key, "")).strip().casefold() == "closed":
			return None

	return _normalize_handicap(market.get("handicap"))


# Возвращает счёт матча из записи истории.
def _match_score(entry: dict) -> str:
	match_data = entry.get("match_data")
	if not isinstance(match_data, dict):
		return ""
	score = match_data.get("score")
	return score.strip() if isinstance(score, str) else ""


# Проверяет, исключено ли время матча для якорной записи.
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


# Возвращает число удалений из данных матча.
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


# Проверяет время матча и отсутствие красной карточки в окне якоря.
def _is_valid_anchor(
	history: list[dict],
	anchor: dict,
	anchor_time: datetime,
) -> bool:
	if _has_excluded_anchor_match_time(anchor):
		return False

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
			return False
	return True


# Ищет накопленное движение линии до якорного значения.
def _find_cumulative_movement(
	history: list[dict],
	anchor_index: int,
	anchor_value: Decimal,
	anchor_time: datetime,
	anchor_score: str,
	value_for_entry: Callable[[dict], Decimal | None],
	movement_for_step: Callable[[Decimal, Decimal, Decimal], Decimal],
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

		step = movement_for_step(older_value, newer_value, anchor_value)
		if step < 0 or step >= threshold:
			break
		accumulated_movement += step
		if accumulated_movement >= threshold:
			return index
		newer_value = older_value

	return None


# Находит якорь и проверяет общее условие накопленного движения линии.
def _find_signal_indices(
	history: list[dict],
	*,
	value_for_entry: Callable[[dict], Decimal | None],
	movement_for_step: Callable[[Decimal, Decimal, Decimal], Decimal],
	anchor_value_is_valid: Callable[[Decimal], bool] | None = None,
) -> tuple[int, int, Decimal] | None:
	anchor_index = None
	anchor_time = None
	anchor_value = None

	for index in range(len(history) - 1, -1, -1):
		entry = history[index]
		if not isinstance(entry, dict) or not _match_score(entry):
			continue
		value = value_for_entry(entry)
		observed_at = _entry_time(entry)
		if value is None or observed_at is None:
			continue
		anchor_index = index
		anchor_time = observed_at
		anchor_value = value
		break

	if anchor_index is None or anchor_time is None or anchor_value is None:
		return None

	anchor = history[anchor_index]
	if (
		anchor_value_is_valid is not None
		and not anchor_value_is_valid(anchor_value)
	):
		return None
	if not _is_valid_anchor(history, anchor, anchor_time):
		return None

	current_index = _find_cumulative_movement(
		history,
		anchor_index,
		anchor_value,
		anchor_time,
		_match_score(anchor),
		value_for_entry,
		movement_for_step,
	)
	if current_index is None:
		return None
	return current_index, anchor_index, anchor_value


# Находит сигнал при росте линии тотала.
def find_over_signal(match_id: str, history: list[dict]) -> dict | None:
	indices = _find_signal_indices(
		history,
		value_for_entry=_market_total,
		movement_for_step=lambda older, newer, _anchor: newer - older,
	)
	if indices is None:
		return None
	current_index, anchor_index, _ = indices
	return {
		"match_id": match_id,
		"current": history[current_index],
		"anchor": history[anchor_index],
	}


# Возвращает название команды из данных матча.
def _match_team(entry: dict, key: str) -> str:
	match_data = entry.get("match_data")
	if not isinstance(match_data, dict):
		return ""
	value = match_data.get(key)
	return value.strip() if isinstance(value, str) else ""


# Находит сигнал при движении форы от нуля.
def find_ah_signal(match_id: str, history: list[dict]) -> dict | None:
	indices = _find_signal_indices(
		history,
		value_for_entry=_market_handicap,
		movement_for_step=lambda older, newer, anchor_value: (
			newer - older if anchor_value >= 0 else older - newer
		),
		anchor_value_is_valid=lambda anchor_value: anchor_value not in {
			Decimal("-0.25"),
			Decimal("0.25"),
			Decimal("0"),
		},
	)
	if indices is None:
		return None
	current_index, anchor_index, anchor_handicap = indices
	anchor = history[anchor_index]

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
