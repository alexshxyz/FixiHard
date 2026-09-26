import logging


logger = logging.getLogger("fixi-hard")

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)

logger.setLevel(logging.INFO)
logger.propagate = False