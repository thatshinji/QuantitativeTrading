"""
策略引擎（Strategy Engine）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
负责策略的执行和调度，是回测/实盘的核心调度器。

职责：
1. 管理策略实例的生命周期（初始化 → 运行 → 结束）
2. 向策略推送市场数据（K线、Tick）
3. 收集策略产生的信号，发送给执行层
4. 处理成交回报，更新策略持仓状态

与各模块的关系：
    DataEngine ──推送数据──▶ StrategyEngine ──产生信号──▶ ExecutionEngine
                                │
                                └── 回调策略的 on_bar / on_tick / on_fill

回测模式 vs 实盘模式：
- 回测模式：BacktestEngine 继承 StrategyEngine，数据从历史数据库读取
- 实盘模式：直接使用 StrategyEngine，数据从 DataEngine 实时推送
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, date
from dataclasses import dataclass, field

from quant_trading.data.models.market_data import BarData, Signal, FillData, Position
from quant_trading.strategies.base_strategy import BaseStrategy
from quant_trading.utils.logger import get_logger

logger = get_logger("StrategyEngine")


@dataclass
class StrategyContext:
    """
    策略执行上下文
    在策略运行期间共享，包含账户信息、配置、持仓状态等。
    策略通过 context 获取所需信息，不需要自己维护状态。
    """
    # 账户信息
    cash: float = 1000000.0           # 可用资金（元）
    initial_cash: float = 1000000.0  # 初始资金

    # 持仓状态 {symbol: Position}
    positions: Dict[str, Position] = field(default_factory=dict)

    # 配置参数
    config: Dict[str, Any] = field(default_factory=dict)

    # 当前时间（回测时为当前K线时间，实盘时为真实时间）
    current_time: Optional[datetime] = None
    current_date: Optional[date] = None

    def get_position(self, symbol: str) -> Position:
        """获取某股票的持仓，不存在则返回空仓"""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def get_position_size(self, symbol: str) -> int:
        """获取某股票的持仓数量"""
        return self.get_position(symbol).quantity

    def get_position_ratio(self, symbol: str) -> float:
        """获取某股票的持仓占比（市值/总资产）"""
        pos = self.get_position(symbol)
        total_value = self.total_assets
        if total_value == 0:
            return 0.0
        return (pos.quantity * pos.avg_cost) / total_value

    @property
    def total_assets(self) -> float:
        """总资产 = 现金 + 所有持仓市值"""
        positions_value = sum(
            pos.quantity * pos.avg_cost
            for pos in self.positions.values()
        )
        return self.cash + positions_value

    @property
    def total_pnl(self) -> float:
        """总盈亏（元）"""
        return self.total_assets - self.initial_cash

    @property
    def total_pnl_ratio(self) -> float:
        """总盈亏比例"""
        if self.initial_cash == 0:
            return 0.0
        return self.total_pnl / self.initial_cash


class StrategyEngine:
    """
    策略引擎

    管理策略的运行，负责数据推送和信号收集。
    支持单策略和多策略运行。

    使用方式：

    1. 初始化
       engine = StrategyEngine(initial_cash=1000000)
       engine.load_strategy(MyStrategy, params={...})

    2. 推送K线（回测或实盘）
       for bar in bars:
           signals = engine.on_bar(bar)

    3. 处理成交回报
       engine.on_fill(fill)

    4. 获取当前状态
       context = engine.get_context()
       print(f"总资产: {context.total_assets}")
    """

    def __init__(
        self,
        initial_cash: float = 1000000.0,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化策略引擎

        Args:
            initial_cash: 初始资金（元）
            config: 全局配置
        """
        self.strategies: List[BaseStrategy] = []  # 加载的策略列表
        self.context = StrategyContext(
            cash=initial_cash,
            initial_cash=initial_cash,
            config=config or {},
        )
        self._bar_count = 0  # 已处理的K线数量

        logger.info(f"策略引擎初始化完成，初始资金: {initial_cash}")

    def load_strategy(
        self,
        strategy_class: type,
        params: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
    ) -> BaseStrategy:
        """
        加载一个策略实例

        Args:
            strategy_class: 策略类（必须是 BaseStrategy 的子类）
            params: 策略参数
            name: 策略名称，默认使用类名

        Returns:
            策略实例

        示例：
            engine.load_strategy(MACDStrategy, params={"fast": 12, "slow": 26})
        """
        # 创建策略实例
        strategy = strategy_class(params=params)
        strategy.name = name or strategy.name

        # 调用策略初始化
        strategy.on_init(self.context)

        self.strategies.append(strategy)
        logger.info(f"策略加载: {strategy.name}，参数: {strategy.params}")

        return strategy

    def on_bar(self, bar: BarData) -> List[Signal]:
        """
        当收到一根K线时调用（核心方法）

        遍历所有策略，将K线推送给每个策略，
        收集策略返回的信号。

        Args:
            bar: 当前K线数据

        Returns:
            产生的信号列表
        """
        self._bar_count += 1

        # 更新上下文时间
        self.context.current_time = bar.timestamp
        self.context.current_date = bar.timestamp.date() if isinstance(bar.timestamp, datetime) else bar.timestamp

        all_signals: List[Signal] = []

        for strategy in self.strategies:
            try:
                # 调用策略的 on_bar
                signal = strategy.on_bar(self.context, bar)

                if signal is not None:
                    # 给信号打上时间戳（如果没有的话）
                    if signal.timestamp is None:
                        signal.timestamp = bar.timestamp
                    all_signals.append(signal)

                    logger.debug(
                        f"策略 {strategy.name} 产生信号: "
                        f"{'买入' if signal.direction > 0 else '卖出'} "
                        f"{signal.symbol} @{signal.price} "
                        f"(置信度: {signal.confidence:.2f})"
                    )

            except Exception as e:
                logger.error(f"策略 {strategy.name} 执行出错: {e}")

        # 每100根K线打印一次状态
        if self._bar_count % 100 == 0:
            logger.info(
                f"已处理 {self._bar_count} 根K线，"
                f"当前资产: {self.context.total_assets:.2f}，"
                f"盈亏: {self.context.total_pnl:.2f} ({self.context.total_pnl_ratio:.2%})"
            )

        return all_signals

    def on_tick(self, tick) -> List[Signal]:
        """
        当收到Tick数据时调用（用于高频策略）

        Args:
            tick: Tick数据

        Returns:
            产生的信号列表
        """
        all_signals: List[Signal] = []

        for strategy in self.strategies:
            try:
                signal = strategy.on_tick(self.context, tick)
                if signal is not None:
                    all_signals.append(signal)
            except Exception as e:
                logger.error(f"策略 {strategy.name} Tick处理出错: {e}")

        return all_signals

    def on_fill(self, fill: FillData):
        """
        当成交时调用（更新持仓状态）

        Args:
            fill: 成交数据
        """
        pos = self.context.get_position(fill.symbol)

        if fill.direction > 0:
            # 买入：增加持仓
            pos.update_cost(fill.quantity, fill.price, direction=1)
            logger.info(
                f"买入成交: {fill.symbol} {fill.quantity}股 @{fill.price}，"
                f"持仓: {pos.quantity}股，均价: {pos.avg_cost:.3f}"
            )
        else:
            # 卖出：减少持仓
            pos.update_cost(fill.quantity, fill.price, direction=-1)
            logger.info(
                f"卖出成交: {fill.symbol} {fill.quantity}股 @{fill.price}，"
                f"持仓: {pos.quantity}股"
            )

        # 通知所有策略
        for strategy in self.strategies:
            try:
                strategy.on_fill(self.context, fill)
            except Exception as e:
                logger.error(f"策略 {strategy.name} 成交回报处理出错: {e}")

    def on_schedule(self, trigger_time: datetime):
        """
        定时触发（每日收盘等）

        Args:
            trigger_time: 触发时间
        """
        self.context.current_time = trigger_time
        self.context.current_date = trigger_time.date()

        for strategy in self.strategies:
            try:
                strategy.on_schedule(self.context, trigger_time.date())
            except Exception as e:
                logger.error(f"策略 {strategy.name} 定时触发出错: {e}")

    def get_context(self) -> StrategyContext:
        """获取当前策略上下文"""
        return self.context

    def get_positions(self) -> Dict[str, Position]:
        """获取所有持仓"""
        return self.context.positions

    def get_signal_stats(self) -> Dict[str, Any]:
        """获取信号统计"""
        return {
            "strategy_count": len(self.strategies),
            "bars_processed": self._bar_count,
            "strategy_names": [s.name for s in self.strategies],
        }

    def __repr__(self) -> str:
        return (
            f"<StrategyEngine "
            f"strategies={len(self.strategies)} "
            f"bars={self._bar_count} "
            f"cash={self.context.cash:.2f}>"
        )
