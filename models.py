from dataclasses import dataclass, asdict


@dataclass(slots=True)
class Match:
    # Контракт данных матча, который передаётся между scraper и analyzer.
    # Поля хранятся явно, чтобы не гонять словари между модулями.

    match_id: str = ""
    league_id: str = ""
    league: str = ""

    home_team: str = ""
    away_team: str = ""
    match_time: str = ""
    home_score: str = ""
    away_score: str = ""

    over_odd: str = ""
    under_odd: str = ""
    total: str = ""

    @property
    def teams(self) -> str:
        # Возвращает строку вида 'Home - Away'.
        if self.home_team and self.away_team:
            return f"{self.home_team} - {self.away_team}"
        return ""

    @property
    def score(self) -> str:
        # Возвращает строку вида '1 - 0'.
        if self.home_score and self.away_score:
            return f"{self.home_score} - {self.away_score}"
        return ""

    def to_dict(self) -> dict:
        # Преобразует объект в словарь для совместимости с логированием или сериализацией.
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Match":
        # Создаёт объект из словаря, чтобы постепенно мигрировать с dict на модели.
        return cls(
            match_id=str(data.get("match_id", "")),
            league_id=str(data.get("league_id", "")),
            league=str(data.get("league", "")),
            home_team=str(data.get("home_team", "")),
            away_team=str(data.get("away_team", "")),
            match_time=str(data.get("match_time", "")),
            home_score=str(data.get("home_score", "")),
            away_score=str(data.get("away_score", "")),
            over_odd=str(data.get("over_odd", "")),
            under_odd=str(data.get("under_odd", "")),
            total=str(data.get("total", "")),
        )


@dataclass(slots=True)
class MatchDelta:
    # Служебный контракт для обновления одного уже известного матча.
    # Необязательный класс на будущее: позволяет выражать, что конкретно
    # изменилось на странице и в какой момент это произошло.

    match_id: str
    changed_at: str = ""
    total: str = ""
    over_odd: str = ""
    under_odd: str = ""
    score: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
