# Quantitative Trading System - 工程架构文档

> 版本：v0.1 | 日期：2026-04-15 | 状态：框架设计阶段

---

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        QUANT TRADING SYSTEM                      │
├──────────┬──────────┬──────────┬──────────┬─────────────────────┤
│  Data    │ Strategy │ Execution│  Risk    │  Backtest           │
│  Engine  │ Engine   │ Engine   │  Engine  │  Engine             │
├──────────┴──────────┴──────────┴──────────┴─────────────────────┤
│                     Core / Commons / Utils                        │
├─────────────────────────────────────────────────────────────────┤
│                     Interface Layer (API)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 目录结构

```
/Users/Shinji/Coding/
├── quant_trading/                 # 主包
│   ├── __init__.py
│   ├── config.py                  # 全局配置
│   ├── const.py                   # 常量定义
│   │
│   ├── core/                     # 核心引擎
│   │   ├── __init__.py
│   │   ├── data_engine.py        # 数据引擎（采集/存储/读取）
│   │   ├── strategy_engine.py    # 策略引擎（信号生成）
│   │   ├── execution_engine.py  # 执行引擎（订单/报单）
│   │   ├── risk_engine.py       # 风控引擎（仓位/止损/保证金）
│   │   └── backtest_engine.py   # 回测引擎
│   │
│   ├── strategies/               # 策略目录
│   │   ├── __init__.py
│   │   ├── base_strategy.py      # 策略基类
│   │   ├── example/             # 示例策略
│   │   │   ├── __init__.py
│   │   │   ├── macd_cross.py     # MACD 交叉策略
│   │   │   └── mean_rev.py       # 均值回归策略
│   │   └── user/                # 用户自定义策略
│   │       ├── __init__.py
│   │       └── .gitkeep
│   │
│   ├── data/                    # 数据层
│   │   ├── __init__.py
│   │   ├── providers/           # 数据源
│   │   │   ├── __init__.py
│   │   │   ├── longbridge.py    # 长桥数据接口
│   │   │   ├── wencai.py        # 问财选股接口
│   │   │   └── tushare.py       # Tushare 接口（备用）
│   │   ├── models/              # 数据模型
│   │   │   ├── __init__.py
│   │   │   ├── market_data.py   # 市场行情模型
│   │   │   ├── fundamentals.py  # 基本面数据模型
│   │   │   └── portfolio.py     # 组合/持仓模型
│   │   └── storage/             # 数据存储
│   │       ├── __init__.py
│   │       ├── sqlite_storage.py
│   │       └── csv_storage.py
│   │
│   ├── execution/               # 执行层
│   │   ├── __init__.py
│   │   ├── brokers/            # 券商接口
│   │   │   ├── __init__.py
│   │   │   ├── abstract_broker.py
│   │   │   └── mock_broker.py   # 模拟券商（回测用）
│   │   ├── order.py            # 订单模型
│   │   └── trade_logger.py     # 交易日志
│   │
│   ├── risk/                   # 风控层
│   │   ├── __init__.py
│   │   ├── position_manager.py # 仓位管理
│   │   ├── stop_loss.py        # 止损管理
│   │   └── exposure.py         # 敞口管理
│   │
│   ├── utils/                  # 工具函数
│   │   ├── __init__.py
│   │   ├── datetime_utils.py   # 时间工具
│   │   ├── math_utils.py       # 数学工具
│   │   ├── logger.py           # 日志工具
│   │   └── decorators.py       # 装饰器
│   │
│   └── api/                    # API 层（对外接口）
│       ├── __init__.py
│       ├── http_api.py         # HTTP API
│       └── ws_api.py           # WebSocket 实时行情
│
├── tests/                      # 测试
│   ├── __init__.py
│   ├── test_data_engine.py
│   ├── test_strategy_engine.py
│   ├── test_risk_engine.py
│   └── test_backtest.py
│
├── scripts/                    # 脚本
│   ├── run_backtest.py         # 运行回测
│   ├── run_live.py             # 运行实盘
│   ├── init_database.py        # 初始化数据库
│   └── download_data.py         # 数据下载
│
├── config/                     # 配置文件
│   ├── strategy_config.yaml    # 策略参数配置
│   ├── broker_config.yaml      # 券商配置
│   └── system_config.yaml      # 系统配置
│
├── data/                       # 数据目录
│   ├── historical/             # 历史数据
│   │   ├── daily/              # 日线数据
│   │   ├── minute/             # 分钟数据
│   │   └── fundamentals/       # 基本面数据
│   └── cache/                  # 缓存数据
│
├── logs/                       # 日志目录
│   ├── trades/                 # 交易日志
│   ├── backtest/               # 回测日志
│   └── system/                 # 系统日志
│
├── docs/                       # 文档
│   ├── ARCHITECTURE.md         # 本文档
│   ├── STRATEGY_GUIDE.md       # 策略编写指南
│   └── API_REFERENCE.md        # API 参考
│
├── requirements.txt            # Python 依赖
├── .gitignore
├── README.md
└── ARCHITECTURE.md             # 指向 docs/ARCHITECTURE.md
```

---

## 3. 核心模块说明

### 3.1 Data Engine（数据引擎）

负责所有数据的采集、存储、读取。

```
数据源 → Data Engine → SQLite/CSV → 策略/回测
```

**职责：**
- 实时行情订阅（长桥 WebSocket）
- 历史数据下载与存储
- 基本面数据获取
- 数据清洗与对齐

### 3.2 Strategy Engine（策略引擎）

负责信号生成，与执行层解耦。

```
Data Engine → Strategy Engine → Signal → Execution Engine
```

**信号结构：**
```python
Signal {
    symbol: str          # 股票代码
    direction: +1/-1     # 买入/卖出
    size: float          # 数量比例 0~1
    price: float         # 预期价格
    reason: str          # 信号原因
    confidence: float    # 置信度 0~1
}
```

### 3.3 Execution Engine（执行引擎）

负责订单发送、报单回报处理。

```
Strategy Engine → Execution Engine → Broker → 交易所
```

**职责：**
- 订单路由（按股票/账户分仓）
- 滑点控制
- 成交回报处理
- 失败重试逻辑

### 3.4 Risk Engine（风控引擎）

所有订单在下发前必须经过风控引擎审核。

```
Strategy → Risk Engine → Execution
```

**风控规则：**
- 单股仓位上限
- 单日最大亏损
- 行业敞口限制
- 止损触发自动平仓

### 3.5 Backtest Engine（回测引擎）

使用历史数据模拟交易，评估策略表现。

```
Historical Data + Strategy → Backtest Engine → Performance Report
```

**评估指标：**
- 年化收益率
- 夏普比率
- 最大回撤
- 胜率/盈亏比

---

## 4. 数据流

### 4.1 实盘模式

```
长桥WebSocket
    ↓
Data Engine（缓存 + 广播）
    ↓
Strategy Engine（生成信号）
    ↓
Risk Engine（风控审核）
    ↓
Execution Engine（发送订单）
    ↓
Broker（券商执行）
    ↓
成交回报 → Portfolio 更新 → 日志记录
```

### 4.2 回测模式

```
历史数据（CSV/SQLite）
    ↓
Backtest Engine（模拟时间轴）
    ↓
Strategy Engine
    ↓
Risk Engine（历史风控）
    ↓
Execution Engine（模拟成交）
    ↓
Performance Report
```

---

## 5. 策略编写规范

所有策略继承 `BaseStrategy`，实现以下方法：

```python
class BaseStrategy(ABC):
    name: str = "base_strategy"
    
    def on_init(self, context):
        """策略初始化"""
        pass
    
    def on_data(self, context, data: MarketData) -> Signal | None:
        """数据到达时调用，返回信号或空"""
        raise NotImplementedError
    
    def on_bar(self, context, bar: BarData):
        """K线闭合时调用（用于择时策略）"""
        pass
    
    def on_fill(self, context, fill: FillData):
        """成交回报"""
        pass
```

---

## 6. 配置管理

所有敏感配置（账号、密码、API Key）通过环境变量或 YAML 文件管理，不硬编码。

```yaml
# config/system_config.yaml
system:
  mode: backtest  # backtest / paper / live
  log_level: INFO
  
data:
  providers:
    - longbridge
    - wencai
  
risk:
  max_position_per_stock: 0.1      # 单股最大仓位 10%
  max_daily_loss: 0.02             # 单日最大亏损 2%
  max_total_exposure: 0.8          # 最大总仓位 80%
```

---

## 7. 开发阶段规划

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 0 | 框架搭建、目录结构、基础类 | ✅ 完成 |
| Phase 1 | 数据层（长桥接口、SQLite 存储）| ✅ 完成 |
| Phase 2 | 策略引擎、回测引擎 | ✅ 完成 |
| Phase 3 | 风控引擎、执行层 | ✅ 完成 |
| Phase 4 | HTTP API + WebSocket | ✅ 完成 |
| Phase 5 | 示例策略（MACD、均值回归）| ✅ 完成 |
| Phase 6 | 实盘对接 | 🔲 |

---

## 8. 技术栈

- **语言：** Python 3.11+
- **数据存储：** SQLite（轻量）、Parquet（历史数据）
- **回测框架：** 自研（基于 Backtrader 思想）
- **数据源：** 长桥 API、问财、TuShare
- **日志：** Python logging + JSON 输出
- **配置：** PyYAML
- **HTTP 服务：** FastAPI
- **实时行情：** WebSocket（长桥）

---

_Architecture designed by Ayanami Rei. Build it, don't just think about it._
