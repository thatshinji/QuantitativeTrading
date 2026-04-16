import sys
import os
from datetime import date
from loguru import logger

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from quant_trading.core import BacktestEngine, BacktestConfig
from quant_trading.data import SQLiteStorage
from quant_trading.strategies.example import MACDCrossStrategy

def main():
    # 配置回测参数
    config = BacktestConfig(
        initial_cash=1000000.0,
        commission_rate=0.0003,
    )
    
    logger.info("初始化回测引擎...")
    engine = BacktestEngine(config=config)
    storage = SQLiteStorage()
    
    symbol = "601899.SH"
    start_date = date(2024, 1, 2)
    end_date = date(2024, 12, 31)
    
    logger.info(f"加载 {symbol} 历史数据 ({start_date} 到 {end_date})...")
    engine.load_data_from_storage(
        symbol=symbol,
        storage=storage,
        start_date=start_date,
        end_date=end_date
    )
    
    logger.info("设置交易策略: MACD交叉策略")
    # 设置策略并配置参数
    engine.set_strategy(MACDCrossStrategy, params={"fast_period": 12, "slow_period": 26, "signal_period": 9})
    
    logger.info("开始执行回测...")
    result = engine.run()
    
    print("\n" + "="*50)
    print("回测结果摘要:")
    print("="*50)
    print(result.summary())
    
    # 打印部分交易记录
    print("\n最近 5 笔交易记录:")
    for trade in result.trades[-5:]:
        print(f"[{trade.timestamp}] {trade.direction} {trade.symbol} 数量: {trade.quantity} 价格: {trade.price:.2f} 手续费: {trade.commission:.2f}")

if __name__ == "__main__":
    main()
