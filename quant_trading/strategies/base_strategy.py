"""
Base strategy class - all user strategies inherit from this.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any
from quant_trading.data.models.market_data import BarData, Signal, FillData


class BaseStrategy(ABC):
    """策略基类，所有策略必须继承此类并实现核心方法"""

    name: str = "base_strategy"
    version: str = "0.1.0"

    def __init__(self, params: Dict[str, Any] = None):
        """
        策略初始化

        Args:
            params: 策略参数字典
        """
        self.params = params or {}
        self.context: Dict[str, Any] = {}  # 策略上下文，可自由使用
        self.initialized = False

    def on_init(self, context: Dict[str, Any]):
        """
        策略初始化回调
        在回测/实盘开始前调用，用于初始化指标等

        Args:
            context: 策略上下文（包含账户信息、配置等）
        """
        self.context = context
        self.initialized = True
        self._init_indicators()

    @abstractmethod
    def _init_indicators(self):
        """初始化技术指标 - 子类实现"""
        pass

    @abstractmethod
    def on_bar(self, context: Dict[str, Any], bar: BarData) -> Optional[Signal]:
        """
        K线闭合时调用（主要策略逻辑）

        Args:
            context: 策略上下文
            bar: 当前K线数据

        Returns:
            Signal 或 None（无信号）
        """
        pass

    def on_tick(self, context: Dict[str, Any], tick) -> Optional[Signal]:
        """
        Tick数据到达时调用（可选，用于高频策略）

        Args:
            context: 策略上下文
            tick: Tick数据

        Returns:
            Signal 或 None
        """
        return None

    def on_fill(self, context: Dict[str, Any], fill: FillData):
        """
        成交回报回调

        Args:
            context: 策略上下文
            fill: 成交数据
        """
        pass

    def on_schedule(self, context: Dict[str, Any], date: datetime):
        """
        定时回调（每日收盘等）

        Args:
            context: 策略上下文
            date: 当前日期
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}('{self.name}', v{self.version})>"
