from collections.abc import Callable
from decimal import Decimal, InvalidOperation
import html
import os
from pathlib import Path
import time
from urllib.parse import quote

import requests
from dotenv import load_dotenv

import config
from line_utils import normalize_handicap, normalize_total
from logger import logger


def _normalize_line(
	value: object,
	normalizer: Callable[[object], Decimal | None],
) -> str:
	line = str(value)
	if "/" not in line:
		return line

	normalized = normalizer(line)
	return str(normalized) if normalized is not None else line


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


class TelegramNotifier:
	# Проверяет и сохраняет параметры Telegram-уведомлений.
	def __init__(
		self,
		bot_token: str,
		channel_id: str,
		proxy_url: str | None = None,
	):
		if not bot_token.strip():
			raise ValueError("BOT_TOKEN must not be empty")
		if not channel_id.strip():
			raise ValueError("CHANNEL_ID must not be empty")

		self.bot_token = bot_token.strip()
		self.channel_id = channel_id.strip()
		self.proxy_url = proxy_url

	# Создаёт notifier из переменных окружения.
	@classmethod
	def from_environment(cls) -> "TelegramNotifier":
		load_dotenv(Path(__file__).with_name(".env"))
		bot_token = os.getenv("BOT_TOKEN", "")
		channel_id = os.getenv("CHANNEL_ID", "")
		proxy_host = os.getenv("TELEGRAM_PROXY_HOST", "").strip()
		proxy_port = os.getenv("TELEGRAM_PROXY_PORT", "").strip()
		proxy_username = os.getenv("TELEGRAM_PROXY_USERNAME", "")
		proxy_password = os.getenv("TELEGRAM_PROXY_PASSWORD", "")

		if bool(proxy_host) != bool(proxy_port):
			raise ValueError(
				"TELEGRAM_PROXY_HOST and TELEGRAM_PROXY_PORT must be set together"
			)
		if bool(proxy_username) != bool(proxy_password):
			raise ValueError(
				"TELEGRAM_PROXY_USERNAME and TELEGRAM_PROXY_PASSWORD "
				"must be set together"
			)

		proxy_url = None
		if proxy_host:
			auth = ""
			if proxy_username:
				auth = (
					f"{quote(proxy_username, safe='')}:"
					f"{quote(proxy_password, safe='')}@"
				)
			try:
				port = int(proxy_port)
			except ValueError as error:
				raise ValueError("TELEGRAM_PROXY_PORT must be a number") from error
			if not 1 <= port <= 65535:
				raise ValueError("TELEGRAM_PROXY_PORT must be between 1 and 65535")
			proxy_url = f"socks5h://{auth}{proxy_host}:{proxy_port}"

		return cls(bot_token, channel_id, proxy_url)

	# Формирует HTML-сообщение по сигналу стратегии.
	def format_signal(self, strategy: str, signal: dict) -> str:
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
			f"🧊 {html.escape(match_time)}’ "
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
			outcome = f"Over {html.escape(total)}"
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
			outcome = f"Handicap {html.escape(_format_handicap(value))} {side}"
		else:
			raise ValueError(f"Unsupported signal strategy: {strategy}")

		return f"{header}\n{match_line}\n\n{outcome}"

	# Отправляет уведомление Telegram с повторными попытками.
	def send_signal(self, strategy: str, signal: dict) -> bool:
		message = self.format_signal(strategy, signal)
		url = (
			"https://api.telegram.org/bot"
			f"{self.bot_token}/sendMessage"
		)
		proxies = (
			{"http": self.proxy_url, "https": self.proxy_url}
			if self.proxy_url
			else None
		)

		for attempt in range(1, config.TELEGRAM_MAX_ATTEMPTS + 1):
			try:
				response = requests.post(
					url,
					data={
						"chat_id": self.channel_id,
						"text": message,
						"parse_mode": "HTML",
						"disable_web_page_preview": "true",
					},
					proxies=proxies,
					timeout=config.TELEGRAM_REQUEST_TIMEOUT_SECONDS,
				)
				response.raise_for_status()
				result = response.json()
				if not isinstance(result, dict) or result.get("ok") is not True:
					description = (
						result.get("description", "Invalid Telegram API response")
						if isinstance(result, dict)
						else "Invalid Telegram API response"
					)
					raise RuntimeError(description)
				return True
			except (requests.RequestException, ValueError, RuntimeError) as error:
				if attempt < config.TELEGRAM_MAX_ATTEMPTS:
					time.sleep(config.TELEGRAM_RETRY_DELAY_SECONDS)
				else:
					logger.error(
						"Telegram notification failed after %d attempts "
						"(%s): %s",
						config.TELEGRAM_MAX_ATTEMPTS,
						type(error).__name__,
						self._sanitize_error(str(error)),
					)
		return False

	# Удаляет секреты из текста ошибки перед логированием.
	def _sanitize_error(self, message: str) -> str:
		for secret in (
			self.bot_token,
			self.proxy_url or "",
		):
			if secret:
				message = message.replace(secret, "[REDACTED]")
		return message
