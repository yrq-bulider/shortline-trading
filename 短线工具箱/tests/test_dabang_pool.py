"""v1.3 涨停板候选池筛选测试。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pandas as pd
import pytest


def _make_row(code='600001', name='测试票', price=15.0, mv_yi=100.0,
              feng='10:30:00', zhaban=0, lianban=1):
    """构造涨停池单行。"""
    return {
        '代码': code, '名称': name,
        '最新价': price,
        '流通市值': mv_yi * 100_000_000,
        '封板时间': feng,
        '炸板次数': zhaban,
        '连板数': lianban,
    }


def _make_score(code='600001', composite=70, earn=60, falsified=False):
    return {
        'code': code, 'composite': composite,
        'subscores': {'tech': 70, 'earn': earn, 'flow': 70, 'news': 70,
                      'earn_reason': '', 'flow_reason': '', 'news_reason': ''},
        'falsified': falsified,
    }


def test_basic_pass():
    """符合全部硬过滤 + 评分 ≥60 → 入池。"""
    from 短线工具箱.dabang_pool import compute_dabang_candidates
    zt_df = pd.DataFrame([_make_row(code='600001')])
    scores = {'600001': _make_score(code='600001', composite=75)}
    out = compute_dabang_candidates(zt_df, scores, top_n=5)
    assert len(out) == 1
    assert out[0]['code'] == '600001'


def test_filter_high_price():
    """价格 >30 → 过滤掉。"""
    from 短线工具箱.dabang_pool import compute_dabang_candidates
    zt_df = pd.DataFrame([_make_row(code='600002', price=35.0)])
    scores = {'600002': _make_score(code='600002', composite=80)}
    out = compute_dabang_candidates(zt_df, scores, top_n=5)
    assert out == []


def test_filter_big_mv():
    """流通市值 >300 亿 → 过滤掉。"""
    from 短线工具箱.dabang_pool import compute_dabang_candidates
    zt_df = pd.DataFrame([_make_row(code='600003', mv_yi=500.0)])
    scores = {'600003': _make_score(code='600003', composite=80)}
    out = compute_dabang_candidates(zt_df, scores, top_n=5)
    assert out == []


def test_filter_late_feng():
    """封板时间 >14:30 → 过滤掉。"""
    from 短线工具箱.dabang_pool import compute_dabang_candidates
    zt_df = pd.DataFrame([_make_row(code='600004', feng='14:45:00')])
    scores = {'600004': _make_score(code='600004', composite=80)}
    out = compute_dabang_candidates(zt_df, scores, top_n=5)
    assert out == []


def test_filter_lianban_ne_1():
    """连板数 ≠1(首板) → 过滤掉(只要首板)。"""
    from 短线工具箱.dabang_pool import compute_dabang_candidates
    zt_df = pd.DataFrame([_make_row(code='600005', lianban=2)])
    scores = {'600005': _make_score(code='600005', composite=80)}
    out = compute_dabang_candidates(zt_df, scores, top_n=5)
    assert out == []


def test_filter_low_4d():
    """4 维综合分 <60 → 过滤掉。"""
    from 短线工具箱.dabang_pool import compute_dabang_candidates
    zt_df = pd.DataFrame([_make_row(code='600006')])
    scores = {'600006': _make_score(code='600006', composite=55)}
    out = compute_dabang_candidates(zt_df, scores, top_n=5)
    assert out == []


def test_filter_leiqu():
    """业绩雷区(falsified=True) → 过滤掉。"""
    from 短线工具箱.dabang_pool import compute_dabang_candidates
    zt_df = pd.DataFrame([_make_row(code='600007')])
    scores = {'600007': _make_score(code='600007', composite=75, falsified=True)}
    out = compute_dabang_candidates(zt_df, scores, top_n=5)
    assert out == []


def test_zt_pool_none():
    """zt_pool_df 为 None → 返回 []。"""
    from 短线工具箱.dabang_pool import compute_dabang_candidates
    out = compute_dabang_candidates(None, {}, top_n=5)
    assert out == []