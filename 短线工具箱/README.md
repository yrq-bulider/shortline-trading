# A股量化短线工具箱 - 详细使用说明

## 目录

1. [环境安装](#环境安装)
2. [数据获取](#数据获取)
3. [策略说明](#策略说明)
4. [回测运行](#回测运行)
5. [GitHub项目](#github项目)
6. [表格说明](#表格说明)

---

## 环境安装

### Python环境要求

- Python 3.10 或更高版本
- 推荐使用虚拟环境

### 安装步骤

```bash
# 创建虚拟环境（推荐）
python -m venv quant_env
source quant_env/bin/activate  # Linux/Mac
# 或
quant_env\Scripts\activate  # Windows

# 安装依赖
pip install baostock rqalpha akshare pandas numpy matplotlib
```

### 验证安装

```python
import baostock as bs
import rqalpha

# 登录baostock
lg = bs.login()
print('login respond error_code:', lg.error_code)
print('login respond error_msg:', lg.error_msg)
```

---

## 数据获取

### 使用baostock获取日线数据

```python
import baostock as bs
import pandas as pd

# 登录系统
lg = bs.login()

# 查询日线数据
rs = bs.query_history_k_data_plus(
    "sh.600519",  # 股票代码：sh.沪市 sz.深市
    "date,code,open,high,low,close,volume,amount,adjustflag",
    start_date='2024-01-01',
    end_date='2025-06-01',
    frequency="d",  # d=日线 w=周线 m=月线
    adjustflag="3"   # 1=后复权 2=前复权 3=不复权
)

# 转换为DataFrame
data_list = []
while (rs.error_code == '0') & rs.next():
    data_list.append(rs.get_row_data())
df = pd.DataFrame(data_list, columns=rs.fields)

# 登出
bs.logout()

# 保存到本地
df.to_hdf('data/600519.h5', key='daily')
```

### 常用股票代码

| 股票 | 代码 | 交易所 |
|------|------|--------|
| 贵州茅台 | sh.600519 | 沪市 |
| 宁德时代 | sz.300750 | 深市 |
| 比亚迪 | sz.002594 | 深市 |
| 招商银行 | sh.600036 | 沪市 |
| 中国平安 | sh.601318 | 沪市 |

### 获取分钟数据

```python
rs = bs.query_history_k_data_plus(
    "sz.002594",
    "date,time,code,open,high,low,close,volume,amount",
    start_date='2025-06-01 09:30:00',
    end_date='2025-06-01 15:00:00',
    frequency="5"  # 5=5分钟 15=15分钟 30=30分钟 60=60分钟
)
```

---

## 策略说明

### 策略1：突破策略

**原理：**
- 价格突破N日最高点时买入
- 价格跌破N日最低点时卖出
- 配合成交量放大确认

**适用场景：**
- 趋势明显的股票
- 突破整理形态时

**参数：**
```python
{
    'high_period': 20,       # 最高价周期
    'volume_multiplier': 1.5 # 量能倍数
}
```

**代码位置：** `策略库/突破策略.py`

---

### 策略2：均线策略

**原理：**
- MA5上穿MA20（金叉）= 买入信号
- MA5下穿MA20（死叉）= 卖出信号

**适用场景：**
- 中短线趋势跟踪
- 震荡市需配合其他指标

**参数：**
```python
{
    'short_period': 5,   # 短期均线
    'long_period': 20    # 长期均线
}
```

**代码位置：** `策略库/均线策略.py`

---

### 策略3：打板策略

**原理：**
- 昨日涨停 → 今日开盘买入
- 设定止盈止损
- 尾盘强制平仓

**适用场景：**
- 强势股短线操作
- 涨停板效应明显的市场

**参数：**
```python
{
    'profit_target': 0.07,  # 7%止盈
    'stop_loss': 0.03,      # 3%止损
    'close_time': '14:55'   # 尾盘平仓时间
}
```

**代码位置：** `策略库/打板策略.py`

---

### 策略4：量价策略

**原理：**
- 量增价涨（成交量放大+价格上涨）= 买入
- 量缩价跌（成交量萎缩+价格下跌）= 卖出

**适用场景：**
- 发现主力动向
- 确认趋势强度

**参数：**
```python
{
    'vol_change_rate': 0.5,   # 成交量变化率50%
    'price_change_min': 0.02   # 最小价格变化2%
}
```

**代码位置：** `策略库/量价策略.py`

---

## 回测运行

### 使用rqalpha进行回测

#### 1. 编写策略文件

```python
# my_strategy.py
from rqalpha.api import *

# 初始化参数
def init(context):
    context.short_period = 5
    context.long_period = 20
    context.stock = "sh.600519"

# 策略逻辑
def handle_bar(context, bar_dict):
    stock = context.stock
    prices = history_bars(stock, context.long_period + 1, '1d', 'close')

    if len(prices) < context.long_period + 1:
        return

    ma_short = prices[-context.short_period:].mean()
    ma_long = prices[-context.long_period:].mean()
    ma_short_prev = prices[-context.short_period-1:-1].mean()
    ma_long_prev = prices[-context.long_period-1:-2].mean()

    # 金叉买入
    if ma_short > ma_long and ma_short_prev <= ma_long_prev:
        order_target_percent(stock, 0.95)

    # 死叉卖出
    elif ma_short < ma_long and ma_short_prev >= ma_long_prev:
        order_target_percent(stock, 0)
```

#### 2. 运行回测

```bash
rqalpha backtest -f my_strategy.py -s 2024-01-01 -e 2025-01-01 -o result.pkl
```

#### 3. 查看回测报告

rqalpha会自动生成报告，包含：
- 年化收益率
- 夏普比率
- 最大回撤
- 胜率
- 盈亏比

### 回测参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| initial_cash | 100000 | 初始资金 |
| commission | 0.0003 | 手续费率 |
| slippage | 0.0001 | 滑点 |
| benchmark | 000300.XSHG | 基准（沪深300）|

---

## GitHub项目

### 优质项目索引

详见 `表格/GitHub优质项目索引.csv`

### 项目推荐

#### 1. vnpy（推荐用于实盘）
- Stars: 15000+
- 功能: 全功能量化交易平台
- 支持: 股票、期货、期权、数字货币

#### 2. rqalpha（推荐用于回测）
- Stars: 8000+
- 功能: A股回测引擎
- 特点: 聚宽出品、中文友好

#### 3. akshare（推荐用于数据）
- Stars: 12000+
- 功能: 金融数据获取
- 特点: 覆盖广、更新频繁

#### 4. baostock（推荐用于A股）
- Stars: 4000+
- 功能: A股数据
- 特点: 免费、专注A股

### 学习路径建议

```
第一阶段：数据获取
  baostock/akshare → 获取股票数据

第二阶段：策略学习
  backtrader/rqalpha → 学习策略编写

第三阶段：实盘进阶
  vnpy → 对接券商接口
```

---

## 表格说明

### 表格文件列表

| 文件 | 用途 |
|------|------|
| 策略模板清单.csv | 4个策略的详细参数说明 |
| 回测参数checklist.csv | 回测配置项清单 |
| GitHub优质项目索引.csv | 优质开源项目列表 |
| 操作流程表.csv | 命令与操作对应表 |

### 策略模板清单.csv

包含：
- 策略名称
- 原理简述
- 适用场景
- 参数列表
- 代码文件位置

### 回测参数checklist.csv

包含：
- 参数名称
- 默认值
- 取值范围
- 说明

### GitHub优质项目索引.csv

包含：
- 项目名称
- Stars数量
- 主要语言
- 功能描述
- 适用场景
- GitHub链接
- 学习难度

### 操作流程表.csv

包含：
- 场景（如：新建回测、评估项目）
- 步骤序号
- 具体操作
- 命令
- 预期输出

---

## 常见问题

### Q: baostock数据不准怎么办？
A: 检查股票代码是否正确（sh./sz.前缀），或使用akshare作为备用数据源

### Q: 回测结果和实盘差异大？
A: 考虑加入滑点、手续费模拟，或使用更小的时间周期

### Q: 如何选择策略？
A: 根据股票特性选择：趋势明显的用突破/均线，波动大的用打板

### Q: 如何获取更多GitHub项目？
A: 访问 https://github.com/topics/quantitative-trading
