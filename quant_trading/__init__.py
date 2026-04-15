"""
Quantitative Trading System
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A modular quantitative trading framework.
"""

__version__ = "0.1.0"
__author__ = "Ayanami Rei"

from quant_trading.core.data_engine import DataEngine
from quant_trading.core.strategy_engine import StrategyEngine
from quant_trading.core.backtest_engine import BacktestEngine
from quant_trading.core.execution_engine import ExecutionEngine
from quant_trading.core.risk_engine import RiskEngine

__all__ = [
    "DataEngine",
    "StrategyEngine",
    "BacktestEngine",
    "ExecutionEngine",
    "RiskEngine",
]
