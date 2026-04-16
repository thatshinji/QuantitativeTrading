"""
数据层（Data）包
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
负责所有市场数据的获取、存储和管理。

包含三层架构：
1. providers/   - 数据源接口（长桥、问财等）
2. models/      - 数据结构定义
3. storage/     - 本地持久化存储

使用流程：
    provider = LongbridgeProvider()           # 1. 创建数据源
    bars = provider.get_candlesticks(...)    # 2. 获取数据
    storage = SQLiteStorage()                # 3. 创建存储
    storage.save_bars(symbol, bars)          # 4. 保存到本地
    loaded_bars = storage.load_bars(...)      # 5. 从本地读取
"""

from quant_trading.data.providers import LongbridgeProvider
from quant_trading.data.storage import SQLiteStorage
from quant_trading.data.models import BarData, TickData, Signal, Order, FillData, Position

__all__ = [
    "LongbridgeProvider",
    "SQLiteStorage",
    "BarData",
    "TickData",
    "Signal",
    "Order",
    "FillData",
    "Position",
]
