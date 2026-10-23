import unittest
from decimal import Decimal

from line_utils import normalize_handicap, normalize_total, parse_line_components


class LineUtilsTests(unittest.TestCase):
    def test_parses_single_and_two_part_lines(self):
        self.assertEqual(parse_line_components("3.25"), [Decimal("3.25")])
        self.assertEqual(
            parse_line_components("-1.5/2"),
            [Decimal("-1.5"), Decimal("2")],
        )

    def test_rejects_invalid_lines(self):
        for value in (None, "", "1/2/3", "invalid", "NaN", "Infinity"):
            with self.subTest(value=value):
                self.assertIsNone(parse_line_components(value))

    def test_normalizes_total_with_signed_components(self):
        self.assertEqual(normalize_total("3.0/3.5"), Decimal("3.25"))
        self.assertEqual(normalize_total("-1/0"), Decimal("-0.5"))
        self.assertEqual(normalize_total("3.25"), Decimal("3.25"))

    def test_normalizes_handicap_magnitude_and_sign(self):
        self.assertEqual(normalize_handicap("1.5/2"), Decimal("1.75"))
        self.assertEqual(normalize_handicap("-1.5/2"), Decimal("-1.75"))
        self.assertEqual(normalize_handicap("0/-0.5"), Decimal("-0.25"))
        self.assertEqual(normalize_handicap("-1.5"), Decimal("-1.5"))

    def test_normalizers_reject_invalid_lines(self):
        self.assertIsNone(normalize_total("1/2/3"))
        self.assertIsNone(normalize_handicap("invalid"))


if __name__ == "__main__":
    unittest.main()
