"""
数据源提供者（Providers）包
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
负责从不同数据源获取市场数据，目前支持：
- 长桥（Longbridge）：实时行情、历史K线、财务数据等

每个数据源对应一个 Provider 类，统一接口方便切换。
"""

from quant_trading.data.providers.longbridge_provider import LongbridgeProvider

__all__ = ["LongbridgeProvider"]
