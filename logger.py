import copy
import logging
from pathlib import Path
import re


logger = logging.getLogger("fixi-hard")

if not logger.handlers:
    date_format = "%Y-%m-%d %H:%M:%S"
    log_format = "%(asctime)s %(levelname)s: %(message)s"

    class ConsoleFormatter(logging.Formatter):
        # Форматирует консольный лог без повторяющихся деталей.
        def format(self, record):
            console_record = copy.copy(record)
            message = console_record.getMessage()
            message = re.sub(
                r"\s*\(\s*(?:\d+(?:\s*,\s*\d+)*\s*)?\)",
                "",
                message,
            )
            message = re.sub(r"\bMatch\s+\d+\b", "Match", message)
            console_record.msg = message
            console_record.args = ()
            return super().format(console_record)

    formatter = logging.Formatter(
        log_format,
        datefmt=date_format,
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        ConsoleFormatter(log_format, datefmt=date_format)
    )
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(
        Path(__file__).resolve().with_name("bot.log"),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

logger.setLevel(logging.INFO)
logger.propagate = False