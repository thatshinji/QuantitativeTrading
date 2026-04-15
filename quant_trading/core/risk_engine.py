"""
风控引擎（Risk Engine）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
所有订单在下发前必须经过风控审核。

风控规则：
1. 仓位限制：单股持仓不超过总资产X%
2. 总仓位限制：所有持仓不超过总资产X%
3. 资金限制：买入金额不超过可用资金
4. 止损规则：持仓亏损超过X%自动触发平仓信号
5. 行业/板块限制：避免单一行业敞口过大

设计原则：
- 风控是独立的，可以单独使用
- 所有规则可配置，灵活调整
- 风控拦截时返回清晰的拒绝原因
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import copy

from quant_trading.data.models.market_data import Signal, Position
from quant_trading.utils.logger import get_logger

logger = get_logger("RiskEngine")


@dataclass
class RiskRule:
    """风控规则"""
    name: str                           # 规则名称
    enabled: bool = True               # 是否启用
    params: Dict[str, Any] = field(default_factory=dict)  # 规则参数


class RiskEngine:
    """
    风控引擎

    对每个信号进行风控检查，检查通过才允许下单。

    使用方式：

    1. 初始化（使用默认规则）
       risk = RiskEngine()

    2. 自定义规则参数
       risk.set_rule_params("max_position_per_stock", 0.15)  # 单股最大15%仓位

    3. 检查信号
       result = risk.check_signal(signal, current_price, positions, cash)
       if not result["passed"]:
           print(f"风控拦截: {result['reason']}")
    """

    # 默认风控参数
    DEFAULT_PARAMS = {
        "max_position_per_stock": 0.20,   # 单股最大持仓：20%
        "max_total_position": 0.80,        # 最大总仓位：80%
        "max_daily_loss": 0.02,            # 单日最大亏损：2%
        "stop_loss_pct": 0.05,             # 默认止损线：5%
        "stop_profit_pct": 0.15,           # 默认止盈线：15%
        "min_trade_value": 1000,           # 最小交易金额（元）
        "max_single_trade_value": 500000,  # 最大单笔交易金额（元）
    }

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        """
        初始化风控引擎

        Args:
            params: 风控参数，为 None 则使用默认参数
        """
        self.params = copy.copy(self.DEFAULT_PARAMS)
        if params:
            self.params.update(params)

        self.enabled = True
        logger.info(f"风控引擎初始化，参数: {self.params}")

    def set_rule_params(self, rule_name: str, value: Any):
        """
        修改某个规则的值

        Args:
            rule_name: 参数名
            value: 参数值
        """
        self.params[rule_name] = value
        logger.info(f"风控规则更新: {rule_name} = {value}")

    def check_signal(
        self,
        signal: Signal,
        current_price: float,
        positions: Dict[str, Position],
        cash: float,
        total_assets: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        检查信号是否通过风控（核心方法）

        检查项目：
        1. 信号有效性
        2. 仓位比例限制
        3. 总仓位限制
        4. 资金限制
        5. 交易金额限制

        Args:
            signal: 交易信号
            current_price: 当前价格
            positions: 当前持仓字典 {symbol: Position}
            cash: 可用资金
            total_assets: 总资产，用于计算仓位比例

        Returns:
            检查结果字典：
            {
                "passed": bool,       # 是否通过
                "reason": str,         # 拒绝原因（如果未通过）
                "warnings": list,     # 警告信息（不影响下单）
            }
        """
        result = {"passed": True, "reason": "", "warnings": []}

        if not self.enabled:
            return result

        # === 基本检查 ===
        if signal.direction == 0:
            result["passed"] = False
            result["reason"] = "信号方向无效（direction=0）"
            return result

        if signal.size <= 0:
            result["passed"] = False
            result["reason"] = "信号数量无效（size<=0）"
            return result

        # === 仓位比例检查 ===
        if total_assets and total_assets > 0:
            # 计算当前持仓市值
            current_position_value = sum(
                pos.quantity * pos.avg_cost
                for pos in positions.values()
            )
            current_total_ratio = current_position_value / total_assets

            # 计算这笔交易后的新仓位
            trade_value = signal.size * current_price  # 估算交易金额
            new_position_ratio = trade_value / total_assets

            if signal.direction > 0:  # 买入
                # 检查单股仓位
                pos = positions.get(signal.symbol)
                if pos and pos.quantity > 0:
                    current_stock_ratio = (pos.quantity * pos.avg_cost) / total_assets
                    new_stock_ratio = current_stock_ratio + new_position_ratio
                else:
                    new_stock_ratio = new_position_ratio

                if new_stock_ratio > self.params["max_position_per_stock"]:
                    result["passed"] = False
                    result["reason"] = (
                        f"单股仓位超限: {new_stock_ratio:.2%} > "
                        f"{self.params['max_position_per_stock']:.2%}"
                    )
                    return result

                # 检查总仓位
                new_total_ratio = current_total_ratio + new_position_ratio
                if new_total_ratio > self.params["max_total_position"]:
                    result["passed"] = False
                    result["reason"] = (
                        f"总仓位超限: {new_total_ratio:.2%} > "
                        f"{self.params['max_total_position']:.2%}"
                    )
                    return result

        # === 资金检查（买入时）===
        if signal.direction > 0:
            estimated_cost = signal.size * current_price
            commission = estimated_cost * 0.0003  # 预估手续费
            total_cost = estimated_cost + commission

            if total_cost > cash:
                result["passed"] = False
                result["reason"] = (
                    f"资金不足: 需要 {total_cost:.2f}，可用 {cash:.2f}"
                )
                return result

            # === 最小/最大交易金额检查 ===
            if estimated_cost < self.params["min_trade_value"]:
                result["passed"] = False
                result["reason"] = (
                    f"交易金额低于最小限制: {estimated_cost:.2f} < "
                    f"{self.params['min_trade_value']:.2f}"
                )
                return result

            if estimated_cost > self.params["max_single_trade_value"]:
                result["passed"] = False
                result["reason"] = (
                    f"交易金额超过最大限制: {estimated_cost:.2f} > "
                    f"{self.params['max_single_trade_value']:.2f}"
                )
                return result

        # === 止盈止损检查（持仓时）===
        pos = positions.get(signal.symbol)
        if pos and pos.quantity > 0:
            # 止损检查
            stop_loss = self.params["stop_loss_pct"]
            if stop_loss > 0:
                loss_pct = (pos.avg_cost - current_price) / pos.avg_cost
                if loss_pct >= stop_loss:
                    result["warnings"].append(
                        f"触及止损线: 亏损 {loss_pct:.2%} >= {stop_loss:.2%}"
                    )

            # 止盈检查
            stop_profit = self.params["stop_profit_pct"]
            if stop_profit > 0:
                profit_pct = (current_price - pos.avg_cost) / pos.avg_cost
                if profit_pct >= stop_profit:
                    result["warnings"].append(
                        f"触及止盈线: 盈利 {profit_pct:.2%} >= {stop_profit:.2%}"
                    )

        return result

    def check_stop_loss(
        self,
        symbol: str,
        current_price: float,
        positions: Dict[str, Position],
    ) -> Optional[Signal]:
        """
        检查是否触发止损（生成止损信号）

        Args:
            symbol: 股票代码
            current_price: 当前价格
            positions: 当前持仓

        Returns:
            如果触发止损，返回卖出信号；否则返回 None
        """
        pos = positions.get(symbol)
        if not pos or pos.quantity == 0:
            return None

        stop_loss = self.params["stop_loss_pct"]
        if stop_loss <= 0:
            return None

        loss_pct = (pos.avg_cost - current_price) / pos.avg_cost

        if loss_pct >= stop_loss:
            logger.warning(
                f"触发止损: {symbol} 亏损 {loss_pct:.2%}，当前价 {current_price}，成本 {pos.avg_cost:.3f}"
            )
            return Signal(
                symbol=symbol,
                direction=-1,  # 卖出
                size=float(pos.quantity),
                price=current_price,
                reason=f"止损触发: 亏损 {loss_pct:.2%}",
                confidence=1.0,
            )

        return None

    def check_stop_profit(
        self,
        symbol: str,
        current_price: float,
        positions: Dict[str, Position],
    ) -> Optional[Signal]:
        """
        检查是否触发止盈（生成止盈信号）

        Args:
            symbol: 股票代码
            current_price: 当前价格
            positions: 当前持仓

        Returns:
            如果触发止盈，返回卖出信号；否则返回 None
        """
        pos = positions.get(symbol)
        if not pos or pos.quantity == 0:
            return None

        stop_profit = self.params["stop_profit_pct"]
        if stop_profit <= 0:
            return None

        profit_pct = (current_price - pos.avg_cost) / pos.avg_cost

        if profit_pct >= stop_profit:
            logger.info(
                f"触发止盈: {symbol} 盈利 {profit_pct:.2%}，当前价 {current_price}，成本 {pos.avg_cost:.3f}"
            )
            return Signal(
                symbol=symbol,
                direction=-1,  # 卖出
                size=float(pos.quantity),
                price=current_price,
                reason=f"止盈触发: 盈利 {profit_pct:.2%}",
                confidence=1.0,
            )

        return None

    def get_position_risk(
        self,
        positions: Dict[str, Position],
        current_prices: Dict[str, float],
        total_assets: float,
    ) -> List[Dict[str, Any]]:
        """
        获取所有持仓的风险状况

        Args:
            positions: 持仓字典
            current_prices: 当前价格字典 {symbol: price}
            total_assets: 总资产

        Returns:
            风险列表，每项包含股票代码、持仓比例、盈亏状况等
        """
        risks = []

        for symbol, pos in positions.items():
            if pos.quantity == 0:
                continue

            current_price = current_prices.get(symbol, pos.avg_cost)
            position_value = pos.quantity * current_price
            position_ratio = position_value / total_assets if total_assets > 0 else 0

            unrealized_pnl = (current_price - pos.avg_cost) * pos.quantity
            unrealized_pnl_pct = (current_price - pos.avg_cost) / pos.avg_cost if pos.avg_cost > 0 else 0

            risk_level = "正常"
            if abs(unrealized_pnl_pct) >= self.params["stop_loss_pct"]:
                risk_level = "止损"
            elif abs(unrealized_pnl_pct) >= self.params["stop_loss_pct"] * 0.8:
                risk_level = "警戒"

            risks.append({
                "symbol": symbol,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "current_price": current_price,
                "position_value": position_value,
                "position_ratio": position_ratio,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "risk_level": risk_level,
            })

        return risks

    def __repr__(self) -> str:
        return f"<RiskEngine enabled={self.enabled} params={self.params}>"
