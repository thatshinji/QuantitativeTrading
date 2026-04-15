"""
均值回归策略
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
基于均值回归理论：当价格偏离均值较大幅度时，价格有回归均值的倾向。

交易逻辑：
- 当价格低于均值一定程度时，买入（价格被低估）
- 当价格高于均值一定程度时，卖出（价格被高估）

技术指标：
- 中轨：N日简单移动平均（SMA）或指数移动平均（EMA）
- 上轨：中轨 + K * N日标准差
- 下轨：中轨 - K * N日标准差

布林带策略：
- 价格触及下轨时买入
- 价格触及上轨时卖出

参数说明：
- period：计算均值的周期，默认20
- std_multiplier：标准差倍数，默认2.0（布林带2倍标准差）
- buy_threshold：买入阈值（价格偏离均值的程度）
- sell_threshold：卖出阈值

注意事项：
- 适用于震荡市场，在趋势行情中可能亏损
- 需要设置止损，因为价格可能长期偏离均值
- 建议在大盘震荡时使用，趋势明显时切换为趋势策略
"""

from typing import Optional, Dict, Any
from math import sqrt

from quant_trading.strategies.base_strategy import BaseStrategy
from quant_trading.data.models.market_data import BarData, Signal


class MeanReversionStrategy(BaseStrategy):
    """
    均值回归策略（布林带版本）

    当价格触及布林带下轨时买入，触及上轨时卖出。

    使用示例：
        strategy = MeanReversionStrategy(params={
            "period": 20,
            "std_multiplier": 2.0,
        })
    """

    name = "均值回归策略"
    version = "1.0.0"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        """
        初始化均值回归策略

        Args:
            params: 参数字典，包含：
                - period: 周期（默认20）
                - std_multiplier: 标准差倍数（默认2.0）
                - buy_threshold: 买入阈值（默认0，即价格触及下轨即买入）
                - sell_threshold: 卖出阈值（默认0）
        """
        super().__init__(params)

        self.period = self.params.get("period", 20)
        self.std_multiplier = self.params.get("std_multiplier", 2.0)
        self.buy_threshold = self.params.get("buy_threshold", 0)
        self.sell_threshold = self.params.get("sell_threshold", 0)

        # 内部状态
        self.price_cache: list = []  # 价格缓存

    def _init_indicators(self):
        """初始化指标"""
        self.price_cache = []

    def _calculate_bollinger_bands(self, closes: list) -> tuple:
        """
        计算布林带

        Args:
            closes: 收盘价序列

        Returns:
            (middle, upper, lower) 上轨、中轨、下轨
        """
        if len(closes) < self.period:
            return 0.0, 0.0, 0.0

        # 取最近 period 个价格
        recent = closes[-self.period:]

        # 中轨 = N日均线
        middle = sum(recent) / self.period

        # 标准差
        variance = sum((p - middle) ** 2 for p in recent) / self.period
        std = sqrt(variance)

        # 上轨 = 中轨 + K * 标准差
        upper = middle + self.std_multiplier * std

        # 下轨 = 中轨 - K * 标准差
        lower = middle - self.std_multiplier * std

        return middle, upper, lower

    def on_bar(self, context: Dict[str, Any], bar: BarData) -> Optional[Signal]:
        """
        每根K线到来时执行的核心策略逻辑

        流程：
        1. 更新价格序列
        2. 计算布林带
        3. 判断是否触及上轨/下轨
        4. 生成交易信号

        Args:
            context: 策略上下文
            bar: 当前K线

        Returns:
            Signal 或 None（无信号）
        """
        # 更新价格缓存
        self.price_cache.append(bar.close)

        # 保持足够的历史数据
        max_need = self.period + 10
        if len(self.price_cache) > max_need:
            self.price_cache = self.price_cache[-max_need:]

        if len(self.price_cache) < self.period:
            # 数据不足，跳过
            return None

        # 计算布林带
        middle, upper, lower = self._calculate_bollinger_bands(self.price_cache)

        # 获取当前持仓
        pos = context.get_position(bar.symbol)
        has_position = pos.quantity > 0

        signal = None

        # 价格触及下轨，且没有持仓 → 买入
        touch_lower = bar.low <= lower * (1 - self.buy_threshold)
        touch_upper = bar.high >= upper * (1 + self.sell_threshold)

        if touch_lower and not has_position:
            signal = Signal(
                symbol=bar.symbol,
                direction=1,             # 买入
                size=1.0,               # 满仓
                price=bar.close,
                reason=f"触及布林下轨: 价格={bar.close:.2f} 下轨={lower:.2f}",
                confidence=0.6,
            )

        elif touch_upper and has_position:
            signal = Signal(
                symbol=bar.symbol,
                direction=-1,            # 卖出
                size=float(pos.quantity),
                price=bar.close,
                reason=f"触及布林上轨: 价格={bar.close:.2f} 上轨={upper:.2f}",
                confidence=0.6,
            )

        # 额外风控：如果价格持续下跌，亏损超过10%也止损
        if has_position and pos.avg_cost > 0:
            loss_pct = (bar.close - pos.avg_cost) / pos.avg_cost
            if loss_pct <= -0.10:
                signal = Signal(
                    symbol=bar.symbol,
                    direction=-1,
                    size=float(pos.quantity),
                    price=bar.close,
                    reason=f"均值回归止损: 亏损 {loss_pct:.2%}",
                    confidence=0.9,
                )

        return signal

    def __repr__(self) -> str:
        return f"<MeanReversionStrategy period={self.period} std={self.std_multiplier}>"
