"""
突破策略
原理：价格突破N日最高点买入，跌破N日最低点卖出，配合成交量放大确认
适用：趋势明显的股票，突破整理形态时
"""

from rqalpha.api import *
import numpy as np


# 策略参数
def init(context):
    context.high_period = 20           # 最高价周期(天)
    context.volume_multiplier = 1.5    # 量能倍数
    context.stock = "sh.600519"       # 股票代码
    context.position = 0              # 持仓状态


def handle_bar(context, bar_dict):
    stock = context.stock

    # 获取历史数据
    prices = history_bars(stock, context.high_period + 2, '1d', ['close', 'high', 'low', 'volume'])

    if len(prices) < context.high_period + 1:
        return

    # 计算最高价/最低价
    high_list = prices['high']
    low_list = prices['low']
    close_list = prices['close']
    volume_list = prices['volume']

    # 当前价格和成交量
    current_price = close_list[-1]
    current_volume = volume_list[-1]

    # 计算N日最高/最低价（不含今天）
    high_n = np.max(high_list[-context.high_period-1:-1])
    low_n = np.min(low_list[-context.high_period-1:-1])

    # 计算平均成交量
    avg_volume = np.mean(volume_list[:-1])

    # 买入条件：价格突破最高价 且 成交量放大
    if current_price > high_n and current_volume > avg_volume * context.volume_multiplier:
        if context.position == 0:
            # 买入95%仓位
            order_target_percent(stock, 0.95)
            context.position = 1
            logger.info(f"买入信号：价格{current_price}突破{context.high_period}日最高价{high_n}，成交量放大")

    # 卖出条件：价格跌破最低价
    elif current_price < low_n and context.position == 1:
        order_target_percent(stock, 0)
        context.position = 0
        logger.info(f"卖出信号：价格{current_price}跌破{context.high_period}日最低价{low_n}")


# 策略说明
"""
参数说明：
- high_period: 突破周期，越大越稳健但信号越少
- volume_multiplier: 量能倍数，越大要求成交量越大

优势：
- 趋势跟随能力强
- 信号明确

劣势：
- 震荡市容易反复开平仓
- 可能错过最佳买点

优化方向：
- 加入止损
- 配合其他指标过滤
- 调整突破周期
"""
