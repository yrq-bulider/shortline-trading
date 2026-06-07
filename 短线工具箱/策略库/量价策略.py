"""
量价策略
原理：量增价涨买入，量缩价跌卖出
适用：发现主力动向，确认趋势强度
"""

from rqalpha.api import *
import numpy as np


def init(context):
    context.vol_change_rate = 0.5     # 成交量放大变化率(50%)
    context.vol_shrink_rate = 0.3    # 成交量萎缩变化率(30%)
    context.price_change_min = 0.02  # 最小价格变化(2%)
    context.stock = "sh.600519"     # 股票代码
    context.position = 0             # 持仓状态


def handle_bar(context, bar_dict):
    stock = context.stock

    # 获取历史数据（需要足够的长度来计算变化率）
    prices = history_bars(stock, 10, '1d', ['close', 'volume'])

    if len(prices) < 10:
        return

    # 当前价格和成交量
    current_price = prices[-1]['close']
    current_volume = prices[-1]['volume']

    # 前一日价格和成交量
    prev_price = prices[-2]['close']
    prev_volume = prices[-2]['volume']

    # 计算变化率
    price_change = (current_price - prev_price) / prev_price
    volume_change = (current_volume - prev_volume) / prev_volume

    # 买入条件：量增价涨
    # 成交量放大超过50% 且 价格上涨超过2%
    is_price_up = price_change >= context.price_change_min
    is_volume_up = volume_change >= context.vol_change_rate

    if is_price_up and is_volume_up and context.position == 0:
        order_target_percent(stock, 0.95)
        context.position = 1
        logger.info(f"买入信号：价格上涨{price_change*100:.2f}%，成交量放大{volume_change*100:.2f}%")

    # 卖出条件：量缩价跌
    # 成交量萎缩超过30% 且 价格下跌超过2%
    is_price_down = price_change <= -context.price_change_min
    is_volume_down = volume_change <= -context.vol_shrink_rate

    if is_price_down and is_volume_down and context.position == 1:
        order_target_percent(stock, 0)
        context.position = 0
        logger.info(f"卖出信号：价格下跌{abs(price_change)*100:.2f}%，成交量萎缩{abs(volume_change)*100:.2f}%")


# 策略说明
"""
参数说明：
- vol_change_rate: 成交量放大变化率，值越大要求放量越明显
- vol_shrink_rate: 成交量萎缩变化率，值越大要求缩量越明显
- price_change_min: 最小价格变化，值越大要求涨幅越大

优势：
- 反映资金动向
- 配合价格变化确认
- 容易理解

劣势：
- 短期波动可能造成假信号
- 震荡市中频繁交易
- 需要配合趋势判断

优化方向：
- 加入均线趋势过滤
- 调整变化率参数
- 加入持仓时间限制
"""
