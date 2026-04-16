"""
数据模型（Models）包
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
定义系统中使用的核心数据结构和类。

包含：
- market_data: 市场数据模型（K线、Tick、信号、订单、持仓等）
- fundamentals: 基本面数据模型（财报、指标等）[预留]

设计原则：
- 使用 dataclass 提供轻量、清晰的数据结构
- 所有字段有类型标注，方便 IDE 自动补全
- 包含基本的业务逻辑（如 Position.update_cost）
"""

from quant_trading.data.models.market_data import (
    BarData,          # K线数据
    TickData,         # Tick数据（逐笔）
    Signal,           # 交易信号
    Order,            # 订单
    FillData,         # 成交回报
    Position,         # 持仓
)

__all__ = [
    "BarData",
    "TickData",
    "Signal",
    "Order",
    "FillData",
    "Position",
]
