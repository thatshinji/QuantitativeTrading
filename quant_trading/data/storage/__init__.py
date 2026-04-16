"""
数据存储层（Storage）包
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
负责将市场数据持久化到本地存储，支持：
- SQLite：轻量级关系数据库，适合存储K线、持仓等结构化数据
- CSV：适合导出和简单备份

存储设计原则：
- 所有数据以 symbol + timestamp 为主键，确保不重复
- 历史数据只增不改，当日数据可更新
- 支持按日期范围批量查询
"""

from quant_trading.data.storage.sqlite_storage import SQLiteStorage

__all__ = ["SQLiteStorage"]
