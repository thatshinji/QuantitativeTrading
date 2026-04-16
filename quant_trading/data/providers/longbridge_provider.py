"""
长桥（Longbridge）数据源提供者
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
封装长桥 OpenAPI，提供统一的数据获取接口。

支持功能：
- 实时行情（最新价、涨跌、成交量等）
- K线数据（日线、分钟线）
- 分时数据
- 基本面数据（PE、PB、市值等）
- 资金流向
- 盘口数据（买卖盘）

使用方式：
    provider = LongbridgeProvider()
    quote = provider.get_quote("601899.SH")
    bars = provider.get_candlesticks("601899.SH", Period.Day, 100)
"""

from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any, Union
from enum import Enum

# 长桥 Python SDK
try:
    from longbridge.openapi import (
        QuoteContext,          # 行情上下文（同步）
        AsyncQuoteContext,     # 行情上下文（异步）
        Period,                # K线周期
        AdjustType,            # 复权类型
        TradeSessions,         # 交易时段
        Market,                # 市场
        SubType,               # 订阅类型
    )
    HAS_LONGBRIDGE_SDK = True
except ImportError:
    HAS_LONGBRIDGE_SDK = False
    QuoteContext = None
    Period = None

from quant_trading.data.models.market_data import BarData, TickData
from quant_trading.utils.logger import get_logger

logger = get_logger("LongbridgeProvider")


class Period(Enum):
    """
    K线周期枚举
    用于指定获取哪种周期的K线数据
    """
    Min_1 = "1m"      # 1分钟
    Min_5 = "5m"      # 5分钟
    Min_15 = "15m"    # 15分钟
    Min_30 = "30m"    # 30分钟
    Hour_1 = "1h"     # 1小时
    Day = "1d"        # 日线
    Week = "1w"       # 周线
    Month = "1M"      # 月线


class AdjustType(Enum):
    """复权类型"""
    NoAdjust = 0      # 不复权
    ForwardAdjust = 1 # 前复权
    BackwardAdjust = 2 # 后复权
    ForwardBackwardAdjust = 3  # 全复权


class Market(Enum):
    """市场"""
    HK = "HK"         # 港股
    US = "US"         # 美股
    SH = "SH"         # 沪市
    SZ = "SZ"         # 深市
    SG = "SG"         # 新加坡


class LongbridgeProvider:
    """
    长桥数据源提供者类

    封装长桥 API，提供标准化的市场数据接口。
    所有返回数据都转换为框架内部的标准格式（BarData、TickData等）。

    使用说明：
        1. 初始化时不需传参，会自动读取配置文件中的认证信息
        2. 每个方法都是独立调用，适合低频调用场景
        3. 高频场景建议使用异步版本 AsyncLongbridgeProvider
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化长桥数据提供者

        Args:
            config: 配置字典，包含 app_key, app_secret, access_token 等
                   若为 None，则从环境变量或配置文件中读取
        """
        self.config = config or {}
        self._ctx: Optional[QuoteContext] = None
        self._connected = False

    def _get_context(self) -> QuoteContext:
        """
        获取或创建行情上下文（懒加载）

        第一次调用时创建，后续复用。
        长桥每次创建 Context 都会建立新的 WebSocket 连接。

        Returns:
            QuoteContext 实例

        Raises:
            RuntimeError: 当 SDK 未安装或认证失败时
        """
        if not HAS_LONGBRIDGE_SDK:
            raise RuntimeError(
                "长桥 SDK 未安装，请运行: pip install longbridge\n"
                "或参考: https://open.longbridge.com/install"
            )

        if self._ctx is None:
            # 从配置或环境变量获取认证信息
            app_key = self.config.get("app_key") or self._get_env("LONGBRIDGE_APP_KEY")
            app_secret = self.config.get("app_secret") or self._get_env("LONGBRIDGE_APP_SECRET")
            access_token = self.config.get("access_token") or self._get_env("LONGBRIDGE_ACCESS_TOKEN")

            if not all([app_key, app_secret, access_token]):
                raise RuntimeError(
                    "长桥认证信息不完整，请设置以下环境变量：\n"
                    "LONGBRIDGE_APP_KEY\n"
                    "LONGBRIDGE_APP_SECRET\n"
                    "LONGBRIDGE_ACCESS_TOKEN\n"
                    "或在配置中传入这些参数"
                )

            # 创建行情上下文（同步版本）
            self._ctx = QuoteContext(
                app_key=app_key,
                app_secret=app_secret,
                access_token=access_token,
            )
            self._connected = True
            logger.info("长桥行情上下文创建成功")

        return self._ctx

    def _get_env(self, key: str, default: str = "") -> str:
        """从环境变量获取值"""
        import os
        return os.environ.get(key, default)

    def close(self):
        """
        关闭连接，释放资源

        在完成所有数据获取后调用，可选。
        不调用也不会造成内存泄漏（Python 垃圾回收会处理）。
        """
        if self._ctx is not None:
            self._ctx = None
            self._connected = False
            logger.info("长桥连接已关闭")

    # ==================== 行情数据 ====================

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取单个标的的实时行情

        Args:
            symbol: 股票代码，格式如 "601899.SH"、"700.HK"、"AAPL.US"

        Returns:
            行情字典，包含字段：
            - last_done: 最新价
            - prev_close: 昨收价
            - open: 开盘价
            - high: 最高价
            - low: 最低价
            - volume: 成交量
            - turnover: 成交额
            - trade_status: 交易状态
            - timestamp: 时间戳

            若获取失败返回 None
        """
        ctx = self._get_context()
        try:
            resp = ctx.quote([symbol])
            if resp and len(resp) > 0:
                q = resp[0]
                return {
                    "symbol": q.symbol,
                    "last_done": float(q.last_done) if q.last_done else 0.0,
                    "prev_close": float(q.prev_close_price) if q.prev_close_price else 0.0,
                    "open": float(q.open) if q.open else 0.0,
                    "high": float(q.high) if q.high else 0.0,
                    "low": float(q.low) if q.low else 0.0,
                    "volume": int(q.volume) if q.volume else 0,
                    "turnover": float(q.turnover) if q.turnover else 0.0,
                    "trade_status": str(q.trade_status) if q.trade_status else "UNKNOWN",
                    "timestamp": datetime.now(),
                }
        except Exception as e:
            logger.error(f"获取行情失败 {symbol}: {e}")
        return None

    def get_quotes(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        批量获取多个标的的实时行情

        Args:
            symbols: 股票代码列表

        Returns:
            行情字典列表，只返回成功获取的行情
        """
        ctx = self._get_context()
        results = []
        try:
            resp = ctx.quote(symbols)
            for q in resp:
                results.append({
                    "symbol": q.symbol,
                    "last_done": float(q.last_done) if q.last_done else 0.0,
                    "prev_close": float(q.prev_close_price) if q.prev_close_price else 0.0,
                    "open": float(q.open) if q.open else 0.0,
                    "high": float(q.high) if q.high else 0.0,
                    "low": float(q.low) if q.low else 0.0,
                    "volume": int(q.volume) if q.volume else 0,
                    "turnover": float(q.turnover) if q.turnover else 0.0,
                })
        except Exception as e:
            logger.error(f"批量获取行情失败: {e}")
        return results

    def get_latest_price(self, symbol: str) -> float:
        """
        获取最新价（最常用的简化接口）

        Args:
            symbol: 股票代码

        Returns:
            最新价，若失败返回 0.0
        """
        quote = self.get_quote(symbol)
        return quote["last_done"] if quote else 0.0

    # ==================== K线数据 ====================

    def get_candlesticks(
        self,
        symbol: str,
        period: Period = Period.Day,
        count: int = 100,
        adjust_type: AdjustType = AdjustType.ForwardAdjust,
        end_date: Optional[date] = None,
    ) -> List[BarData]:
        """
        获取K线数据（历史K线）

        Args:
            symbol: 股票代码
            period: K线周期，默认日线
            count: 获取数量，默认100根
            adjust_type: 复权类型，默认前复权
            end_date: 结束日期，默认今天

        Returns:
            BarData 列表，每根K线的数据

        示例：
            # 获取茅台最近100天日线（前复权）
            bars = provider.get_candlesticks("600519.SH", Period.Day, 100)
            for bar in bars:
                print(bar.date, bar.close, bar.volume)
        """
        ctx = self._get_context()
        try:
            # 将 Period 转换为 SDK 期望的格式
            sdk_period = self._to_sdk_period(period)

            if end_date is None:
                end_date = datetime.now().date()

            # 调用长桥 API
            resp = ctx.candlesticks(
                symbol,
                sdk_period,
                count,
                self._to_sdk_adjust_type(adjust_type),
            )

            # 转换为框架标准格式 BarData
            bars = []
            for c in resp:
                bars.append(BarData(
                    symbol=symbol,
                    timestamp=c.timestamp if isinstance(c.timestamp, datetime) else datetime.fromtimestamp(c.timestamp),
                    open=float(c.open) if c.open else 0.0,
                    high=float(c.high) if c.high else 0.0,
                    low=float(c.low) if c.low else 0.0,
                    close=float(c.close) if c.close else 0.0,
                    volume=int(c.volume) if c.volume else 0,
                    turnover=float(c.turnover) if c.turnover else 0.0,
                ))
            return bars

        except Exception as e:
            logger.error(f"获取K线失败 {symbol}: {e}")
            return []

    def get_candlesticks_by_date(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        period: Period = Period.Day,
        adjust_type: AdjustType = AdjustType.ForwardAdjust,
    ) -> List[BarData]:
        """
        按日期范围获取K线数据

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            period: K线周期
            adjust_type: 复权类型

        Returns:
            BarData 列表

        注意：
            日期范围不能超过1个月（长桥API限制）
        """
        ctx = self._get_context()
        try:
            sdk_period = self._to_sdk_period(period)
            resp = ctx.history_candlesticks_by_date(
                symbol,
                sdk_period,
                self._to_sdk_adjust_type(adjust_type),
                start=start_date,
                end=end_date,
            )

            bars = []
            for c in resp:
                bars.append(BarData(
                    symbol=symbol,
                    timestamp=c.timestamp if isinstance(c.timestamp, datetime) else datetime.fromtimestamp(c.timestamp),
                    open=float(c.open) if c.open else 0.0,
                    high=float(c.high) if c.high else 0.0,
                    low=float(c.low) if c.low else 0.0,
                    close=float(c.close) if c.close else 0.0,
                    volume=int(c.volume) if c.volume else 0,
                    turnover=float(c.turnover) if c.turnover else 0.0,
                ))
            return bars

        except Exception as e:
            logger.error(f"按日期获取K线失败 {symbol}: {e}")
            return []

    def get_realtime_candlesticks(
        self,
        symbol: str,
        period: Period = Period.Day,
        count: int = 100,
    ) -> List[BarData]:
        """
        获取实时（当日）K线

        用于回测或实盘时获取当日最新的K线数据。
        会返回从当日开盘到当前时刻的所有K线。

        Args:
            symbol: 股票代码
            period: K线周期
            count: 数量

        Returns:
            BarData 列表
        """
        ctx = self._get_context()
        try:
            sdk_period = self._to_sdk_period(period)
            resp = ctx.candlesticks(
                symbol,
                sdk_period,
                count,
                AdjustType.NoAdjust,  # 实时数据不复权
                TradeSessions.Intraday,
            )

            bars = []
            for c in resp:
                bars.append(BarData(
                    symbol=symbol,
                    timestamp=c.timestamp if isinstance(c.timestamp, datetime) else datetime.fromtimestamp(c.timestamp),
                    open=float(c.open) if c.open else 0.0,
                    high=float(c.high) if c.high else 0.0,
                    low=float(c.low) if c.low else 0.0,
                    close=float(c.close) if c.close else 0.0,
                    volume=int(c.volume) if c.volume else 0,
                    turnover=float(c.turnover) if c.turnover else 0.0,
                ))
            return bars

        except Exception as e:
            logger.error(f"获取实时K线失败 {symbol}: {e}")
            return []

    # ==================== 分时数据 ====================

    def get_intraday(self, symbol: str) -> List[Dict[str, Any]]:
        """
        获取分时数据（当日）

        返回当日每分钟的交易数据，包含价格和成交量。

        Args:
            symbol: 股票代码

        Returns:
            分时数据列表，每项包含：
            - time: 时间字符串 "HH:MM:SS"
            - price: 价格
            - volume: 成交量
            - turnover: 成交额
        """
        ctx = self._get_context()
        try:
            resp = ctx.intraday(symbol)
            return [
                {
                    "time": line.time.strftime("%H:%M:%S") if hasattr(line.time, 'strftime') else str(line.time),
                    "price": float(line.price) if line.price else 0.0,
                    "volume": int(line.volume) if line.volume else 0,
                    "turnover": float(line.turnover) if line.turnover else 0.0,
                }
                for line in resp
            ]
        except Exception as e:
            logger.error(f"获取分时数据失败 {symbol}: {e}")
            return []

    # ==================== 盘口数据 ====================

    def get_depth(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取买卖盘口（盘口数据）

        返回当前的买卖队列，通常显示10档行情。

        Args:
            symbol: 股票代码

        Returns:
            包含 bids（买盘）和 asks（卖盘）的字典
            每档包含 price（价格）和 volume（量）
        """
        ctx = self._get_context()
        try:
            resp = ctx.depth(symbol)
            if resp:
                return {
                    "bids": [
                        {"price": float(d.price), "volume": int(d.volume)}
                        for d in resp.bids
                    ],
                    "asks": [
                        {"price": float(d.price), "volume": int(d.volume)}
                        for d in resp.asks
                    ],
                }
        except Exception as e:
            logger.error(f"获取盘口失败 {symbol}: {e}")
        return None

    # ==================== 资金流向 ====================

    def get_capital_flow(self, symbol: str) -> List[Dict[str, Any]]:
        """
        获取资金流向（分时级别）

        返回一段时间内每分钟的资金净流入/流出数据。

        Args:
            symbol: 股票代码

        Returns:
            资金流向列表，每项包含：
            - time: 时间
            - flow: 净流入额（正=流入，负=流出）
            - volume: 成交量
        """
        ctx = self._get_context()
        try:
            resp = ctx.capital_flow(symbol)
            return [
                {
                    "time": line.time if hasattr(line, 'time') else line[0],
                    "flow": float(line.flow) if hasattr(line, 'flow') else float(line[1]),
                    "volume": int(line.volume) if hasattr(line, 'volume') else int(line[2]),
                }
                for line in resp
            ]
        except Exception as e:
            logger.error(f"获取资金流向失败 {symbol}: {e}")
            return []

    # ==================== 基本面数据 ====================

    def get_static_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取股票基本信息

        包含公司名称、交易所、市值、PE、PB、每股收益、股息等。

        Args:
            symbol: 股票代码

        Returns:
            基本信息字典，字段说明：
            - name_en: 英文名
            - name_zh: 中文名
            - exchange: 交易所
            - currency: 货币
            - lot_size: 每手股数
            - total_shares: 总股本
            - eps: 每股收益
            - eps_ttm: TTM每股收益
            - bps: 每股净资产
            - dividend_yield: 股息率
        """
        ctx = self._get_context()
        try:
            resp = ctx.static_info([symbol])
            if resp and len(resp) > 0:
                info = resp[0]
                return {
                    "symbol": info.symbol,
                    "name_en": info.name_en,
                    "name_zh": info.name_zh,
                    "exchange": info.exchange,
                    "currency": info.currency,
                    "lot_size": int(info.lot_size) if info.lot_size else 0,
                    "total_shares": int(info.total_shares) if info.total_shares else 0,
                    "circulating_shares": int(info.circulating_shares) if info.circulating_shares else 0,
                    "eps": float(info.eps) if info.eps else 0.0,
                    "eps_ttm": float(info.eps_ttm) if info.eps_ttm else 0.0,
                    "bps": float(info.bps) if info.bps else 0.0,
                    "dividend_yield": float(info.dividend_yield) if info.dividend_yield else 0.0,
                }
        except Exception as e:
            logger.error(f"获取基本信息失败 {symbol}: {e}")
        return None

    def get_indicators(self, symbols: List[str]) -> Dict[str, Dict[str, float]]:
        """
        批量获取指标数据（PE、PB、市值等）

        比 static_info 更适合批量查询估值指标。

        Args:
            symbols: 股票代码列表

        Returns:
            以 symbol 为键的字典，值包含：
            - pe_ttm: 市盈率TTM
            - pb: 市净率
            - total_market_value: 总市值
            - turnover_rate: 换手率
        """
        ctx = self._get_context()
        try:
            from longbridge.openapi import CalcIndex
            resp = ctx.calc_indexes(
                symbols,
                [
                    CalcIndex.PeTtmRatio,
                    CalcIndex.PbRatio,
                    CalcIndex.TotalMarketValue,
                    CalcIndex.TurnoverRate,
                ],
            )
            result = {}
            for item in resp:
                result[item.symbol] = {
                    "pe_ttm": float(item.values[0]) if item.values[0] is not None else 0.0,
                    "pb": float(item.values[1]) if item.values[1] is not None else 0.0,
                    "total_market_value": float(item.values[2]) if item.values[2] is not None else 0.0,
                    "turnover_rate": float(item.values[3]) if item.values[3] is not None else 0.0,
                }
            return result
        except Exception as e:
            logger.error(f"获取指标失败: {e}")
            return {}

    # ==================== 辅助方法 ====================

    def _to_sdk_period(self, period: Period) -> Any:
        """将框架 Period 转换为长桥 SDK 的 Period"""
        # 这里做映射，因为长桥 SDK 的 Period 是 C 扩展的 enum
        # 实际使用时需要根据 SDK 文档调整
        if not HAS_LONGBRIDGE_SDK:
            return None
        from longbridge.openapi import Period as LBPeriod
        mapping = {
            Period.Min_1: LBPeriod.Min_1,
            Period.Min_5: LBPeriod.Min_5,
            Period.Min_15: LBPeriod.Min_15,
            Period.Min_30: LBPeriod.Min_30,
            Period.Hour_1: LBPeriod.Hour_1,
            Period.Day: LBPeriod.Day,
            Period.Week: LBPeriod.Week,
            Period.Month: LBPeriod.Month,
        }
        return mapping.get(period, LBPeriod.Day)

    def _to_sdk_adjust_type(self, adjust_type: AdjustType) -> Any:
        """将框架 AdjustType 转换为长桥 SDK 的 AdjustType"""
        if not HAS_LONGBRIDGE_SDK:
            return None
        from longbridge.openapi import AdjustType as LBAdjustType
        mapping = {
            AdjustType.NoAdjust: LBAdjustType.NoAdjust,
            AdjustType.ForwardAdjust: LBAdjustType.ForwardAdjust,
            AdjustType.BackwardAdjust: LBAdjustType.BackwardAdjust,
            AdjustType.ForwardBackwardAdjust: LBAdjustType.ForwardBackwardAdjust,
        }
        return mapping.get(adjust_type, LBAdjustType.ForwardAdjust)

    def __repr__(self) -> str:
        return f"<LongbridgeProvider connected={self._connected}>"
