"""
HTTP API 层
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
提供 HTTP 接口，方便外部系统调用量化策略服务。

使用 FastAPI 实现，支持：
- GET /status - 查询系统状态
- GET /positions - 查询持仓
- GET /accounts - 查询账户信息
- GET /quotes/{symbol} - 查询实时行情
- POST /orders - 发送订单
- GET /backtest - 运行回测
- WS /ws - WebSocket 实时行情订阅

启动方式：
    uvicorn quant_trading.api.http_api:app --host 0.0.0.0 --port 8000 --reload
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, date
from pathlib import Path
import sys

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio

from quant_trading.core import BacktestEngine, BacktestConfig, StrategyEngine
from quant_trading.data import SQLiteStorage, LongbridgeProvider
from quant_trading.data.providers.longbridge_provider import Period, AdjustType

# ============== FastAPI 应用 ==============

app = FastAPI(
    title="量化交易系统 API",
    description="Quantitative Trading System HTTP API",
    version="0.1.0",
)

# CORS 配置（允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== 内部状态 ==============

# 全局数据提供者（懒加载）
_data_provider: Optional[LongbridgeProvider] = None
_storage: Optional[SQLiteStorage] = None


def get_provider() -> LongbridgeProvider:
    """获取数据提供者实例（单例）"""
    global _data_provider
    if _data_provider is None:
        _data_provider = LongbridgeProvider()
    return _data_provider


def get_storage() -> SQLiteStorage:
    """获取存储实例（单例）"""
    global _storage
    if _storage is None:
        _storage = SQLiteStorage()
    return _storage


# ============== 请求/响应模型 ==============

class OrderRequest(BaseModel):
    """下单请求"""
    symbol: str
    direction: int          # 1=买入, -1=卖出
    price: float
    quantity: int
    order_type: str = "MARKET"


class BacktestRequest(BaseModel):
    """回测请求"""
    symbol: str
    strategy: str           # 策略名称，如 "MACDCrossStrategy"
    start_date: str         # "2024-01-01"
    end_date: str           # "2024-12-31"
    initial_cash: float = 1000000.0
    params: Dict[str, Any] = {}  # 策略参数


class QuoteResponse(BaseModel):
    """行情响应"""
    symbol: str
    last_done: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: int
    turnover: float
    timestamp: str


class PositionResponse(BaseModel):
    """持仓响应"""
    symbol: str
    quantity: int
    avg_cost: float
    last_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


# ============== API 路由 ==============

@app.get("/")
def root():
    """API 根路径"""
    return {
        "name": "量化交易系统 API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/status")
def get_status():
    """
    查询系统状态

    返回系统运行状态、数据连接状态等基本信息。
    """
    provider = get_provider()
    storage = get_storage()

    try:
        # 尝试获取一只股票的价格来测试连接
        provider.get_latest_price("601899.SH")
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "running",
        "data_provider": "longbridge",
        "data_provider_status": "connected" if provider._connected else "disconnected",
        "database_status": db_status,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/quotes/{symbol}", response_model=QuoteResponse)
def get_quote(symbol: str):
    """
    查询单个标的实时行情

    Args:
        symbol: 股票代码，如 601899.SH、700.HK、AAPL.US
    """
    provider = get_provider()
    quote = provider.get_quote(symbol)

    if not quote:
        raise HTTPException(status_code=404, detail=f"行情获取失败: {symbol}")

    return QuoteResponse(
        symbol=quote["symbol"],
        last_done=quote["last_done"],
        prev_close=quote["prev_close"],
        open=quote["open"],
        high=quote["high"],
        low=quote["low"],
        volume=quote["volume"],
        turnover=quote["turnover"],
        timestamp=quote["timestamp"].isoformat() if quote.get("timestamp") else "",
    )


@app.get("/quotes")
def get_quotes(symbols: str = Query(..., description="股票代码，多个用逗号分隔")):
    """
    批量查询行情

    Args:
        symbols: 股票代码列表，用逗号分隔
    """
    symbol_list = [s.strip() for s in symbols.split(",")]
    provider = get_provider()
    quotes = provider.get_quotes(symbol_list)

    return {"quotes": quotes}


@app.get("/bars/{symbol}")
def get_bars(
    symbol: str,
    period: str = Query("1d", description="周期: 1d, 1m, 5m, 15m, 30m, 60m"),
    count: int = Query(100, description="数量"),
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    adjust: str = Query("forward", description="复权: forward, backward, none"),
):
    """
    获取K线数据

    Args:
        symbol: 股票代码
        period: K线周期
        count: 数量
        start: 开始日期
        end: 结束日期
        adjust: 复权类型
    """
    storage = get_storage()

    # 优先从数据库读取
    bars = storage.load_bars(symbol, count=count)

    if not bars:
        # 数据库没有，从网络获取
        provider = get_provider()
        period_enum = {
            "1d": Period.Day,
            "1m": Period.Min_1,
            "5m": Period.Min_5,
            "15m": Period.Min_15,
            "30m": Period.Min_30,
            "60m": Period.Hour_1,
        }.get(period, Period.Day)

        adjust_enum = {
            "forward": AdjustType.ForwardAdjust,
            "backward": AdjustType.BackwardAdjust,
            "none": AdjustType.NoAdjust,
        }.get(adjust, AdjustType.ForwardAdjust)

        bars = provider.get_candlesticks(symbol, period_enum, count, adjust_enum)

    return {
        "symbol": symbol,
        "period": period,
        "count": len(bars),
        "bars": [
            {
                "timestamp": bar.timestamp.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "turnover": bar.turnover,
            }
            for bar in bars
        ],
    }


@app.get("/positions")
def get_positions():
    """
    查询当前持仓

    注意：这里返回的是回测引擎的持仓状态，
    实盘需要接入券商 API 获取真实持仓。
    """
    # 暂时返回示例数据
    return {
        "positions": [],
        "total_value": 0.0,
        "total_pnl": 0.0,
    }


@app.post("/orders")
def place_order(order: OrderRequest):
    """
    发送订单（模拟）

    注意：这是模拟下单，不会真实成交。
    实盘需要接入券商 API。
    """
    return {
        "order_id": f"ORD_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "symbol": order.symbol,
        "direction": "买入" if order.direction > 0 else "卖出",
        "price": order.price,
        "quantity": order.quantity,
        "status": "pending",
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/backtest")
def run_backtest(request: BacktestRequest):
    """
    运行回测

    Args:
        request: 回测参数

    Returns:
        回测结果
    """
    from quant_trading.strategies.example import MACDCrossStrategy, MeanReversionStrategy

    # 策略映射
    strategies = {
        "MACDCrossStrategy": MACDCrossStrategy,
        "MeanReversionStrategy": MeanReversionStrategy,
    }

    strategy_class = strategies.get(request.strategy)
    if not strategy_class:
        raise HTTPException(status_code=400, detail=f"未知策略: {request.strategy}")

    # 初始化回测引擎
    config = BacktestConfig(
        initial_cash=request.initial_cash,
        commission_rate=0.0003,
    )
    engine = BacktestEngine(config=config)

    # 加载数据
    storage = get_storage()
    try:
        engine.load_data_from_storage(
            symbol=request.symbol,
            storage=storage,
            start_date=datetime.strptime(request.start_date, "%Y-%m-%d").date(),
            end_date=datetime.strptime(request.end_date, "%Y-%m-%d").date(),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"数据加载失败: {str(e)}")

    # 设置策略
    engine.set_strategy(strategy_class, params=request.params)

    # 运行回测
    try:
        result = engine.run()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回测执行失败: {str(e)}")

    return {
        "summary": result.summary(),
        "metrics": result.to_dict(),
        "trades_count": result.total_trades,
        "trades": result.trades[-20:],  # 返回最近20笔交易
    }


@app.get("/storage/symbols")
def get_stored_symbols():
    """获取数据库中已有的股票列表"""
    storage = get_storage()
    symbols = storage.get_symbols()
    return {"symbols": symbols, "count": len(symbols)}


@app.get("/storage/range/{symbol}")
def get_data_range(symbol: str, period: str = "1d"):
    """获取某股票在数据库中的日期范围"""
    storage = get_storage()
    min_date, max_date = storage.get_date_range(symbol, period)
    return {
        "symbol": symbol,
        "period": period,
        "min_date": str(min_date) if min_date else None,
        "max_date": str(max_date) if max_date else None,
    }


# ============== WebSocket 实时行情 ==============

class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, List[str]] = {}  # websocket -> [symbols]

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = []
        logger.info(f"WebSocket 连接建立，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            del self.subscriptions[websocket]
            logger.info(f"WebSocket 连接断开，当前连接数: {len(self.active_connections)}")

    def subscribe(self, websocket: WebSocket, symbol: str):
        if symbol not in self.subscriptions[websocket]:
            self.subscriptions[websocket].append(symbol)

    def unsubscribe(self, websocket: WebSocket, symbol: str):
        if symbol in self.subscriptions[websocket]:
            self.subscriptions[websocket].remove(symbol)

    async def broadcast_quote(self, quote: Dict[str, Any]):
        """广播行情给所有订阅者"""
        for websocket in self.active_connections:
            # 检查是否订阅了该股票
            if quote["symbol"] in self.subscriptions.get(websocket, []):
                try:
                    await websocket.send_json(quote)
                except Exception:
                    pass


# 全局连接管理器
manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 实时行情订阅

    客户端连接后，发送订阅消息：
    {"action": "subscribe", "symbol": "601899.SH"}

    取消订阅：
    {"action": "unsubscribe", "symbol": "601899.SH"}

    服务器会推送实时行情：
    {"symbol": "601899.SH", "last_done": 35.72, ...}
    """
    await manager.connect(websocket)

    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_json()

            action = data.get("action")
            symbol = data.get("symbol")

            if action == "subscribe" and symbol:
                manager.subscribe(websocket, symbol)
                await websocket.send_json({
                    "type": "subscribed",
                    "symbol": symbol,
                })

            elif action == "unsubscribe" and symbol:
                manager.unsubscribe(websocket, symbol)
                await websocket.send_json({
                    "type": "unsubscribed",
                    "symbol": symbol,
                })

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
        manager.disconnect(websocket)


# ============== 启动信息 ==============

logger = get_logger = lambda name: __import__("loguru").logger.bind(name=name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
