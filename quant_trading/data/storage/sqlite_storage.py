"""
SQLite 数据存储实现
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
将市场数据（K线、行情、元数据）存储到 SQLite 数据库。

设计说明：
- 使用 SQLite 而非其他数据库，是因为它：
  1. 无需单独安装服务，零配置
  2. 适合单机量化系统的数据量级（万级标的 × 年数据）
  3. 支持 SQL 查询，方便数据分析
  4. 可以直接用 DB Browser for SQLite 可视化查看

数据库文件结构：
    data/quant.db          - 主数据库
    ├── daily_bars        - 日线数据表
    ├── minute_bars       - 分钟线数据表
    ├── quotes             - 行情快照表
    ├── positions          - 持仓记录表
    └── trade_logs         - 交易日志表

使用方法：
    storage = SQLiteStorage()
    storage.save_bars("601899.SH", bars)
    bars = storage.load_bars("601899.SH", start_date, end_date)
"""

import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from contextlib import contextmanager

from quant_trading.data.models.market_data import BarData
from quant_trading.utils.logger import get_logger

logger = get_logger("SQLiteStorage")


class SQLiteStorage:
    """
    SQLite 数据存储类

    提供统一的数据读写接口，屏蔽 SQL 细节。
    支持自动建表、批量写入、条件查询。

    示例：
        storage = SQLiteStorage()

        # 保存K线数据
        storage.save_bars("601899.SH", bars)

        # 按日期范围读取
        bars = storage.load_bars(
            "601899.SH",
            start_date=date(2024, 1, 1),
            end_date=date(2025, 1, 1)
        )

        # 读取最后100根K线
        recent_bars = storage.load_bars("601899.SH", count=100)
    """

    # 数据库文件名
    DB_NAME = "quant.db"

    def __init__(self, data_dir: Optional[Path] = None):
        """
        初始化存储

        Args:
            data_dir: 数据目录，默认为 /Users/Shinji/Coding/QuantitativeTrading/data
                     数据库文件将创建在此目录下
        """
        if data_dir is None:
            data_dir = Path("/Users/Shinji/Coding/QuantitativeTrading/data")
        self.data_dir = data_dir
        self.db_path = self.data_dir / self.DB_NAME

        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 初始化数据库表
        self._init_tables()

        logger.info(f"SQLite存储初始化完成: {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """
        获取数据库连接的上下文管理器

        使用方法：
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ...")

        这样做的好处是：
        1. 自动处理连接的开启和关闭
        2. 自动提交事务
        3. 异常时自动回滚
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # 支持列名访问
        try:
            yield conn
            conn.commit()  # 正常结束时提交事务
        except Exception:
            conn.rollback()  # 异常时回滚
            raise
        finally:
            conn.close()

    def _init_tables(self):
        """
        初始化数据库表

        如果表不存在则创建，已存在则跳过。
        """
        # 日线数据表
        self._execute("""
            CREATE TABLE IF NOT EXISTS daily_bars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,           -- 股票代码，如 "601899.SH"
                trade_date DATE NOT NULL,       -- 交易日期
                open REAL NOT NULL,             -- 开盘价
                high REAL NOT NULL,             -- 最高价
                low REAL NOT NULL,              -- 最低价
                close REAL NOT NULL,            -- 收盘价
                volume INTEGER NOT NULL,        -- 成交量
                turnover REAL DEFAULT 0,       -- 成交额
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, trade_date)      -- 确保不重复插入
            )
        """)

        # 分钟线数据表（支持不同周期，区分放在 period 字段）
        self._execute("""
            CREATE TABLE IF NOT EXISTS minute_bars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                trade_date DATE NOT NULL,
                trade_time DATETIME NOT NULL,   -- 精确到分钟的时间
                period TEXT NOT NULL,           -- 周期：1m, 5m, 15m, 30m, 60m
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                turnover REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, trade_time, period)
            )
        """)

        # 行情快照表（每日收盘时记录，用于复盘）
        self._execute("""
            CREATE TABLE IF NOT EXISTS quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                trade_date DATE NOT NULL,
                last_done REAL,                 -- 最新价
                prev_close REAL,                -- 昨收
                open_price REAL,                -- 开盘价
                high REAL,                      -- 最高价
                low REAL,                       -- 最低价
                volume INTEGER,                  -- 成交量
                turnover REAL,                  -- 成交额
                pe_ttm REAL,                    -- 市盈率TTM
                pb REAL,                        -- 市净率
                market_value REAL,              -- 总市值
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, trade_date)
            )
        """)

        # 持仓记录表
        self._execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                trade_date DATE NOT NULL,
                quantity INTEGER NOT NULL,     -- 持仓数量
                avg_cost REAL NOT NULL,         -- 平均成本
                market_value REAL,              -- 市值
                unrealized_pnl REAL,            -- 浮动盈亏
                realized_pnl REAL DEFAULT 0,   -- 已实现盈亏
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, trade_date)
            )
        """)

        # 交易日志表
        self._execute("""
            CREATE TABLE IF NOT EXISTS trade_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,         -- 订单ID
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,         -- BUY / SELL
                price REAL NOT NULL,             -- 成交价
                quantity INTEGER NOT NULL,       -- 成交数量
                commission REAL DEFAULT 0,       -- 手续费
                trade_time TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建索引加速查询
        self._execute("CREATE INDEX IF NOT EXISTS idx_daily_bars_symbol_date ON daily_bars(symbol, trade_date)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_minute_bars_symbol_time ON minute_bars(symbol, trade_time)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_quotes_symbol_date ON quotes(symbol, trade_date)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol_date ON positions(symbol, trade_date)")

    def _execute(self, sql: str, params: Tuple = ()):
        """
        执行一条SQL语句（内部使用）

        Args:
            sql: SQL语句
            params: 参数元组
        """
        with self._get_connection() as conn:
            conn.execute(sql, params)

    def _fetch(self, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """
        执行查询并返回结果（内部使用）

        Args:
            sql: SELECT 语句
            params: 参数元组

        Returns:
            sqlite3.Row 列表
        """
        with self._get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.fetchall()

    # ==================== K线数据读写 ====================

    def save_bars(self, symbol: str, bars: List[BarData], period: str = "1d") -> int:
        """
        保存K线数据到数据库

        使用 REPLACE INTO 语法，遇到相同 symbol+date 时自动覆盖更新。

        Args:
            symbol: 股票代码
            bars: BarData 列表
            period: 周期标识，默认 "1d"（日线）
                   分钟线传入 "1m", "5m", "15m" 等

        Returns:
            成功保存的条数

        示例：
            bars = provider.get_candlesticks("601899.SH", Period.Day, 100)
            storage.save_bars("601899.SH", bars)
        """
        if not bars:
            return 0

        count = 0
        with self._get_connection() as conn:
            for bar in bars:
                trade_date = bar.timestamp.date() if isinstance(bar.timestamp, datetime) else bar.timestamp

                if period == "1d":
                    # 日线数据
                    conn.execute("""
                        REPLACE INTO daily_bars 
                        (symbol, trade_date, open, high, low, close, volume, turnover)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        trade_date,
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        bar.turnover or 0,
                    ))
                else:
                    # 分钟线数据
                    conn.execute("""
                        REPLACE INTO minute_bars
                        (symbol, trade_date, trade_time, period, open, high, low, close, volume, turnover)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        trade_date,
                        bar.timestamp,
                        period,
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                        bar.turnover or 0,
                    ))
                count += 1

        logger.info(f"已保存 {symbol} {period} K线 {count} 条")
        return count

    def load_bars(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        count: Optional[int] = None,
        period: str = "1d",
    ) -> List[BarData]:
        """
        从数据库加载K线数据

        优先使用日期范围查询，其次使用 count 限制数量。

        Args:
            symbol: 股票代码
            start_date: 开始日期（包含）
            end_date: 结束日期（包含）
            count: 只返回最近 count 条，优先于日期范围
            period: 周期，"1d" 或 "1m", "5m" 等

        Returns:
            BarData 列表，按时间正序排列

        示例：
            # 获取最近100天
            bars = storage.load_bars("601899.SH", count=100)

            # 获取2024年全年数据
            bars = storage.load_bars(
                "601899.SH",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31)
            )
        """
        if period == "1d":
            table = "daily_bars"
        else:
            table = "minute_bars"

        # 构建查询
        if count is not None:
            # 使用 LIMIT 返回最新数据
            sql = f"""
                SELECT * FROM {table}
                WHERE symbol = ?
                ORDER BY trade_date DESC
                LIMIT ?
            """
            # 注意：返回的是倒序，后面需要反转
            rows = self._fetch(sql, (symbol, count))
            rows = list(reversed(rows))  # 转为正序
        elif start_date and end_date:
            sql = f"""
                SELECT * FROM {table}
                WHERE symbol = ? AND trade_date >= ? AND trade_date <= ?
                ORDER BY trade_date ASC
            """
            rows = self._fetch(sql, (symbol, start_date, end_date))
        else:
            # 无条件限制，默认返回最近1000条
            sql = f"""
                SELECT * FROM {table}
                WHERE symbol = ?
                ORDER BY trade_date DESC
                LIMIT 1000
            """
            rows = self._fetch(sql, (symbol,))
            rows = list(reversed(rows))

        # 转换为 BarData 对象
        bars = []
        for row in rows:
            if period == "1d":
                trade_date_str = row["trade_date"]
                trade_date = datetime.strptime(trade_date_str, "%Y-%m-%d").date() if isinstance(trade_date_str, str) else trade_date_str
                bar = BarData(
                    symbol=row["symbol"],
                    timestamp=datetime.combine(trade_date, datetime.min.time()),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    turnover=row["turnover"] or 0,
                )
            else:
                bar = BarData(
                    symbol=row["symbol"],
                    timestamp=datetime.fromisoformat(row["trade_time"]),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    turnover=row["turnover"] or 0,
                )
            bars.append(bar)

        return bars

    def get_latest_bar_date(self, symbol: str, period: str = "1d") -> Optional[date]:
        """
        获取数据库中某标的最新的K线日期

        用于判断从哪个日期继续下载数据（断点续传）。

        Args:
            symbol: 股票代码
            period: 周期

        Returns:
            最新日期，若无数据返回 None
        """
        table = "daily_bars" if period == "1d" else "minute_bars"
        sql = f"SELECT MAX(trade_date) as max_date FROM {table} WHERE symbol = ?"
        rows = self._fetch(sql, (symbol,))
        if rows and rows[0]["max_date"]:
            return datetime.strptime(rows[0]["max_date"], "%Y-%m-%d").date()
        return None

    # ==================== 行情快照 ====================

    def save_quote(self, symbol: str, trade_date: date, quote: Dict[str, Any]) -> bool:
        """
        保存行情快照

        Args:
            symbol: 股票代码
            trade_date: 交易日期
            quote: 行情字典，包含 last_done, prev_close, open, high, low, volume, turnover 等

        Returns:
            是否成功
        """
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    REPLACE INTO quotes
                    (symbol, trade_date, last_done, prev_close, open_price, high, low, volume, turnover, pe_ttm, pb, market_value)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol,
                    trade_date,
                    quote.get("last_done"),
                    quote.get("prev_close"),
                    quote.get("open"),
                    quote.get("high"),
                    quote.get("low"),
                    quote.get("volume"),
                    quote.get("turnover"),
                    quote.get("pe_ttm"),
                    quote.get("pb"),
                    quote.get("market_value"),
                ))
            return True
        except Exception as e:
            logger.error(f"保存行情快照失败 {symbol}: {e}")
            return False

    def load_quotes(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        读取历史行情快照

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            行情字典列表
        """
        sql = "SELECT * FROM quotes WHERE symbol = ?"
        params = [symbol]

        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)

        sql += " ORDER BY trade_date ASC"

        rows = self._fetch(sql, tuple(params))
        return [dict(row) for row in rows]

    # ==================== 持仓记录 ====================

    def save_position(self, symbol: str, trade_date: date, position: Dict[str, Any]) -> bool:
        """
        保存持仓快照

        Args:
            symbol: 股票代码
            trade_date: 日期
            position: 持仓字典，包含 quantity, avg_cost, market_value, unrealized_pnl 等

        Returns:
            是否成功
        """
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    REPLACE INTO positions
                    (symbol, trade_date, quantity, avg_cost, market_value, unrealized_pnl, realized_pnl)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol,
                    trade_date,
                    position.get("quantity", 0),
                    position.get("avg_cost", 0),
                    position.get("market_value", 0),
                    position.get("unrealized_pnl", 0),
                    position.get("realized_pnl", 0),
                ))
            return True
        except Exception as e:
            logger.error(f"保存持仓失败 {symbol}: {e}")
            return False

    def load_positions(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        读取持仓历史

        Args:
            symbol: 股票代码，为空则返回所有
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            持仓字典列表
        """
        sql = "SELECT * FROM positions WHERE 1=1"
        params = []

        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)

        sql += " ORDER BY trade_date DESC"

        rows = self._fetch(sql, tuple(params))
        return [dict(row) for row in rows]

    # ==================== 交易日志 ====================

    def log_trade(
        self,
        order_id: str,
        symbol: str,
        direction: str,
        price: float,
        quantity: int,
        commission: float = 0,
        trade_time: Optional[datetime] = None,
    ) -> bool:
        """
        记录一笔成交

        Args:
            order_id: 订单ID
            symbol: 股票代码
            direction: 方向，"BUY" 或 "SELL"
            price: 成交价
            quantity: 成交数量
            commission: 手续费
            trade_time: 成交时间，默认为当前时间

        Returns:
            是否成功
        """
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO trade_logs
                    (order_id, symbol, direction, price, quantity, commission, trade_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    symbol,
                    direction,
                    price,
                    quantity,
                    commission,
                    trade_time or datetime.now(),
                ))
            logger.info(f"交易记录: {direction} {symbol} {quantity}@{price}")
            return True
        except Exception as e:
            logger.error(f"记录交易失败: {e}")
            return False

    def load_trade_logs(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        读取交易日志

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            交易记录列表
        """
        sql = "SELECT * FROM trade_logs WHERE 1=1"
        params = []

        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        if start_date:
            sql += " AND DATE(trade_time) >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND DATE(trade_time) <= ?"
            params.append(end_date)

        sql += " ORDER BY trade_time DESC"

        rows = self._fetch(sql, tuple(params))
        return [dict(row) for row in rows]

    # ==================== 统计查询 ====================

    def get_symbols(self) -> List[str]:
        """
        获取数据库中所有有数据的股票代码

        Returns:
            股票代码列表
        """
        rows = self._fetch("SELECT DISTINCT symbol FROM daily_bars ORDER BY symbol")
        return [row["symbol"] for row in rows]

    def get_date_range(self, symbol: str, period: str = "1d") -> Tuple[Optional[date], Optional[date]]:
        """
        获取某股票在数据库中的数据日期范围

        Args:
            symbol: 股票代码
            period: 周期

        Returns:
            (最早日期, 最晚日期)，若无数据返回 (None, None)
        """
        table = "daily_bars" if period == "1d" else "minute_bars"
        sql = f"SELECT MIN(trade_date) as min_date, MAX(trade_date) as max_date FROM {table} WHERE symbol = ?"
        rows = self._fetch(sql, (symbol,))
        if rows and rows[0]["min_date"]:
            min_d = datetime.strptime(rows[0]["min_date"], "%Y-%m-%d").date()
            max_d = datetime.strptime(rows[0]["max_date"], "%Y-%m-%d").date()
            return min_d, max_d
        return None, None

    def __repr__(self) -> str:
        return f"<SQLiteStorage db={self.db_path}>"
