"""
Simple logger utility using loguru.
"""

import sys
from pathlib import Path
from loguru import logger

# Remove default handler
logger.remove()

# Console output
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO"
)

# File output
LOG_DIR = Path("/Users/Shinji/Coding/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.add(
    LOG_DIR / "system" / "system_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG"
)


def get_logger(name: str):
    """获取带名称的logger"""
    return logger.bind(name=name)
