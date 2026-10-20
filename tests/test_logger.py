import logging
import unittest

import logger as logger_module


class LoggerTests(unittest.TestCase):
    def test_logger_has_expected_level_and_does_not_propagate(self):
        self.assertEqual(logger_module.logger.name, "fixi-hard")
        self.assertEqual(logger_module.logger.level, logging.INFO)
        self.assertFalse(logger_module.logger.propagate)

    def test_console_formatter_sanitizes_match_counts_without_mutating_record(self):
        console_handler = next(
            handler
            for handler in logger_module.logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        )
        record = logging.LogRecord(
            "fixi-hard",
            logging.INFO,
            "logger.py",
            1,
            "Matches updated: %d (12, 34) Match %d",
            (2, 7),
            None,
        )
        original_message = record.msg
        original_args = record.args

        formatted = console_handler.formatter.format(record)

        self.assertTrue(formatted.endswith("INFO: Matches updated: 2 Match"))
        self.assertEqual(record.msg, original_message)
        self.assertEqual(record.args, original_args)

    def test_console_formatter_handles_empty_numeric_parentheses(self):
        console_handler = next(
            handler
            for handler in logger_module.logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        )
        record = logging.LogRecord(
            "fixi-hard",
            logging.INFO,
            "logger.py",
            1,
            "No matches ()",
            (),
            None,
        )

        formatted = console_handler.formatter.format(record)

        self.assertTrue(formatted.endswith("INFO: No matches"))

    def test_file_formatter_preserves_original_message(self):
        file_handler = next(
            handler
            for handler in logger_module.logger.handlers
            if isinstance(handler, logging.FileHandler)
        )
        record = logging.LogRecord(
            "fixi-hard",
            logging.INFO,
            "logger.py",
            1,
            "Match %d (12, 34)",
            (7,),
            None,
        )

        formatted = file_handler.formatter.format(record)

        self.assertTrue(formatted.endswith("INFO: Match 7 (12, 34)"))
        self.assertEqual(record.msg, "Match %d (12, 34)")
        self.assertEqual(record.args, (7,))


if __name__ == "__main__":
    unittest.main()
