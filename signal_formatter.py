from collections.abc import Callable
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import html
import re
from urllib.parse import quote

import config
from line_utils import normalize_handicap, normalize_total
from logger import logger


# Нормализует линию, если она содержит несколько частей.
def _normalize_line(
	value: object,
	normalizer: Callable[[object], Decimal | None],
) -> str:
	line = str(value)
	if "/" not in line:
		return line

	normalized = normalizer(line)
	return str(normalized) if normalized is not None else line


# Форматирует фору с учётом её знака.
def _format_handicap(value: object) -> str:
	handicap = _normalize_line(value, normalize_handicap)
	if "-" in handicap:
		return handicap

	try:
		number = Decimal(handicap.strip())
	except InvalidOperation:
		return handicap
	if not number.is_finite() or number <= 0:
		return handicap

	return f"-{handicap.strip().lstrip('+')}"


# Убирает лишние нули из десятичного числа.
def _format_decimal(value: Decimal) -> str:
	if value == 0:
		return "0"
	formatted = format(value.normalize(), "f")
	if "." in formatted:
		formatted = formatted.rstrip("0").rstrip(".")
	return formatted


# Форматирует фору для отображения со знаком.
def _format_display_handicap(value: Decimal) -> str:
	formatted = _format_decimal(value)
	return f"+{formatted}" if value > 0 else formatted


# Округляет четвертные линии тотала вверх до половины.
def _round_quarter_total(value: Decimal) -> Decimal:
	fractional_part = abs(value) % 1
	if fractional_part in (Decimal("0.25"), Decimal("0.75")):
		return (value * 2).to_integral_value(rounding=ROUND_CEILING) / 2
	return value


# Округляет четвертные форы от нуля до половины.
def _round_quarter_handicap(value: Decimal) -> Decimal:
	fractional_part = abs(value) % 1
	if fractional_part not in (Decimal("0.25"), Decimal("0.75")):
		return value

	rounded_magnitude = (
		(abs(value) * 2).to_integral_value(rounding=ROUND_CEILING) / 2
	)
	return -rounded_magnitude if value.is_signed() else rounded_magnitude


# Разбирает счёт и возвращает голы хозяев и гостей.
def _parse_score(score: str) -> tuple[int, int] | None:
	match = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", score)
	if match is None:
		return None
	return int(match.group(1)), int(match.group(2))


# Формирует текст сообщения и prediction по данным сигнала.
def _format_signal_parts(strategy: str, signal: dict) -> tuple[str, str]:
	anchor = signal.get("anchor")
	if not isinstance(anchor, dict):
		raise ValueError("Signal is missing its anchor record")
	match_data = anchor.get("match_data")
	market_data = anchor.get("market_data")
	if not isinstance(match_data, dict) or not isinstance(market_data, dict):
		raise ValueError("Signal anchor is missing match or market data")

	match_id = str(match_data.get("match_id", signal.get("match_id", "")))
	league = str(match_data.get("league", ""))
	match_time = str(match_data.get("match_time", ""))
	home_team = str(match_data.get("home_team", ""))
	away_team = str(match_data.get("away_team", ""))
	score = str(match_data.get("score", ""))
	if not all((match_id, league, match_time, home_team, away_team, score)):
		raise ValueError("Signal anchor is missing required match details")

	url = f"https://www.goaloo.com/oddscomp/{quote(match_id, safe='')}"
	header = f"<b>{html.escape(league)}</b>"
	match_line = (
		f"⚡ {html.escape(match_time)}’ "
		f'<a href="{html.escape(url, quote=True)}">'
		f"{html.escape(home_team)} "
		f"{html.escape(score.replace('-', ' - ', 1))} "
		f"{html.escape(away_team)}</a>"
	)

	if strategy == "over":
		market = market_data.get("over")
		value = market.get("total") if isinstance(market, dict) else None
		if value is None:
			raise ValueError("Over signal anchor is missing total")
		total = _normalize_line(value, normalize_total)
		try:
			display_total = _format_decimal(
				_round_quarter_total(Decimal(total))
			)
		except (InvalidOperation, ValueError):
			logger.warning(
				"Could not format total line for Telegram: %s",
				total,
			)
			display_total = total
		outcome = f"Тотал больше {html.escape(display_total)}"
	elif strategy == "ah":
		market = market_data.get("ah")
		value = market.get("handicap") if isinstance(market, dict) else None
		if value is None:
			raise ValueError("AH signal anchor is missing handicap")
		team = str(signal.get("team", ""))
		if team == home_team:
			side = "Home"
		elif team == away_team:
			side = "Away"
		else:
			raise ValueError("AH signal team does not match either match team")
		line = _format_handicap(value)
		try:
			handicap = Decimal(line)
			if not handicap.is_finite():
				raise ValueError("Handicap must be finite")
		except (InvalidOperation, ValueError):
			logger.warning("Could not parse handicap line for Telegram: %s", line)
			team_number = "1" if side == "Home" else "2"
			outcome = f"Фора {team_number} {html.escape(line)}"
		else:
			parsed_score = _parse_score(score)
			if parsed_score is None:
				logger.warning(
					"Could not recalculate handicap for Telegram "
					"with unknown score: %s",
					score,
				)
				team_number = "1" if side == "Home" else "2"
				outcome = (
					f"Фора {team_number} "
					f"{html.escape(_format_display_handicap(handicap))}"
				)
			else:
				home_score, away_score = parsed_score
				score_difference = (
					home_score - away_score
					if side == "Home"
					else away_score - home_score
				)
				display_handicap = _round_quarter_handicap(
					handicap - score_difference
				)
				normalized_outcome = config.NORMALIZED_HANDICAP_OUTCOMES.get(
					(side, display_handicap)
				)
				if normalized_outcome is not None:
					outcome = normalized_outcome
				else:
					team_number = "1" if side == "Home" else "2"
					outcome = (
						f"Фора {team_number} "
						f"{html.escape(_format_display_handicap(display_handicap))}"
					)
	else:
		raise ValueError(f"Unsupported signal strategy: {strategy}")

	return f"{header}\n{match_line}\n\n{outcome}", outcome


# Возвращает сообщение Telegram и исход для сохранения в базе.
def format_signal_details(strategy: str, signal: dict) -> tuple[str, str]:
	return _format_signal_parts(strategy, signal)


# Формирует HTML-сообщение Telegram по сигналу.
def format_signal(strategy: str, signal: dict) -> str:
	return format_signal_details(strategy, signal)[0]
