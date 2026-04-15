"""
示例策略包
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
提供几个简单策略作为参考，方便用户开发自己的策略。

包含：
- MACDCrossStrategy：MACD 金叉/死叉策略
- MeanReversionStrategy：均值回归策略

每个策略都有完整的中文注释，说明策略逻辑和参数含义。
"""

from quant_trading.strategies.example.macd_cross import MACDCrossStrategy
from quant_trading.strategies.example.mean_rev import MeanReversionStrategy

__all__ = ["MACDCrossStrategy", "MeanReversionStrategy"]
