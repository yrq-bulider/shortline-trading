"""
均线策略
原理：MA5上穿MA20(金叉)买入，MA5下穿MA20(死叉)卖出
适用：中短线趋势跟踪，震荡市需配合其他指标
"""

from rqalpha.api import *
import numpy as np


def init(context):
    context.short_period = 5      # 短期均线周期
    context.long_period = 20     # 长期均线周期
    context.stock = "sh.600519"  # 股票代码
    context.position = 0         # 持仓状态


def handle_bar(context, bar_dict):
    stock = context.stock

    # 获取历史数据
    prices = history_bars(stock, context.long_period + 1, '1d', 'close')

    if len(prices) < context.long_period + 1:
        return

    # 计算均线
    ma_short = np.mean(prices[-context.short_period:])
    ma_long = np.mean(prices[-context.long_period:])

    # 前一交易日均线值
    ma_short_prev = np.mean(prices[-context.short_period-1:-1])
    ma_long_prev = np.mean(prices[-context.long_period-1:-1])

    current_price = prices[-1]

    # 金叉买入：短期均线上穿长期均线
    if ma_short > ma_long and ma_short_prev <= ma_long_prev:
        if context.position == 0:
            order_target_percent(stock, 0.95)
            context.position = 1
            logger.info(f"买入信号(金叉)：MA5={ma_short:.2f}上穿MA20={ma_long:.2f}，价格={current_price}")

    # 死叉卖出：短期均线下穿长期均线
    elif ma_short < ma_long and ma_short_prev >= ma_long_prev:
        if context.position == 1:
            order_target_percent(stock, 0)
            context.position = 0
            logger.info(f"卖出信号(死叉)：MA5={ma_short:.2f}下穿MA20={ma_long:.2f}，价格={current_price}")


# 策略说明
"""
参数说明：
- short_period: 短期均线周期，越短越敏感
- long_period: 长期均线周期，越长越稳健

优势：
- 简单易理解
- 信号明确
- 趋势跟随效果好

劣势：
- 滞后性强
- 震荡市容易反复交易
- 可能产生较多无效信号

优化方向：
- 增加其他指标过滤（如RSI、MACD）
- 加入止损止盈
- 调整均线周期组合（MA10/MA30等）
"""
