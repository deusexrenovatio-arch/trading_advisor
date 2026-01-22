import logging
from typing import Optional


def configure_logging(level: str = "INFO", log_format: Optional[str] = None) -> None:
    if log_format is None:
        log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    logging.basicConfig(level=level, format=log_format)
