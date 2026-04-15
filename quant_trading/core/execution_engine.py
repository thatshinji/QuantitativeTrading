"""
执行引擎（Execution Engine）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
负责订单的发送、成交回报处理和交易日志记录。

职责：
1. 接收策略产生的信号（Signal）
2. 进行风控审核（RiskEngine）
3. 向券商发送订单
4. 处理成交回报（Fill）
5. 更新持仓状态
6. 记录交易日志

订单执行流程：
    Signal → Risk Check → Order → Broker → Fill → Position Update → Log

支持三种模式：
- 回测模式（MockBroker）：模拟成交，不真实下单
- 模拟盘模式（PaperBroker）：模拟成交，但记录真实时间
- 实盘模式（RealBroker）：通过券商API真实下单
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field
import uuid

from quant_trading.data.models.market_data import Signal, Order, FillData, Position
from quant_trading.core.risk_engine import RiskEngine
from quant_trading.utils.logger import get_logger

logger = get_logger("ExecutionEngine")


@dataclass
class ExecutionReport:
    """执行报告：记录一次完整执行的的结果"""
    signal: Signal                      # 原始信号
    order: Optional[Order]              # 生成的订单（可能被风控拒绝）
    fill: Optional[FillData]            # 成交回报（可能为None）
    rejected: bool = False              # 是否被风控拒绝
    reject_reason: str = ""             # 拒绝原因
    timestamp: datetime = None         # 处理时间

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class ExecutionEngine:
    """
    执行引擎

    负责信号到成交的完整流程。
    内部包含风控引擎（RiskEngine），所有订单都必须通过风控。

    使用方式：

    1. 初始化
       engine = ExecutionEngine()

    2. 设置券商（模拟或实盘）
       engine.set_broker(MockBroker())  # 回测用
       # 或
       engine.set_broker(RealBroker(...))  # 实盘用

    3. 处理信号
       report = engine.execute_signal(signal, current_price)

    4. 查询状态
       orders = engine.get_open_orders()
       fills = engine.get_fills()
    """

    def __init__(self, risk_engine: Optional[RiskEngine] = None):
        """
        初始化执行引擎

        Args:
            risk_engine: 风控引擎实例，为 None 则使用默认风控
        """
        self.risk_engine = risk_engine or RiskEngine()
        self.broker = None  # 券商接口（Broker）

        # 内部状态
        self._orders: Dict[str, Order] = {}       # order_id -> Order
        self._fills: List[FillData] = []           # 成交历史
        self._pending_orders: List[Order] = []    # 待成交订单
        self._symbol_positions: Dict[str, Position] = {}  # symbol -> Position

        # 回调函数
        self._on_fill_callbacks: List[callable] = []

        logger.info("执行引擎初始化完成")

    def set_broker(self, broker):
        """
        设置券商

        Args:
            broker: Broker 实例（MockBroker / PaperBroker / RealBroker）
        """
        self.broker = broker
        logger.info(f"券商设置: {broker.__class__.__name__}")

    def on_fill_callback(self, callback: callable):
        """
        注册成交回调函数

        Args:
            callback: 回调函数，签名: on_fill(fill: FillData)

        用于实盘时，当成交后主动通知策略更新持仓。
        """
        self._on_fill_callbacks.append(callback)

    def execute_signal(
        self,
        signal: Signal,
        current_price: float,
        current_time: Optional[datetime] = None,
    ) -> ExecutionReport:
        """
        执行一个信号（核心方法）

        流程：信号 → 风控检查 → 生成订单 → 发送券商 → 模拟成交

        Args:
            signal: 交易信号
            current_price: 当前价格
            current_time: 当前时间

        Returns:
            ExecutionReport 执行报告
        """
        if current_time is None:
            current_time = datetime.now()

        report = ExecutionReport(signal=signal)

        # === 风控检查 ===
        check_result = self.risk_engine.check_signal(
            signal=signal,
            current_price=current_price,
            positions=self._symbol_positions,
            cash=self._get_available_cash(),
        )

        if not check_result["passed"]:
            report.rejected = True
            report.reject_reason = check_result["reason"]
            logger.debug(f"信号被风控拦截: {signal.symbol} {check_result['reason']}")
            return report

        # === 生成订单 ===
        order = Order(
            order_id=f"ORD_{uuid.uuid4().hex[:12].upper()}",
            symbol=signal.symbol,
            direction=signal.direction,
            price=current_price,
            quantity=self._signal_size_to_quantity(signal, current_price),
            order_type="MARKET",
            status="PENDING",
            created_at=current_time,
        )

        self._orders[order.order_id] = order
        self._pending_orders.append(order)

        logger.debug(f"订单已提交: {order.order_id} {signal.symbol} {order.quantity}股")

        # === 模拟成交（回测/模拟盘）===
        if self.broker is not None and hasattr(self.broker, "mock_fill"):
            # 模拟成交（回测模式）
            fill = self.broker.mock_fill(order, current_time)
            if fill:
                self._handle_fill(fill)
                report.fill = fill
                report.order = order
                order.status = "FILLED"

        return report

    def _get_available_cash(self) -> float:
        """获取可用资金（总现金 - 已冻结资金）"""
        # 简化版：实际应该从账户系统获取
        total_used = sum(
            o.price * o.quantity for o in self._pending_orders if o.direction > 0
        )
        # 实际可用资金需要从账户系统获取，这里返回0表示不限制
        return float("inf")

    def _signal_size_to_quantity(self, signal: Signal, price: float) -> int:
        """
        将信号的 size 转换为股数

        Args:
            signal: 信号
            price: 当前价格

        Returns:
            股数（整数）
        """
        if signal.size <= 1.0:
            # size 是比例（0.0 ~ 1.0），表示占总资产的比例
            # 这里需要总资产信息，简化处理用100股为单位
            return max(100, int(signal.size * 10000) // 100 * 100)
        else:
            # size 是具体股数
            return int(signal.size)

    def _handle_fill(self, fill: FillData):
        """
        处理成交回报

        Args:
            fill: 成交数据
        """
        self._fills.append(fill)

        # 更新持仓
        if fill.symbol not in self._symbol_positions:
            self._symbol_positions[fill.symbol] = Position(symbol=fill.symbol)

        pos = self._symbol_positions[fill.symbol]

        if fill.direction > 0:  # 买入
            pos.update_cost(fill.quantity, fill.price, direction=1)
        else:  # 卖出
            pos.update_cost(fill.quantity, fill.price, direction=-1)

        logger.info(
            f"成交: {'买入' if fill.direction > 0 else '卖出'} "
            f"{fill.symbol} {fill.quantity}股 @{fill.price}"
        )

        # 回调
        for callback in self._on_fill_callbacks:
            try:
                callback(fill)
            except Exception as e:
                logger.error(f"成交回调执行失败: {e}")

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        获取未成交订单

        Args:
            symbol: 过滤条件，为空则返回所有

        Returns:
            订单列表
        """
        if symbol:
            return [o for o in self._pending_orders if o.symbol == symbol]
        return list(self._pending_orders)

    def get_fills(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[FillData]:
        """
        获取成交历史

        Args:
            symbol: 过滤条件
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            成交列表
        """
        fills = self._fills

        if symbol:
            fills = [f for f in fills if f.symbol == symbol]
        if start_time:
            fills = [f for f in fills if f.timestamp >= start_time]
        if end_time:
            fills = [f for f in fills if f.timestamp <= end_time]

        return fills

    def get_position(self, symbol: str) -> Optional[Position]:
        """获取某股票的持仓"""
        return self._symbol_positions.get(symbol)

    def get_all_positions(self) -> Dict[str, Position]:
        """获取所有持仓"""
        return self._symbol_positions

    def cancel_order(self, order_id: str) -> bool:
        """
        取消订单

        Args:
            order_id: 订单ID

        Returns:
            是否成功取消
        """
        if order_id in self._pending_orders:
            order = self._orders[order_id]
            order.status = "CANCELLED"
            self._pending_orders = [o for o in self._pending_orders if o.order_id != order_id]
            logger.info(f"订单已取消: {order_id}")
            return True
        return False

    def cancel_all_orders(self, symbol: Optional[str] = None):
        """
        取消所有待成交订单

        Args:
            symbol: 为空则取消所有，否则只取消指定股票
        """
        if symbol:
            to_cancel = [o for o in self._pending_orders if o.symbol == symbol]
        else:
            to_cancel = self._pending_orders[:]

        for order in to_cancel:
            order.status = "CANCELLED"
            self._orders[order.order_id].status = "CANCELLED"

        self._pending_orders = [
            o for o in self._pending_orders
            if (symbol and o.symbol != symbol)
        ]

        logger.info(f"已取消 {len(to_cancel)} 个订单")

    def __repr__(self) -> str:
        return (
            f"<ExecutionEngine "
            f"pending_orders={len(self._pending_orders)} "
            f"fills={len(self._fills)} "
            f"broker={self.broker.__class__.__name__ if self.broker else 'None'}>"
        )
