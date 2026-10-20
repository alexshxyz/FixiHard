import unittest

from models import Match, MatchDelta


class MatchTests(unittest.TestCase):
    def test_default_values_and_empty_teams(self):
        match = Match()

        self.assertEqual(match.match_id, "")
        self.assertEqual(match.redcards, 0)
        self.assertEqual(match.teams, "")

    def test_teams_are_formatted_only_when_both_names_are_present(self):
        match = Match(home_team="Home", away_team="Away")
        self.assertEqual(match.teams, "Home - Away")
        self.assertEqual(Match(home_team="Home").teams, "")
        self.assertEqual(Match(away_team="Away").teams, "")

    def test_to_dict_returns_all_fields_as_a_detached_dictionary(self):
        match = Match(match_id="m-1", home_team="Home", redcards=2)

        result = match.to_dict()

        self.assertEqual(
            result,
            {
                "match_id": "m-1",
                "league_id": "",
                "league": "",
                "home_team": "Home",
                "away_team": "",
                "match_time": "",
                "score": "",
                "redcards": 2,
                "over_odd": "",
                "under_odd": "",
                "total": "",
                "ah_home_odd": "",
                "ah_away_odd": "",
                "ah_handicap": "",
            },
        )
        result["match_id"] = "changed"
        self.assertEqual(match.match_id, "m-1")

    def test_to_match_data_dict_contains_match_details_not_market_values(self):
        match = Match(
            match_id="m-1",
            league_id="league-1",
            league="League",
            home_team="Home",
            away_team="Away",
            match_time="12",
            score="1:0",
            redcards=1,
            over_odd="1.9",
        )

        self.assertEqual(
            match.to_match_data_dict(),
            {
                "match_id": "m-1",
                "league_id": "league-1",
                "league": "League",
                "home_team": "Home",
                "away_team": "Away",
                "match_time": "12",
                "score": "1:0",
                "redcards": 1,
            },
        )

    def test_to_market_data_dict_groups_over_and_handicap_values(self):
        match = Match(
            over_odd="1.8",
            under_odd="2.0",
            total="2.5",
            ah_home_odd="1.9",
            ah_away_odd="1.95",
            ah_handicap="-0.5",
        )

        self.assertEqual(
            match.to_market_data_dict(),
            {
                "over": {
                    "odd": "1.8",
                    "under_odd": "2.0",
                    "total": "2.5",
                },
                "ah": {
                    "home_odd": "1.9",
                    "away_odd": "1.95",
                    "handicap": "-0.5",
                },
            },
        )

    def test_from_dict_converts_values_and_ignores_unknown_keys(self):
        match = Match.from_dict(
            {
                "match_id": 123,
                "league_id": 4,
                "redcards": "2",
                "over_odd": 1.85,
                "unknown": "ignored",
            }
        )

        self.assertEqual(match.match_id, "123")
        self.assertEqual(match.league_id, "4")
        self.assertEqual(match.redcards, 2)
        self.assertEqual(match.over_odd, "1.85")
        self.assertFalse(hasattr(match, "unknown"))

    def test_from_dict_uses_defaults_for_empty_input(self):
        self.assertEqual(Match.from_dict({}), Match())

    def test_from_dict_raises_for_invalid_redcards_value(self):
        with self.assertRaises(ValueError):
            Match.from_dict({"redcards": "not-a-number"})

    def test_from_dict_requires_a_mapping(self):
        with self.assertRaises(AttributeError):
            Match.from_dict(None)


class MatchDeltaTests(unittest.TestCase):
    def test_required_match_id_and_default_values(self):
        delta = MatchDelta(match_id="m-1")

        self.assertEqual(delta.match_id, "m-1")
        self.assertEqual(delta.to_dict(), {
            "match_id": "m-1",
            "changed_at": "",
            "total": "",
            "over_odd": "",
            "under_odd": "",
            "score": "",
        })

    def test_to_dict_includes_provided_delta_fields(self):
        delta = MatchDelta(
            match_id="m-1",
            changed_at="2026-10-20T12:00:00+00:00",
            total="2.5",
            over_odd="1.9",
            under_odd="2.0",
            score="1:0",
        )

        self.assertEqual(
            delta.to_dict(),
            {
                "match_id": "m-1",
                "changed_at": "2026-10-20T12:00:00+00:00",
                "total": "2.5",
                "over_odd": "1.9",
                "under_odd": "2.0",
                "score": "1:0",
            },
        )

    def test_match_id_is_required(self):
        with self.assertRaises(TypeError):
            MatchDelta()


if __name__ == "__main__":
    unittest.main()
