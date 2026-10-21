# Конфигурация сайта
SITE_URL = "https://www.goaloo.com/"
HEADLESS = False

# Интервал обновления таблицы матчей
LIVE_REFRESH_INTERVAL_SECONDS = (100, 120)

# Интервал полной перезагрузки страницы
PAGE_REFRESH_INTERVAL_SECONDS = 18

# Куки для сайта
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
