"""
API 层（HTTP + WebSocket）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
提供 HTTP REST API 和 WebSocket 实时行情接口。

HTTP API：
    - GET  /status              系统状态
    - GET  /quotes/{symbol}     查询行情
    - GET  /bars/{symbol}       获取K线
    - POST /orders              下单（模拟）
    - POST /backtest            运行回测
    - WS   /ws                  WebSocket 实时行情

启动服务：
    uvicorn quant_trading.api.http_api:app --host 0.0.0.0 --port 8000

访问文档：
    http://localhost:8000/docs
"""

from quant_trading.api.http_api import app

__all__ = ["app"]
