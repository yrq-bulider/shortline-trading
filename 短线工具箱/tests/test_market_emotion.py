"""v1.3 大盘情绪门测试 — 4 档(hot/normal/cool/cold)分流。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pandas as pd
import pytest


def _make_zt_df(zt_count: int, lianban_count: int, dt_count: int = 0) -> pd.DataFrame:
    """构造一个最小可用的涨停池 df,只填打分用得到的字段。"""
    rows = []
    for i in range(zt_count):
        rows.append({
            '代码': f'600{i:03d}',
            '连板数': 2 if i < lianban_count else 1,
        })
    for i in range(dt_count):
        rows.append({'代码': f'500{i:03d}', '连板数': -1})
    return pd.DataFrame(rows)


def _make_activity_df(zt_count: int) -> pd.DataFrame:
    return pd.DataFrame([
        {'item': '涨停', 'value': str(zt_count)},
        {'item': '上涨', 'value': '2000'},
        {'item': '下跌', 'value': '2500'},
    ])


def test_hot_tier():
    """连板 ≥30 且 涨停 ≥80 → hot,multiplier=1.0。"""
    from 短线工具箱.market_emotion import compute_emotion_tier
    zt_df = _make_zt_df(zt_count=100, lianban_count=35)
    act_df = _make_activity_df(zt_count=100)
    res = compute_emotion_tier(zt_df, act_df)
    assert res['tier'] == 'hot'
    assert res['multiplier'] == 1.0
    assert res['lianban_count'] >= 30
    assert res['zt_count'] >= 80


def test_cool_tier():
    """连板 <10 → cool,multiplier=0.5。"""
    from 短线工具箱.market_emotion import compute_emotion_tier
    zt_df = _make_zt_df(zt_count=50, lianban_count=5)
    act_df = _make_activity_df(zt_count=50)
    res = compute_emotion_tier(zt_df, act_df)
    assert res['tier'] == 'cool'
    assert res['multiplier'] == 0.5


def test_cold_tier():
    """涨停 <30 → cold,multiplier=0.2,优先级高于连板判断。"""
    from 短线工具箱.market_emotion import compute_emotion_tier
    zt_df = _make_zt_df(zt_count=20, lianban_count=8)
    act_df = _make_activity_df(zt_count=20)
    res = compute_emotion_tier(zt_df, act_df)
    assert res['tier'] == 'cold'
    assert res['multiplier'] == 0.2


def test_zt_pool_none():
    """zt_pool_df 为 None → tier='normal',multiplier=1.0,reason 含'数据缺失'。"""
    from 短线工具箱.market_emotion import compute_emotion_tier
    res = compute_emotion_tier(None, None)
    assert res['tier'] == 'normal'
    assert res['multiplier'] == 1.0
    assert '数据缺失' in res['reason'] or '缺失' in res['reason']