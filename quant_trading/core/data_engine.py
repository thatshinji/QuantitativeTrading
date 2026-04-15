"""
Data Engine - handles all market data acquisition and storage.
"""

from datetime import datetime
from typing import Dict, List, Optional
from quant_trading.data.models.market_data import BarData, TickData


class DataEngine:
    """
    数据引擎：负责行情数据的采集、缓存、存储和分发
    """

    def __init__(self):
        self._bars_cache: Dict[str, List[BarData]] = {}  # symbol -> bar list
        self._tick_cache: Dict[str, TickData] = {}       # symbol -> latest tick
        self._subscribers: Dict[str, List] = {}           # symbol -> callback list

    def subscribe(self, symbol: str, callback):
        """订阅行情"""
        if symbol not in self._subscribers:
            self._subscribers[symbol] = []
        self._subscribers[symbol].append(callback)

    def unsubscribe(self, symbol: str, callback):
        """取消订阅"""
        if symbol in self._subscribers:
            self._subscribers[symbol].remove(callback)

    def update_bar(self, symbol: str, bar: BarData):
        """更新K线数据"""
        if symbol not in self._bars_cache:
            self._bars_cache[symbol] = []
        self._bars_cache[symbol].append(bar)

    def update_tick(self, symbol: str, tick: TickData):
        """更新Tick数据"""
        self._tick_cache[symbol] = tick
        # 通知订阅者
        if symbol in self._subscribers:
            for cb in self._subscribers[symbol]:
                cb(tick)

    def get_latest_bar(self, symbol: str) -> Optional[BarData]:
        """获取最新K线"""
        bars = self._bars_cache.get(symbol, [])
        return bars[-1] if bars else None

    def get_bars(self, symbol: str, n: int = 100) -> List[BarData]:
        """获取最近n根K线"""
        bars = self._bars_cache.get(symbol, [])
        return bars[-n:]

    def get_turnover(self, symbol: str) -> float:
        """获取最新成交额"""
        bar = self.get_latest_bar(symbol)
        return bar.turnover if bar else 0.0

    def get_latest_price(self, symbol: str) -> float:
        """获取最新价"""
        tick = self._tick_cache.get(symbol)
        if tick:
            return tick.last_price
        bar = self.get_latest_bar(symbol)
        return bar.close if bar else 0.0

    def load_historical_bars(self, symbol: str, bars: List[BarData]):
        """加载历史K线数据（回测用）"""
        self._bars_cache[symbol] = list(bars)

    def clear(self):
        """清空缓存"""
        self._bars_cache.clear()
        self._tick_cache.clear()
