"""
历史数据下载脚本
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
用于从长桥下载历史K线数据并存储到本地SQLite数据库。

功能：
1. 支持按股票代码下载日线/分钟线数据
2. 支持断点续传（跳过已有数据）
3. 支持批量下载多个股票
4. 自动处理复权（前复权数据更适合技术分析）

使用方式：
    # 下载单只股票日线
    python scripts/download_data.py --symbol 601899.SH

    # 下载多只股票
    python scripts/download_data.py --symbols 601899.SH,600519.SH,000001.SZ

    # 指定日期范围
    python scripts/download_data.py --symbol 601899.SH --start 2020-01-01 --end 2024-12-31

    # 下载分钟线
    python scripts/download_data.py --symbol 601899.SH --period 5m --count 500

    # 定时任务：每日收盘后更新数据
    # crontab -e
    # 0 16 * * 1-5 cd /Users/Shinji/Coding/QuantitativeTrading && python scripts/download_data.py --symbols 601899.SH,600519.SH >> logs/download.log 2>&1
"""

import argparse
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

# 将项目根目录加入 Python 路径，以便导入 quant_trading 包
sys.path.insert(0, str(Path(__file__).parent.parent))

from quant_trading.data.providers.longbridge_provider import LongbridgeProvider, Period, AdjustType
from quant_trading.data.storage.sqlite_storage import SQLiteStorage
from quant_trading.utils.logger import get_logger

logger = get_logger("download_data")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="下载历史K线数据到本地SQLite数据库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --symbol 601899.SH                    # 下载紫金矿业日线（默认）
  %(prog)s --symbols 601899.SH,600519.SH          # 批量下载
  %(prog)s --symbol 601899.SH --start 2020-01-01  # 指定开始日期
  %(prog)s --symbol 601899.SH --period 5m         # 下载5分钟线
  %(prog)s --symbol 601899.SH --count 500         # 只下载最近500根
        """
    )

    parser.add_argument(
        "--symbol",
        type=str,
        help="单个股票代码，如 601899.SH"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        help="多个股票代码，用逗号分隔，如 601899.SH,600519.SH,000001.SZ"
    )
    parser.add_argument(
        "--period",
        type=str,
        default="1d",
        choices=["1d", "1m", "5m", "15m", "30m", "60m"],
        help="K线周期：1d=日线, 1m/5m/15m/30m/60m=分钟线 (默认: 1d)"
    )
    parser.add_argument(
        "--start",
        type=str,
        help="开始日期，格式 YYYY-MM-DD (默认: 2020-01-01)"
    )
    parser.add_argument(
        "--end",
        type=str,
        help="结束日期，格式 YYYY-MM-DD (默认: 昨天)"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="下载数量，不指定则自动计算日期范围"
    )
    parser.add_argument(
        "--adjust",
        type=str,
        default="forward",
        choices=["forward", "backward", "none"],
        help="复权类型：forward=前复权, backward=后复权, none=不复权 (默认: forward)"
    )
    parser.add_argument(
        "--storage-dir",
        type=str,
        help="数据存储目录 (默认: /Users/Shinji/Coding/QuantitativeTrading/data)"
    )

    args = parser.parse_args()

    # 至少要指定一个股票
    if not args.symbol and not args.symbols:
        parser.error("请指定 --symbol 或 --symbols")

    return args


def str_to_date(s: str) -> date:
    """将 YYYY-MM-DD 字符串转为 date 对象"""
    return datetime.strptime(s, "%Y-%m-%d").date()


def period_str_to_enum(period_str: str) -> Period:
    """将周期字符串转为 Period 枚举"""
    mapping = {
        "1d": Period.Day,
        "1m": Period.Min_1,
        "5m": Period.Min_5,
        "15m": Period.Min_15,
        "30m": Period.Min_30,
        "60m": Period.Hour_1,
    }
    return mapping.get(period_str, Period.Day)


def adjust_str_to_enum(adjust_str: str) -> AdjustType:
    """将复权字符串转为 AdjustType 枚举"""
    mapping = {
        "forward": AdjustType.ForwardAdjust,
        "backward": AdjustType.BackwardAdjust,
        "none": AdjustType.NoAdjust,
    }
    return mapping.get(adjust_str, AdjustType.ForwardAdjust)


def download_symbol(
    provider: LongbridgeProvider,
    storage: SQLiteStorage,
    symbol: str,
    period_str: str = "1d",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    count: int = 0,
    adjust_str: str = "forward",
) -> bool:
    """
    下载单个股票的数据

    Args:
        provider: 长桥数据提供者
        storage: 存储实例
        symbol: 股票代码
        period_str: 周期字符串
        start_date: 开始日期
        end_date: 结束日期
        count: 数量（优先于日期范围）
        adjust_str: 复权类型

    Returns:
        是否成功
    """
    period = period_str_to_enum(period_str)
    adjust = adjust_str_to_enum(adjust_str)

    logger.info(f"开始下载 {symbol} {period_str} 数据...")

    try:
        if count > 0:
            # 按数量下载（不需要日期范围）
            bars = provider.get_candlesticks(
                symbol=symbol,
                period=period,
                count=count,
                adjust_type=adjust,
            )
        else:
            # 按日期范围下载
            if end_date is None:
                end_date = date.today() - timedelta(days=1)  # 昨天
            if start_date is None:
                start_date = date(2020, 1, 1)  # 默认从2020年开始

            # 断点续传：检查数据库中已有的最新日期
            latest_date = storage.get_latest_bar_date(symbol, period_str)
            if latest_date:
                # 从最新日期的下一个交易日开始
                start_date = latest_date + timedelta(days=1)
                logger.info(f"  断点续传: 数据库已有数据至 {latest_date}，从 {start_date} 继续下载")

            if start_date > end_date:
                logger.info(f"  {symbol} 数据已是最新，无需下载")
                return True

            bars = provider.get_candlesticks_by_date(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                period=period,
                adjust_type=adjust,
            )

        if not bars:
            logger.warning(f"  {symbol} 未获取到数据")
            return False

        # 保存到数据库
        saved_count = storage.save_bars(symbol, bars, period_str)
        logger.info(f"  成功保存 {saved_count} 条K线")

        return True

    except Exception as e:
        logger.error(f"  下载失败: {e}")
        return False


def main():
    """主函数"""
    args = parse_args()

    # 解析日期参数
    start_date = str_to_date(args.start) if args.start else None
    end_date = str_to_date(args.end) if args.end else None

    # 解析股票代码
    symbols = []
    if args.symbol:
        symbols.append(args.symbol)
    if args.symbols:
        symbols.extend([s.strip() for s in args.symbols.split(",")])

    # 去重
    symbols = list(dict.fromkeys(symbols))

    # 初始化
    storage_dir = Path(args.storage_dir) if args.storage_dir else None
    provider = LongbridgeProvider()
    storage = SQLiteStorage(data_dir=storage_dir)

    logger.info(f"=" * 50)
    logger.info(f"数据下载任务开始")
    logger.info(f"股票数量: {len(symbols)}")
    logger.info(f"周期: {args.period}")
    logger.info(f"复权: {args.adjust}")
    logger.info(f"=" * 50)

    success_count = 0
    fail_count = 0

    for symbol in symbols:
        success = download_symbol(
            provider=provider,
            storage=storage,
            symbol=symbol,
            period_str=args.period,
            start_date=start_date,
            end_date=end_date,
            count=args.count,
            adjust_str=args.adjust,
        )
        if success:
            success_count += 1
        else:
            fail_count += 1

    logger.info(f"=" * 50)
    logger.info(f"下载完成: 成功 {success_count}, 失败 {fail_count}")
    logger.info(f"=" * 50)

    # 关闭连接
    provider.close()


if __name__ == "__main__":
    # 允许直接运行此脚本
    # python scripts/download_data.py --symbol 601899.SH --start 2024-01-01
    main()
