from pathlib import Path


_JS_DIR = Path(__file__).with_name("js")


def _load_script(filename: str) -> str:
	return (_JS_DIR / filename).read_text(encoding="utf-8")


_GLOBAL_ODDS_READY_JS = _load_script("global_odds_ready.js")
_MATCH_ODDS_READY_JS = _load_script("match_odds_ready.js").replace(
	"__GLOBAL_ODDS_READY__",
	_GLOBAL_ODDS_READY_JS,
)
_LEAGUE_NAMES_JS = _load_script("league_names.js")
_MATCH_DATA_JS = _load_script("match_data.js").replace(
	"__GLOBAL_ODDS_READY__",
	_GLOBAL_ODDS_READY_JS,
)
_LIVE_WATCH_OBSERVER_JS = _load_script("live_watch_observer.js")
