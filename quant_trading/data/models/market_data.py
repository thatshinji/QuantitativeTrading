"""
Market data models.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class BarData:
    """K线数据"""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: Optional[float] = None

    @property
    def date(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")

    @property
    def time(self) -> str:
        return self.timestamp.strftime("%H:%M:%S")


@dataclass
class TickData:
    """Tick 数据（逐笔）"""
    symbol: str
    timestamp: datetime
    last_price: float
    last_volume: float
    bid_price: float
    ask_price: float
    bid_volume: float
    ask_volume: float


@dataclass
class Signal:
    """交易信号"""
    symbol: str
    direction: int  # +1 买入, -1 卖出
    size: float     # 仓位比例 0.0 ~ 1.0
    price: float    # 预期价格
    reason: str     # 信号原因
    confidence: float  # 置信度 0.0 ~ 1.0
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class Order:
    """订单"""
    order_id: str
    symbol: str
    direction: int
    price: float
    quantity: int
    order_type: str = "MARKET"
    status: str = "PENDING"
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()


@dataclass
class FillData:
    """成交回报"""
    order_id: str
    symbol: str
    direction: int
    price: float
    quantity: int
    timestamp: datetime
    commission: float = 0.0


@dataclass
class Position:
    """持仓"""
    symbol: str
    quantity: int = 0
    avg_cost: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.avg_cost

    def update_cost(self, new_qty: int, new_price: float, direction: int):
        """更新持仓成本（加仓/减仓）"""
        if direction > 0:  # 买入
            total_cost = self.quantity * self.avg_cost + new_qty * new_price
            self.quantity += new_qty
            self.avg_cost = total_cost / self.quantity if self.quantity > 0 else 0.0
        else:  # 卖出
            self.quantity -= new_qty
            if self.quantity > 0:
                # 卖出不改变均价（先进先出简化版）
                pass
            else:
                self.avg_cost = 0.0
                self.quantity = 0
