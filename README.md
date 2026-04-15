# Quantitative Trading System

量化交易系统框架 v0.1

## 状态

**Phase 1 - ✅ 完成**（长桥接口 + SQLite 存储）
**Phase 2 - ✅ 完成**（策略引擎 + 回测引擎 + 风控引擎 + 执行引擎）
**Phase 3 - ✅ 完成**（HTTP API + WebSocket）
**Phase 4 - 🔲 待开发**（实盘对接 + 文档完善）

## 快速开始

```bash
cd /Users/Shinji/Coding/QuantitativeTrading

# 安装依赖
pip install -r requirements.txt

# 配置长桥认证（设置环境变量）
export LONGBRIDGE_APP_KEY="your_app_key"
export LONGBRIDGE_APP_SECRET="your_app_secret"
export LONGBRIDGE_ACCESS_TOKEN="your_access_token"

# 下载历史数据
python scripts/download_data.py --symbol 601899.SH --start 2020-01-01

# 查看数据库中的数据
python scripts/download_data.py --symbol 601899.SH --count 5
```

## 目录结构

```
QuantitativeTrading/
├── quant_trading/            # 主包
│   ├── config.py              配置加载
│   ├── const.py               常量定义
│   ├── core/                  # 核心引擎
│   │   └── data_engine.py     数据引擎（实时行情订阅）
│   ├── data/                  # 数据层
│   │   ├── providers/         数据源接口
│   │   │   └── longbridge_provider.py  长桥接口（详细中文注释）
│   │   ├── models/            数据模型
│   │   │   └── market_data.py BarData/Signal/Order/Position 等
│   │   └── storage/           存储层
│   │       └── sqlite_storage.py  SQLite 存储实现（详细中文注释）
│   ├── strategies/            # 策略目录
│   │   └── base_strategy.py   策略基类
│   └── utils/                 # 工具函数
│       └── logger.py          日志工具
├── scripts/
│   └── download_data.py       历史数据下载脚本（详细中文注释）
├── config/
│   └── system_config.yaml     系统配置
├── data/                      # 数据目录（自动创建）
│   └── quant.db               SQLite 数据库
├── docs/
│   └── ARCHITECTURE.md        完整架构文档
└── requirements.txt           Python 依赖
```

## Phase 3-5 完成内容

### 1. HTTP API（FastAPI）

启动服务：
```bash
cd /Users/Shinji/Coding/QuantitativeTrading
uvicorn quant_trading.api.http_api:app --host 0.0.0.0 --port 8000
```

访问 http://localhost:8000/docs 查看 API 文档。

接口列表：
- `GET /status` - 系统状态
- `GET /quotes/{symbol}` - 实时行情
- `GET /bars/{symbol}` - K线数据
- `POST /orders` - 模拟下单
- `POST /backtest` - 运行回测
- `WS /ws` - WebSocket 实时行情订阅

### 2. 示例策略

```python
from quant_trading.strategies.example import MACDCrossStrategy, MeanReversionStrategy

# MACD 策略
strategy = MACDCrossStrategy(params={"fast_period": 12, "slow_period": 26})

# 均值回归策略
strategy = MeanReversionStrategy(params={"period": 20, "std_multiplier": 2.0})
```

### 3. WebSocket 实时行情

```python
# 连接到 ws://localhost:8000/ws
# 订阅: {"action": "subscribe", "symbol": "601899.SH"}
# 取消: {"action": "unsubscribe", "symbol": "601899.SH"}
```

## 下一步

**Phase 6：实盘对接**
- 接入真实券商API（掘金量化、聚宽等）
- 完善风控日志和报警机制
- 编写完整使用文档

### 1. 长桥数据接口（longbridge_provider.py）

```python
from quant_trading.data.providers import LongbridgeProvider

provider = LongbridgeProvider()

# 获取实时行情
quote = provider.get_quote("601899.SH")
print(f"紫金矿业现价: {quote['last_done']}")

# 获取K线
from quant_trading.data.providers.longbridge_provider import Period, AdjustType
bars = provider.get_candlesticks(
    "601899.SH",
    period=Period.Day,
    count=100,
    adjust_type=AdjustType.ForwardAdjust
)

# 获取分时、盘口、资金流向等
intraday = provider.get_intraday("601899.SH")
depth = provider.get_depth("601899.SH")
flow = provider.get_capital_flow("601899.SH")
```

### 2. SQLite 存储（sqlite_storage.py）

```python
from quant_trading.data.storage import SQLiteStorage

storage = SQLiteStorage()

# 保存K线
storage.save_bars("601899.SH", bars)

# 加载K线（按日期范围）
from datetime import date
bars = storage.load_bars(
    "601899.SH",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31)
)

# 加载最近100根
bars = storage.load_bars("601899.SH", count=100)

# 断点续传：查询最新日期
latest = storage.get_latest_bar_date("601899.SH")
print(f"数据库最新日期: {latest}")
```

### 3. 数据下载脚本（download_data.py）

```bash
# 下载单只股票日线（2020年至今）
python scripts/download_data.py --symbol 601899.SH

# 批量下载
python scripts/download_data.py --symbols 601899.SH,600519.SH,000001.SZ

# 下载5分钟线
python scripts/download_data.py --symbol 601899.SH --period 5m --count 500

# 断点续传（自动跳过已有数据）
python scripts/download_data.py --symbol 601899.SH --start 2020-01-01
```

## 下一步

**Phase 2：策略引擎 + 回测引擎**

- 策略基类完善
- 策略引擎（信号生成）
- 回测引擎（历史回测）
- 性能报告生成

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## 开发日志

- 2026-04-15: Phase 0 初始化框架，Phase 1 完成数据层（长桥接口 + SQLite 存储）
