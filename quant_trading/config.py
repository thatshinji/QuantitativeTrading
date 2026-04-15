"""
Global configuration for the quantitative trading system.
Loads settings from YAML files and environment variables.
"""

import os
from pathlib import Path
from typing import Dict, Any
import yaml

# Base directory
BASE_DIR = Path("/Users/Shinji/Coding")
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def load_config(config_name: str) -> Dict[str, Any]:
    """Load a YAML config file from the config directory."""
    config_path = CONFIG_DIR / f"{config_name}.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Config:
    """Global configuration singleton."""

    def __init__(self):
        self.system = load_config("system_config")
        self.strategy = load_config("strategy_config")
        self.broker = load_config("broker_config")

        # Default values
        self.mode = self.system.get("mode", "backtest")
        self.log_level = self.system.get("log_level", "INFO")
        self.data_dir = DATA_DIR
        self.logs_dir = LOGS_DIR

    def reload(self):
        """Reload all configs."""
        self.system = load_config("system_config")
        self.strategy = load_config("strategy_config")
        self.broker = load_config("broker_config")


# Global config instance
config = Config()
