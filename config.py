import os
from pathlib import Path
from decimal import Decimal

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=APP_DIR / ".env")


# Сайт и режим браузера
SITE_URL = "https://www.goaloo.com/"
HEADLESS = True
BROWSER_PROXY_SERVER = os.environ.get("BROWSER_PROXY_SERVER")
SITE_COOKIES = [
	{"name": "goaloo_SelCompany_V2", "value": "8", "domain": "www.goaloo.com", "path": "/"},
	{"name": "Default_TimeZone", "value": "3", "domain": "www.goaloo.com", "path": "/"},
	{"name": "isOddsShow", "value": "1", "domain": "www.goaloo.com", "path": "/"},
	{"name": "OddsShowType", "value": "9", "domain": "www.goaloo.com", "path": "/"},
	{"name": "goalWindowCheck", "value": "0", "domain": "www.goaloo.com", "path": "/"},
	{"name": "redWindowCheck", "value": "0", "domain": "www.goaloo.com", "path": "/"},
	{"name": "YellowCheck", "value": "0", "domain": "www.goaloo.com", "path": "/"},
	{"name": "orderby", "value": "time", "domain": "www.goaloo.com", "path": "/"},
]

# Аргументы запуска Chromium
BROWSER_ARGS = [
	"--disable-gpu",
	"--disable-dev-shm-usage",
	"--disable-infobars",
	"--no-sandbox",
	"--disable-setuid-sandbox",
	"--disable-notifications",
	"--disable-background-networking",
	"--disable-background-timer-throttling",
	"--disable-renderer-backgrounding",
	"--disable-extensions",
	"--disable-sync",
	"--metrics-recording-only",
	"--mute-audio",
]

# Периодические обновления страницы и цикла бота (секунды)
LIVE_REFRESH_INTERVAL_SECONDS = (100, 120)
PAGE_REFRESH_INTERVAL_SECONDS = 1800
MAIN_LOOP_WAIT_SECONDS = 1
RESTART_HOURS = 24


# Ожидания браузера и загрузки данных (секунды)
PAGE_NAVIGATION_TIMEOUT_SECONDS = 30
BROWSER_DEFAULT_TIMEOUT_SECONDS = 30
TABLE_TIMEOUT_SECONDS = 10
PAGE_TABLE_TIMEOUT_SECONDS = 20
POST_REFRESH_WAIT_SECONDS = 1
MATCH_DATA_TIMEOUT_SECONDS = 10
MATCH_ODDS_TIMEOUT_SECONDS = 30
VALID_MATCH_ODDS_TIMEOUT_SECONDS = 60
ODDS_POLL_INTERVAL_SECONDS = 1

# Повторные попытки обновлений (секунды и число попыток)
NO_MATCHES_RETRY_SECONDS = 60
REFRESH_RETRY_ATTEMPTS = 3
LIVE_REFRESH_RETRY_SECONDS = 5
PAGE_REFRESH_RETRY_SECONDS = 10

# Повторные попытки уведомлений Telegram (секунды и число попыток)
TELEGRAM_MAX_ATTEMPTS = 3
TELEGRAM_RETRY_DELAY_SECONDS = 3
TELEGRAM_REQUEST_TIMEOUT_SECONDS = 15

# Общие параметры стратегий
DEBUG_MODE = 0
GOAL_MARKET_CLOSE_MINUTES = 1
REDCARD_WINDOW_MINUTES = 20
MAX_OBSERVATION_INTERVAL_MINUTES = 5
TOTAL_INCREASE = 0.5 
REDCARD_THRESHOLD = 0
EXCLUDED_ANCHOR_MATCH_TIME_VALUES = ("90", "90+", "Penalty", "FT", "ET")
SIGNAL_SOURCE = "Bet365"

# Русские подписи стандартных исходов азиатской форы.
NORMALIZED_HANDICAP_OUTCOMES = {
	("Home", Decimal("-0.5")): "Победа 1",
	("Away", Decimal("-0.5")): "Победа 2",
	("Home", Decimal("0.5")): "1X",
	("Away", Decimal("0.5")): "X2",
}
