"""
MACD 交叉策略
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
经典的技术分析策略，基于 MACD 指标的黄金交叉和死亡交叉产生交易信号。

MACD 指标说明：
- DIF（快线）：EMA(close, fast_period) - EMA(close, slow_period)
- DEA（慢线）：EMA(DIF, signal_period)
- MACD 柱：DIF - DEA，当 DIF > DEA 时为红柱（多头），否则为绿柱（空头）

交易逻辑：
- 金叉买入：DIF 从下方穿越 DEA（空头转多头）
- 死叉卖出：DIF 从上方穿越 DEA（多头转空头）

参数说明：
- fast_period：快线周期，默认12
- slow_period：慢线周期，默认26
- signal_period：信号线周期，默认9
- buy_threshold：买入信号阈值，默认0（完全按金叉）
- sell_threshold：卖出信号阈值，默认0

注意事项：
- MACD 是趋势跟踪策略，适合趋势明显的市场
- 震荡行情中会有频繁假信号
- 建议结合其他指标（如成交量、趋势线）综合判断
"""

from typing import Optional, Dict, Any
from datetime import datetime

from quant_trading.strategies.base_strategy import BaseStrategy
from quant_trading.data.models.market_data import BarData, Signal


class MACDCrossStrategy(BaseStrategy):
    """
    MACD 交叉策略

    当 DIF 上穿 DEA 时买入（多头入场）
    当 DIF 下穿 DEA 时卖出（多头离场）

    使用示例：
        strategy = MACDCrossStrategy(params={
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
        })
    """

    name = "MACD交叉策略"
    version = "1.0.0"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        """
        初始化 MACD 策略

        Args:
            params: 参数字典，包含：
                - fast_period: 快线周期（默认12）
                - slow_period: 慢线周期（默认26）
                - signal_period: 信号线周期（默认9）
                - buy_threshold: 买入阈值（默认0）
                - sell_threshold: 卖出阈值（默认0）
        """
        super().__init__(params)

        self.fast_period = self.params.get("fast_period", 12)
        self.slow_period = self.params.get("slow_period", 26)
        self.signal_period = self.params.get("signal_period", 9)
        self.buy_threshold = self.params.get("buy_threshold", 0)
        self.sell_threshold = self.params.get("sell_threshold", 0)

        # 内部状态
        self.dif_values: list = []   # DIF 历史值
        self.dea_values: list = []   # DEA 历史值
        self.last_signal: int = 0    # 上一个信号方向（1=多头，-1=空头）
        self.position_open = False   # 当前是否有持仓

    def _init_indicators(self):
        """
        初始化技术指标

        策略初始化时调用，用于创建指标计算所需的数据结构。
        MACD 策略需要维护 DIF 和 DEA 的历史序列。
        """
        # 历史数据容器，用于计算移动平均
        self.dif_values = []
        self.dea_values = []
        self.last_signal = 0
        self.position_open = False

    def _calculate_ema(self, data: list, period: int, smoothing: float = 2.0) -> float:
        """
        计算指数移动平均（EMA）

        EMA_t = (Close_t * smoothing / (1 + period)) + EMA_{t-1} * (1 - smoothing / (1 + period))

        Args:
            data: 价格序列（最近的放在最后）
            period: 周期
            smoothing: 平滑系数，默认2

        Returns:
            最新 EMA 值
        """
        if len(data) < period:
            return sum(data) / len(data) if data else 0.0

        # 取最近 period 个数据计算 SMA 作为 EMA 的初始值
        sma = sum(data[-period:]) / period

        multiplier = smoothing / (1 + period)
        ema = sma

        # 从 period 位置开始，用 EMA 公式迭代
        for price in data[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))

        return ema

    def _calculate_macd(self, closes: list) -> tuple:
        """
        计算 MACD 指标

        Args:
            closes: 收盘价序列

        Returns:
            (dif, dea) 元组
        """
        if len(closes) < self.slow_period:
            return 0.0, 0.0

        # 计算快线和慢线的 EMA
        fast_ema = self._calculate_ema(closes, self.fast_period)
        slow_ema = self._calculate_ema(closes, self.slow_period)

        # DIF = 快线 EMA - 慢线 EMA
        dif = fast_ema - slow_ema

        # DEA = EMA(DIF, signal_period)
        # 为了计算 DEA，我们需要 DIF 的历史序列
        if len(self.dif_values) >= self.signal_period:
            dea = self._calculate_ema(self.dif_values, self.signal_period)
        else:
            dea = dif  # 数据不足时，DEA 初始值等于 DIF

        return dif, dea

    def on_bar(self, context: Dict[str, Any], bar: BarData) -> Optional[Signal]:
        """
        每根K线到来时执行的核心策略逻辑

        流程：
        1. 更新收盘价序列
        2. 计算 MACD 指标
        3. 判断是否产生金叉/死叉
        4. 生成交易信号

        Args:
            context: 策略上下文
            bar: 当前K线

        Returns:
            Signal 或 None（无信号）
        """
        # 获取历史收盘价（用于计算 EMA）
        # StrategyContext 是 dataclass，直接用属性访问
        # data_engine 存在 context._data_engine 里
        data_engine = getattr(context, '_data_engine', None)
        if data_engine:
            recent_bars = data_engine.get_bars(bar.symbol, n=self.slow_period + 10)
            closes = [b.close for b in recent_bars]
        else:
            # 备用：从 context 维护简单缓存
            if not hasattr(self, "_price_cache"):
                self._price_cache = []
            self._price_cache.append(bar.close)
            # 保持足够的历史数据
            max_need = self.slow_period + self.signal_period + 10
            if len(self._price_cache) > max_need:
                self._price_cache = self._price_cache[-max_need:]
            closes = self._price_cache

        if len(closes) < self.slow_period:
            # 数据不足，跳过
            return None

        # 计算当前 MACD
        dif, dea = self._calculate_macd(closes)

        # 更新 DIF 历史（用于计算 DEA）
        self.dif_values.append(dif)
        # 保持足够的历史
        max_dif_need = self.signal_period + 10
        if len(self.dif_values) > max_dif_need:
            self.dif_values = self.dif_values[-max_dif_need:]

        # 记录前一个 DIF/DEA 值
        if len(self.dif_values) >= 2:
            prev_dif = self.dif_values[-2]
            prev_dea = self.dea_values[-1] if self.dea_values else prev_dif
        else:
            prev_dif = dif
            prev_dea = dea

        # 更新 DEA 历史
        self.dea_values.append(dea)
        if len(self.dea_values) > max_dif_need:
            self.dea_values = self.dea_values[-max_dif_need:]

        # === 信号生成 ===
        signal = None

        # 金叉：DIF 从下方穿越 DEA（DIF 由负转正或从 DEA 下方穿到上方）
        if len(self.dif_values) >= 2:
            # 当前 DIF > DEA（多头）
            # 前一时刻 DIF < DEA（空头）
            cross_up = (dif > dea + self.buy_threshold) and (prev_dif <= prev_dea)

            # 死叉：DIF 从上方穿越 DEA（DIF 由正转负或从 DEA 上方穿到下方）
            cross_down = (dif < dea - self.sell_threshold) and (prev_dif >= prev_dea)

            # 获取当前持仓
            pos = context.get_position(bar.symbol)
            has_position = pos.quantity > 0

            if cross_up and not has_position:
                # 金叉买入
                signal = Signal(
                    symbol=bar.symbol,
                    direction=1,           # 买入
                    size=1.0,             # 满仓（后续风控可能调整）
                    price=bar.close,
                    reason=f"MACD金叉: DIF={dif:.4f} DEA={dea:.4f}",
                    confidence=0.7,
                )
                self.last_signal = 1
                self.position_open = True

            elif cross_down and has_position:
                # 死叉卖出
                signal = Signal(
                    symbol=bar.symbol,
                    direction=-1,          # 卖出
                    size=float(pos.quantity),
                    price=bar.close,
                    reason=f"MACD死叉: DIF={dif:.4f} DEA={dea:.4f}",
                    confidence=0.7,
                )
                self.last_signal = -1
                self.position_open = False

        return signal

    def __repr__(self) -> str:
        return f"<MACDCrossStrategy fast={self.fast_period} slow={self.slow_period} signal={self.signal_period}>"
