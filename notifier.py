import os
from pathlib import Path
import time
from urllib.parse import quote

import requests
from dotenv import load_dotenv

import config
from logger import logger
from signal_formatter import format_signal as _format_signal


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
		return _format_signal(strategy, signal)

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
