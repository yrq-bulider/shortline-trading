"""
打板策略
原理：昨日涨停股今日开盘买入，设定固定止盈止损，尾盘强制平仓
适用：强势股短线操作，涨停板效应明显时
"""

from rqalpha.api import *
import pandas as pd


def init(context):
    context.profit_target = 0.07    # 7%止盈
    context.stop_loss = 0.03        # 3%止损
    context.close_time = "14:55"    # 尾盘平仓时间
    context.stock = "sh.600519"     # 股票代码
    context.position = 0            # 持仓状态
    context.buy_price = 0           # 买入价格
    context.is_yesterday_limit_up = False  # 昨日是否涨停


def handle_bar(context, bar_dict):
    stock = context.stock
    current_time = str(context.now)

    # 获取昨日收盘数据
    prices = history_bars(stock, 2, '1d', ['close', 'high', 'low', 'volume'])

    if len(prices) < 2:
        return

    yesterday_close = prices[-2]['close']
    yesterday_high = prices[-2]['high']
    today_open = prices[-1]['open']
    current_price = prices[-1]['close']

    # 判断昨日是否涨停（收盘价等于最高价，且涨幅接近10%）
    prev_close = prices[-3]['close'] if len(prices) >= 3 else yesterday_close
    is_limit_up = (yesterday_close >= yesterday_high * 0.999) and (yesterday_close / prev_close > 1.09)

    # 买入逻辑：昨日涨停，今日开盘买入
    if is_limit_up and context.position == 0:
        # 开盘买入
        order_target_percent(stock, 0.95)
        context.position = 1
        context.buy_price = today_open
        context.is_yesterday_limit_up = True
        logger.info(f"买入：昨日涨停，今日开盘{today_open}买入，涨停价={yesterday_high}")

    # 止盈止损逻辑
    if context.position == 1 and context.buy_price > 0:
        profit_ratio = (current_price - context.buy_price) / context.buy_price

        # 止损
        if profit_ratio <= -context.stop_loss:
            order_target_percent(stock, 0)
            context.position = 0
            logger.info(f"止损：当前价格{current_price}，亏损{profit_ratio*100:.2f}%")

        # 止盈
        elif profit_ratio >= context.profit_target:
            order_target_percent(stock, 0)
            context.position = 0
            logger.info(f"止盈：当前价格{current_price}，盈利{profit_ratio*100:.2f}%")

    # 尾盘强制平仓
    if current_time >= context.close_time and context.position == 1:
        order_target_percent(stock, 0)
        context.position = 0
        context.is_yesterday_limit_up = False
        logger.info(f"尾盘平仓：价格{current_price}")


# 策略说明
"""
参数说明：
- profit_target: 止盈比例，建议7-10%
- stop_loss: 止损比例，建议3-5%
- close_time: 尾盘平仓时间，建议14:50-14:55

优势：
- 捕捉强势股连续上涨
- 止盈止损明确
- 操作简单

劣势：
- 涨停股选择难度大
- 次日可能低开低走
- 风险较高

注意事项：
- 仅适用于热点板块强势股
- 需要配合市场情绪判断
- 建议仓位控制

优化方向：
- 加入板块热度过滤
- 加入大盘指数确认
- 调整止盈止损比例
"""
