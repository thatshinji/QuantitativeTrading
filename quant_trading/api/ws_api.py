"""
WebSocket 实时行情层
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
基于长桥 WebSocket 的实时行情推送服务。

功能：
- 实时订阅多个股票的行情
- 自动重连
- 行情数据缓存在 DataEngine
- 广播给所有订阅的 WebSocket 客户端

使用方式：
    # 启动服务
    python -m quant_trading.api.ws_api

    # 或在 HTTP API 中一起使用（已包含在 http_api.py 中）
"""

import asyncio
import json
from typing import Dict, List, Set, Optional
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from loguru import logger

# 尝试导入长桥 SDK
try:
    from longbridge.openapi import AsyncQuoteContext, SubType, AdjustType
    HAS_LONGBRIDGE_SDK = True
except ImportError:
    HAS_LONGBRIDGE_SDK = False
    logger.warning("长桥 SDK 未安装，WebSocket 实时行情功能不可用")


class QuoteBroadcaster:
    """
    行情广播器

    负责：
    1. 维护长桥 WebSocket 连接
    2. 订阅股票行情
    3. 缓存最新行情
    4. 广播给所有 WebSocket 客户端
    """

    def __init__(self):
        self._ctx: Optional["AsyncQuoteContext"] = None
        self._connected = False
        self._subscribed_symbols: Set[str] = set()

        # WebSocket 客户端管理
        self._ws_clients: List = []  # 存储 (ws, subscribed_symbols) 元组

        # 行情缓存
        self._quote_cache: Dict[str, Dict] = {}

        # 重连配置
        self._reconnect_interval = 5  # 秒
        self._max_reconnect = 10

    async def connect(self, config: Optional[Dict] = None):
        """
        建立长桥 WebSocket 连接

        Args:
            config: 长桥认证配置
        """
        if not HAS_LONGBRIDGE_SDK:
            logger.error("长桥 SDK 未安装，无法连接")
            return False

        config = config or {}
        from longbridge.openapi import Config

        lb_config = Config(
            app_key=config.get("app_key", ""),
            app_secret=config.get("app_secret", ""),
            access_token=config.get("access_token", ""),
        )

        try:
            self._ctx = await AsyncQuoteContext.create(lb_config)

            # 设置行情回调
            self._ctx.set_on_quote(self._on_quote_callback)

            self._connected = True
            logger.info("长桥 WebSocket 连接成功")
            return True

        except Exception as e:
            logger.error(f"长桥 WebSocket 连接失败: {e}")
            self._connected = False
            return False

    def _on_quote_callback(self, symbol: str, event):
        """
        行情回调

        Args:
            symbol: 股票代码
            event: 行情事件（PushQuote 类型）
        """
        # 更新缓存
        quote = {
            "symbol": symbol,
            "last_done": float(event.last_done) if event.last_done else 0.0,
            "prev_close": float(event.prev_close_price) if event.prev_close_price else 0.0,
            "open": float(event.open) if event.open else 0.0,
            "high": float(event.high) if event.high else 0.0,
            "low": float(event.low) if event.low else 0.0,
            "volume": int(event.volume) if event.volume else 0,
            "turnover": float(event.turnover) if event.turnover else 0.0,
            "timestamp": datetime.now().isoformat(),
        }
        self._quote_cache[symbol] = quote

        # 广播给订阅的客户端
        asyncio.create_task(self._broadcast(quote, symbol))

    async def _broadcast(self, quote: Dict, symbol: str):
        """
        广播行情给订阅的客户端

        Args:
            quote: 行情数据
            symbol: 股票代码
        """
        for ws, symbols in self._ws_clients:
            if symbol in symbols:
                try:
                    await ws.send_json(quote)
                except Exception as e:
                    logger.error(f"WebSocket 发送失败: {e}")

    async def subscribe(self, symbols: List[str]):
        """
        订阅股票行情

        Args:
            symbols: 股票代码列表
        """
        if not self._connected or not self._ctx:
            logger.error("未连接长桥 WebSocket")
            return False

        try:
            await self._ctx.subscribe(symbols, [SubType.Quote])
            self._subscribed_symbols.update(symbols)
            logger.info(f"订阅成功: {symbols}")
            return True
        except Exception as e:
            logger.error(f"订阅失败: {e}")
            return False

    async def unsubscribe(self, symbols: List[str]):
        """
        取消订阅

        Args:
            symbols: 股票代码列表
        """
        if not self._connected or not self._ctx:
            return

        try:
            await self._ctx.unsubscribe(symbols, [SubType.Quote])
            self._subscribed_symbols.difference_update(symbols)
            logger.info(f"取消订阅: {symbols}")
        except Exception as e:
            logger.error(f"取消订阅失败: {e}")

    def add_client(self, ws, symbols: List[str] = None):
        """
        添加 WebSocket 客户端

        Args:
            ws: WebSocket 连接
            symbols: 初始订阅列表
        """
        self._ws_clients.append((ws, set(symbols or [])))

    def remove_client(self, ws):
        """
        移除 WebSocket 客户端

        Args:
            ws: WebSocket 连接
        """
        self._ws_clients = [(w, s) for w, s in self._ws_clients if w != ws]

    def get_cache(self, symbol: str) -> Optional[Dict]:
        """获取缓存的行情"""
        return self._quote_cache.get(symbol)

    async def reconnect(self):
        """尝试重连"""
        for i in range(self._max_reconnect):
            logger.info(f"尝试重连 ({i+1}/{self._max_reconnect})...")
            if await self.connect():
                # 重连后重新订阅
                if self._subscribed_symbols:
                    await self.subscribe(list(self._subscribed_symbols))
                return True
            await asyncio.sleep(self._reconnect_interval)

        logger.error("重连失败")
        return False


# 全局广播器实例
_broadcaster: Optional[QuoteBroadcaster] = None


def get_broadcaster() -> QuoteBroadcaster:
    """获取全局广播器实例"""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = QuoteBroadcaster()
    return _broadcaster


async def start_realtime_service(config: Optional[Dict] = None):
    """
    启动实时行情服务

    Args:
        config: 长桥认证配置
    """
    broadcaster = get_broadcaster()
    success = await broadcaster.connect(config)

    if not success:
        logger.error("实时行情服务启动失败")
        return False

    logger.info("实时行情服务已启动")
    return True


# ============== 独立的测试脚本 ==============

if __name__ == "__main__" and HAS_LONGBRIDGE_SDK:
    async def test():
        """测试实时行情"""
        broadcaster = get_broadcaster()

        # 连接
        await broadcaster.connect()

        if broadcaster._connected:
            # 订阅
            await broadcaster.subscribe(["601899.SH", "700.HK"])

            # 保持运行
            logger.info("按 Ctrl+C 退出")
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                logger.info("退出")

    asyncio.run(test())
