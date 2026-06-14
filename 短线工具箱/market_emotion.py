"""大盘情绪门(v1.3) — 把当日涨停池/市场活跃度归到 4 档,
返回对应的仓位乘数。失败默认 normal/1.0,不影响 v1.2 行为。"""

EMOTION_THRESHOLDS = {
    'hot':  {'lianban_count': 30, 'zt_count': 80},
    'cool': {'lianban_count': 10},
    'cold': {'zt_count': 30},
}

POSITION_MULTIPLIER = {
    'hot':    1.0,
    'normal': 0.8,
    'cool':   0.5,
    'cold':   0.2,
}


def _count_lianban(zt_pool_df) -> int:
    """涨停池里 连板数 ≥ 2 的票数(首板不算连板)。"""
    if zt_pool_df is None or zt_pool_df.empty:
        return 0
    col = next((c for c in zt_pool_df.columns if '连板' in str(c)), None)
    if col is None:
        return 0
    import pandas as pd
    return int((pd.to_numeric(zt_pool_df[col], errors='coerce') >= 2).sum())


def _count_from_activity(activity_df, key: str) -> int:
    """从 stock_market_activity_legu 的 item/value 表里抽取 '涨停'/'跌停' 等数字。"""
    if activity_df is None or activity_df.empty:
        return 0
    try:
        row = activity_df[activity_df['item'] == key]
        if row.empty:
            return 0
        return int(float(row['value'].iloc[0]))
    except Exception:
        return 0


def compute_emotion_tier(zt_pool_df, market_activity_df) -> dict:
    """4 档分流:
      - cold: 涨停 <30 → multiplier 0.2
      - cool: 连板 <10 → 0.5
      - hot: 连板 ≥30 且 涨停 ≥80 → 1.0
      - normal: 其余 → 0.8
    优先级 cold > cool > hot > normal。数据缺失 → normal/1.0。
    返回 dict: tier/multiplier/zt_count/lianban_count/dt_count/reason。"""
    if zt_pool_df is None and market_activity_df is None:
        return {
            'tier': 'normal', 'multiplier': 1.0,
            'zt_count': 0, 'lianban_count': 0, 'dt_count': 0,
            'reason': '数据缺失,默认 normal',
        }

    lianban_count = _count_lianban(zt_pool_df)
    zt_count = _count_from_activity(market_activity_df, '涨停')
    if zt_count == 0 and zt_pool_df is not None:
        zt_count = len(zt_pool_df)
    dt_count = _count_from_activity(market_activity_df, '跌停')

    if zt_count < EMOTION_THRESHOLDS['cold']['zt_count']:
        tier = 'cold'
    elif lianban_count < EMOTION_THRESHOLDS['cool']['lianban_count']:
        tier = 'cool'
    elif (lianban_count >= EMOTION_THRESHOLDS['hot']['lianban_count']
          and zt_count >= EMOTION_THRESHOLDS['hot']['zt_count']):
        tier = 'hot'
    else:
        tier = 'normal'

    return {
        'tier': tier,
        'multiplier': POSITION_MULTIPLIER[tier],
        'zt_count': zt_count,
        'lianban_count': lianban_count,
        'dt_count': dt_count,
        'reason': f'涨停{zt_count} 连板{lianban_count} 跌停{dt_count} → {tier}',
    }