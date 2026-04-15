"""
回测引擎（Backtest Engine）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
使用历史数据模拟策略执行，评估策略表现。

核心设计：
- 模拟撮合：按K线收盘价成交（简化模型，不考虑滑点）
- 风控前置：每笔下单前检查仓位和资金限制
- 多空支持：支持做多（long）和做空（short）信号
- 性能评估：计算年化收益率、夏普比率、最大回撤等指标

回测流程：
    1. 加载历史数据（从 SQLite 或 CSV）
    2. 设置策略和初始资金
    3. 按时间顺序遍历K线
    4. 每根K线：推送数据给策略 → 收集信号 → 风控审核 → 模拟成交
    5. 生成回测报告

注意：
- 回测结果仅供参考，实盘会有滑点、流动性、滑价等差异
- 历史表现不代表未来收益
"""

from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
import copy

from quant_trading.data.models.market_data import BarData, Signal, FillData, Order, Position
from quant_trading.core.strategy_engine import StrategyEngine, StrategyContext
from quant_trading.data.storage import SQLiteStorage
from quant_trading.utils.logger import get_logger

logger = get_logger("BacktestEngine")


@dataclass
class BacktestConfig:
    """回测配置"""
    initial_cash: float = 1000000.0       # 初始资金
    commission_rate: float = 0.0003      # 手续费率（默认万3）
    slippage_rate: float = 0.0           # 滑点率（默认0）
    margin_rate: float = 1.0             # 保证金率（1=全款，0.1=10%保证金）
    max_position_per_stock: float = 0.2  # 单股最大持仓比例
    max_total_position: float = 1.0      # 最大总持仓比例
    stop_loss_pct: float = 0.0           # 止损比例（0=不设置）
    stop_profit_pct: float = 0.0         # 止盈比例（0=不设置）


@dataclass
class BacktestResult:
    """回测结果"""
    # 基本信息
    symbol: str = ""
    strategy_name: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    bars_count: int = 0

    # 收益指标
    initial_cash: float = 0.0
    final_assets: float = 0.0
    total_return: float = 0.0            # 总收益率
    total_return_pct: float = 0.0         # 总收益率百分比
    annualized_return: float = 0.0        # 年化收益率
    annualized_volatility: float = 0.0    # 年化波动率

    # 风险指标
    max_drawdown: float = 0.0           # 最大回撤（元）
    max_drawdown_pct: float = 0.0       # 最大回撤（%）
    sharpe_ratio: float = 0.0            # 夏普比率
    sortino_ratio: float = 0.0           # 索提诺比率
    calmar_ratio: float = 0.0            # 卡玛比率

    # 交易统计
    total_trades: int = 0                # 总交易次数
    win_rate: float = 0.0               # 胜率
    avg_profit: float = 0.0             # 平均盈利（元）
    avg_loss: float = 0.0                # 平均亏损（元）
    profit_loss_ratio: float = 0.0       # 盈亏比

    # 持仓统计
    long_positions: int = 0              # 多头持仓次数
    short_positions: int = 0             # 空头持仓次数

    # 每日净值
    daily_nav: List[Dict[str, Any]] = field(default_factory=list)

    # 交易明细
    trades: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        """返回摘要字符串"""
        return f"""
========== 回测报告 ==========
标的: {self.symbol}
策略: {self.strategy_name}
时间: {self.start_date} ~ {self.end_date}
K线数: {self.bars_count}
------------------------------
初始资金: {self.initial_cash:,.2f}
最终资产: {self.final_assets:,.2f}
总收益率: {self.total_return_pct:.2%}
年化收益率: {self.annualized_return:.2%}
年化波动率: {self.annualized_volatility:.2%}
------------------------------
最大回撤: {self.max_drawdown_pct:.2%} ({self.max_drawdown:,.2f}元)
夏普比率: {self.sharpe_ratio:.2f}
卡玛比率: {self.calmar_ratio:.2f}
------------------------------
总交易次数: {self.total_trades}
胜率: {self.win_rate:.2%}
盈亏比: {self.profit_loss_ratio:.2f}
=============================="""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于导出）"""
        return {
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "start_date": str(self.start_date),
            "end_date": str(self.end_date),
            "bars_count": self.bars_count,
            "initial_cash": self.initial_cash,
            "final_assets": self.final_assets,
            "total_return_pct": self.total_return_pct,
            "annualized_return": self.annualized_return,
            "annualized_volatility": self.annualized_volatility,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "profit_loss_ratio": self.profit_loss_ratio,
        }


class BacktestEngine:
    """
    回测引擎

    使用历史数据模拟策略执行，支持：
    - 单股票回测
    - 多策略同时回测（各自独立持仓）
    - 自定义风控规则

    使用方式：

    1. 创建回测引擎
       engine = BacktestEngine(config=BacktestConfig(initial_cash=1000000))

    2. 设置数据源
       engine.load_data_from_storage("601899.SH", start_date=date(2024,1,1))
       # 或
       engine.load_data(bars)  # 直接传入 BarData 列表

    3. 设置策略
       engine.set_strategy(MACDStrategy, params={"fast": 12, "slow": 26})

    4. 运行回测
       result = engine.run()

    5. 查看结果
       print(result.summary())
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        """
        初始化回测引擎

        Args:
            config: 回测配置，为 None 则使用默认配置
        """
        self.config = config or BacktestConfig()
        self.strategy_class: Optional[type] = None
        self.strategy_params: Dict[str, Any] = {}
        self._bars: List[BarData] = []
        self._symbol: str = ""

        # 内部状态
        self._strategy_engine: Optional[StrategyEngine] = None
        self._pending_orders: List[Order] = []   # 待成交订单
        self._trade_history: List[FillData] = []  # 成交历史
        self._daily_records: List[Dict[str, Any]] = []  # 每日净值记录

        logger.info(f"回测引擎初始化，初始资金: {self.config.initial_cash}")

    def load_data(
        self,
        symbol: str,
        bars: List[BarData],
    ):
        """
        加载历史K线数据

        Args:
            symbol: 股票代码
            bars: K线数据列表（按时间正序）
        """
        self._symbol = symbol
        self._bars = sorted(bars, key=lambda x: x.timestamp)
        logger.info(f"加载数据: {symbol}，共 {len(bars)} 根K线")

        if bars:
            logger.info(f"  时间范围: {bars[0].timestamp.date()} ~ {bars[-1].timestamp.date()}")

    def load_data_from_storage(
        self,
        symbol: str,
        storage: SQLiteStorage,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        period: str = "1d",
    ):
        """
        从 SQLite 存储加载数据

        Args:
            symbol: 股票代码
            storage: SQLiteStorage 实例
            start_date: 开始日期
            end_date: 结束日期
            period: 周期
        """
        bars = storage.load_bars(
            symbol,
            start_date=start_date,
            end_date=end_date,
            period=period,
        )
        self.load_data(symbol, bars)

    def set_strategy(
        self,
        strategy_class: type,
        params: Optional[Dict[str, Any]] = None,
    ):
        """
        设置回测使用的策略

        Args:
            strategy_class: 策略类
            params: 策略参数
        """
        self.strategy_class = strategy_class
        self.strategy_params = params or {}
        logger.info(f"策略设置: {strategy_class.__name__}，参数: {self.strategy_params}")

    def run(self) -> BacktestResult:
        """
        运行回测

        核心逻辑：
        1. 初始化策略引擎和策略实例
        2. 按时间顺序遍历K线
        3. 每根K线：
           - 更新持仓的浮动盈亏
           - 推送K线给策略，获取信号
           - 对信号进行风控检查
           - 执行模拟成交
           - 记录每日净值
        4. 生成回测报告

        Returns:
            BacktestResult 回测结果
        """
        if not self._bars:
            raise ValueError("请先加载数据（调用 load_data 或 load_data_from_storage）")
        if self.strategy_class is None:
            raise ValueError("请先设置策略（调用 set_strategy）")

        logger.info("=" * 50)
        logger.info("开始回测...")
        logger.info("=" * 50)

        # 初始化策略引擎
        self._strategy_engine = StrategyEngine(
            initial_cash=self.config.initial_cash,
        )
        self._strategy_engine.load_strategy(
            self.strategy_class,
            params=self.strategy_params,
            name=self.strategy_class.__name__,
        )

        # 重置内部状态
        self._pending_orders = []
        self._trade_history = []
        self._daily_records = []

        # 记录每日资产（用于计算波动率和回撤）
        daily_values: List[float] = []  # 每日收盘后的总资产

        bars_processed = 0
        current_date: Optional[date] = None

        for bar in self._bars:
            bars_processed += 1

            # 更新浮动盈亏（按当前收盘价计算）
            self._update_unrealized_pnl(bar.close)

            # 记录每日净值（只在日期变化时记录）
            if bar.timestamp.date() != current_date:
                current_date = bar.timestamp.date()
                self._record_daily_nav(bar, current_date)

            # === 推送K线给策略，获取信号 ===
            signals = self._strategy_engine.on_bar(bar)

            # === 处理信号 → 下单 → 模拟成交 ===
            for signal in signals:
                self._process_signal(signal, bar)

            # === 模拟订单成交（简化为收盘价立即成交）===
            self._fill_pending_orders(bar)

            # === 处理未成交订单（取消）===
            # 对于隔夜未成交的订单，取消之（不复权）
            for order in self._pending_orders[:]:
                if order.symbol != bar.symbol:
                    order.status = "CANCELLED"
                    self._pending_orders.remove(order)

            # 每500根K线打印进度
            if bars_processed % 500 == 0:
                ctx = self._strategy_engine.get_context()
                logger.info(
                    f"进度: {bars_processed}/{len(self._bars)} "
                    f"日期: {bar.timestamp.date()} "
                    f"资产: {ctx.total_assets:,.2f}"
                )

        # === 回测结束，生成报告 ===
        result = self._generate_result(bars_processed)

        logger.info("=" * 50)
        logger.info("回测完成")
        logger.info("=" * 50)
        logger.info(result.summary())

        return result

    def _update_unrealized_pnl(self, current_price: float):
        """
        更新所有持仓的浮动盈亏

        Args:
            current_price: 当前价格（用于计算市值）
        """
        ctx = self._strategy_engine.get_context()
        for symbol, pos in ctx.positions.items():
            if pos.quantity > 0:
                pos.unrealized_pnl = (current_price - pos.avg_cost) * pos.quantity

    def _record_daily_nav(self, bar: BarData, record_date: date):
        """
        记录每日净值

        Args:
            bar: 当日最后一根K线
            record_date: 日期
        """
        ctx = self._strategy_engine.get_context()
        total_value = ctx.total_assets

        self._daily_records.append({
            "date": record_date,
            "close": bar.close,
            "total_value": total_value,
            "cash": ctx.cash,
            "positions_value": total_value - ctx.cash,
        })

    def _process_signal(self, signal: Signal, bar: BarData):
        """
        处理信号：风控检查 → 下单

        signal.size 的含义：资金使用比例（0.0 ~ 1.0），即使用总资产的 signal.size 倍资金
        例如：signal.size=1.0 表示使用 100% 总资产，signal.size=0.3 表示使用 30% 总资产

        Args:
            signal: 信号
            bar: 当前K线
        """
        ctx = self._strategy_engine.get_context()
        pos = ctx.get_position(signal.symbol)
        total_value = ctx.total_assets

        # === 计算实际交易金额 ===
        # signal.size 是资金比例，乘以总资产得到实际交易金额
        trade_value = signal.size * total_value  # 计划投入的资金
        target_quantity = int(trade_value / bar.close / 100) * 100  # 按100股取整

        if target_quantity < 100:
            logger.debug(f"风控拦截: 交易股数 {target_quantity} < 最低100股")
            return

        # === 风控检查 ===
        # 1. 仓位比例检查（signal.size 作为目标持仓比例）
        current_ratio = ctx.get_position_ratio(signal.symbol)

        if signal.direction > 0:  # 买入
            # 裁剪到风控上限（而不是直接拒绝）
            allowed_size = self.config.max_position_per_stock - current_ratio
            executed_size = min(signal.size, max(0, allowed_size))

            if executed_size <= 0:
                logger.debug(f"风控拦截: 仓位已满")
                return

            # 2. 总仓位检查
            total_position_value = sum(
                p.quantity * p.avg_cost for p in ctx.positions.values()
            )
            current_total_ratio = total_position_value / total_value if total_value > 0 else 0
            max_total_allowed = self.config.max_total_position - current_total_ratio
            executed_size = min(executed_size, max(0, max_total_allowed))

            if executed_size <= 0:
                logger.debug(f"风控拦截: 总仓位已满")
                return

            # 3. 资金检查（买入时）
            trade_value = executed_size * total_value
            required_cash = trade_value * (1 + self.config.commission_rate)
            if ctx.cash < required_cash:
                logger.debug(f"风控拦截: 资金不足，需要 {required_cash:.2f}，可用 {ctx.cash:.2f}")
                return

            # 4. 重新计算交易数量（用裁剪后的 executed_size）
            trade_value = executed_size * total_value
            target_quantity = int(trade_value / bar.close / 100) * 100

            if target_quantity < 100:
                logger.debug(f"风控拦截: 裁剪后股数不足 {target_quantity} < 100")
                return

            signal.size = executed_size  # 修改信号（用于生成订单）

        # === 生成订单 ===
        order = Order(
            order_id=f"BT_{bar.timestamp.strftime('%Y%m%d%H%M%S')}_{signal.symbol}",
            symbol=signal.symbol,
            direction=signal.direction,
            price=bar.close,  # 以收盘价成交
            quantity=target_quantity,
            order_type="MARKET",
            status="PENDING",
            created_at=bar.timestamp,
        )

        self._pending_orders.append(order)
        logger.debug(f"下单: {'买入' if order.direction > 0 else '卖出'} {order.symbol} {order.quantity}股 @{order.price}")

    def _fill_pending_orders(self, bar: BarData):
        """
        模拟订单成交（以收盘价立即成交）

        Args:
            bar: 当前K线
        """
        if not self._pending_orders:
            return

        ctx = self._strategy_engine.get_context()
        filled_orders = []

        for order in self._pending_orders:
            # 只处理当前股票的订单
            if order.symbol != bar.symbol:
                continue

            # 估算手续费
            commission = order.price * order.quantity * self.config.commission_rate

            if order.direction > 0:  # 买入
                cost = order.price * order.quantity + commission
                if ctx.cash < cost:
                    order.status = "REJECTED"
                    logger.debug(f"订单拒绝(资金不足): {order.symbol} 需要 {cost:.2f}，可用 {ctx.cash:.2f}")
                    continue

                ctx.cash -= cost
                order.status = "FILLED"

            else:  # 卖出
                pos = ctx.get_position(order.symbol)
                if pos.quantity < order.quantity:
                    order.status = "REJECTED"
                    logger.debug(f"订单拒绝(持仓不足): {order.symbol} 持有 {pos.quantity}，卖出 {order.quantity}")
                    continue

                revenue = order.price * order.quantity - commission
                ctx.cash += revenue
                order.status = "FILLED"

            order.avg_fill_price = bar.close  # 以收盘价成交
            order.filled_qty = order.quantity
            order.updated_at = bar.timestamp
            filled_orders.append(order)

            # 记录成交
            fill = FillData(
                order_id=order.order_id,
                symbol=order.symbol,
                direction=order.direction,
                price=bar.close,  # 模拟以收盘价成交
                quantity=order.quantity,
                timestamp=bar.timestamp,
                commission=commission,
            )
            self._trade_history.append(fill)

            # 更新策略引擎的持仓状态
            self._strategy_engine.on_fill(fill)

            logger.info(
                f"{'买入' if order.direction > 0 else '卖出'} 成交: "
                f"{order.symbol} {order.quantity}股 @{bar.close:.2f} "
                f"(手续费: {commission:.2f})"
            )

        # 移除已处理的订单
        for order in filled_orders:
            if order in self._pending_orders:
                self._pending_orders.remove(order)

    def _generate_result(self, bars_count: int) -> BacktestResult:
        """
        生成回测结果报告

        Args:
            bars_count: 处理的K线数量

        Returns:
            BacktestResult
        """
        ctx = self._strategy_engine.get_context()
        result = BacktestResult()

        result.symbol = self._symbol
        result.strategy_name = self.strategy_class.__name__
        result.bars_count = bars_count

        if self._bars:
            result.start_date = self._bars[0].timestamp.date()
            result.end_date = self._bars[-1].timestamp.date()

        result.initial_cash = self.config.initial_cash
        result.final_assets = ctx.total_assets

        # 收益率计算
        result.total_return = result.final_assets - result.initial_cash
        result.total_return_pct = result.total_return / result.initial_cash if result.initial_cash > 0 else 0

        # 年化收益率
        if result.start_date and result.end_date:
            days = (result.end_date - result.start_date).days
            if days > 0:
                years = days / 365.25
                result.annualized_return = ((1 + result.total_return_pct) ** (1 / years) - 1) if years > 0 else 0

        # === 计算波动率和夏普比率 ===
        if len(self._daily_records) > 1:
            # 计算每日收益率
            daily_returns = []
            for i in range(1, len(self._daily_records)):
                prev_value = self._daily_records[i - 1]["total_value"]
                curr_value = self._daily_records[i]["total_value"]
                if prev_value > 0:
                    daily_returns.append((curr_value - prev_value) / prev_value)

            if daily_returns:
                import statistics
                avg_return = statistics.mean(daily_returns)
                std_return = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0

                # 年化
                result.annualized_volatility = std_return * (252 ** 0.5)

                # 夏普比率（假设无风险利率为2%）
                risk_free_rate = 0.02
                if std_return > 0:
                    result.sharpe_ratio = (result.annualized_return - risk_free_rate) / result.annualized_volatility

        # === 最大回撤 ===
        peak = self.config.initial_cash
        max_drawdown = 0.0
        max_drawdown_pct = 0.0

        for record in self._daily_records:
            value = record["total_value"]
            if value > peak:
                peak = value
            drawdown = peak - value
            drawdown_pct = drawdown / peak if peak > 0 else 0

            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = drawdown_pct

        result.max_drawdown = max_drawdown
        result.max_drawdown_pct = max_drawdown_pct

        # 卡玛比率
        if result.max_drawdown > 0 and result.annualized_return > 0:
            result.calmar_ratio = result.annualized_return / (result.max_drawdown_pct)

        # === 交易统计 ===
        result.total_trades = len(self._trade_history)

        if self._trade_history:
            # 统计买卖对
            buy_count = sum(1 for f in self._trade_history if f.direction > 0)
            sell_count = sum(1 for f in self._trade_history if f.direction < 0)
            result.long_positions = buy_count
            result.short_positions = sell_count

            # 简化胜率计算（基于每笔交易的盈亏）
            profits = []
            losses = []
            for fill in self._trade_history:
                if fill.direction < 0:  # 卖出时计算盈亏
                    # 简化：假设对应买入价的差异
                    pnl = fill.price * fill.quantity - fill.commission
                    if pnl > 0:
                        profits.append(pnl)
                    else:
                        losses.append(abs(pnl))

            if profits or losses:
                win_count = len(profits)
                total_count = len(profits) + len(losses)
                result.win_rate = win_count / total_count if total_count > 0 else 0

                result.avg_profit = sum(profits) / len(profits) if profits else 0
                result.avg_loss = sum(losses) / len(losses) if losses else 0

                if result.avg_loss > 0:
                    result.profit_loss_ratio = result.avg_profit / result.avg_loss

        # 交易明细
        result.trades = [
            {
                "time": f.timestamp.strftime("%Y-%m-%d %H:%M"),
                "symbol": f.symbol,
                "direction": "买入" if f.direction > 0 else "卖出",
                "price": f.price,
                "quantity": f.quantity,
                "commission": f.commission,
            }
            for f in self._trade_history
        ]

        # 每日净值
        result.daily_nav = self._daily_records

        return result

    def __repr__(self) -> str:
        return f"<BacktestEngine symbol={self._symbol} bars={len(self._bars)}>"
