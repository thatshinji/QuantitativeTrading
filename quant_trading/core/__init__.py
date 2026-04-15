"""
Core 模块 - 核心引擎包
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
包含量化交易系统的五大核心引擎：

1. DataEngine（数据引擎）
   - 负责行情数据的接收、缓存和分发
   - 支持实时WebSocket订阅和历史数据查询

2. StrategyEngine（策略引擎）
   - 管理策略的生命周期
   - 向策略推送数据，收集信号
   - 支持多策略同时运行

3. ExecutionEngine（执行引擎）
   - 负责信号到订单的转换
   - 包含风控审核
   - 对接券商接口

4. RiskEngine（风控引擎）
   - 仓位控制、资金校验
   - 止损止盈监控
   - 风险敞口管理

5. BacktestEngine（回测引擎）
   - 使用历史数据模拟交易
   - 生成性能报告
   - 支持多种评估指标
"""

from quant_trading.core.data_engine import DataEngine
from quant_trading.core.strategy_engine import StrategyEngine, StrategyContext
from quant_trading.core.execution_engine import ExecutionEngine, ExecutionReport
from quant_trading.core.risk_engine import RiskEngine, RiskRule
from quant_trading.core.backtest_engine import BacktestEngine, BacktestConfig, BacktestResult

__all__ = [
    # 数据引擎
    "DataEngine",
    # 策略引擎
    "StrategyEngine",
    "StrategyContext",
    # 执行引擎
    "ExecutionEngine",
    "ExecutionReport",
    # 风控引擎
    "RiskEngine",
    "RiskRule",
    # 回测引擎
    "BacktestEngine",
    "BacktestConfig",
    "BacktestResult",
]
