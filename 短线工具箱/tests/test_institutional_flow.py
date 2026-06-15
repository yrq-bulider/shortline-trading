"""v2.0 机构流出深层次信号测试 — 25+ 用例覆盖 4 子分 + 综合 + 主力分单。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pandas as pd
import pytest


def _make_dzjy_row(code='600001', rate=5.0, seller='营业部A'):
    return {
        '证券代码': code, '证券简称': '测试票',
        '折溢率': rate, '卖方营业部': seller,
    }


# score_dzjy 测试
def test_dzjy_strong_discount_with_inst():
    """折价 12% + 卖方'机构专用' → 25-10=15 分,reason 含'机构席位'。"""
    from 短线工具箱.institutional_flow import score_dzjy
    df = pd.DataFrame([_make_dzjy_row(rate=12.0, seller='机构专用席位')])
    df['_code6'] = df['证券代码']
    score, reason = score_dzjy('600001', df)
    assert score == 15
    assert '机构' in reason


def test_dzjy_mild_discount():
    """折价 6% → 35 分,reason 含'折价'。"""
    from 短线工具箱.institutional_flow import score_dzjy
    df = pd.DataFrame([_make_dzjy_row(rate=6.0)])
    df['_code6'] = df['证券代码']
    score, reason = score_dzjy('600001', df)
    assert score == 35
    assert '折价' in reason


def test_dzjy_premium():
    """溢价 5% → 70 分。"""
    from 短线工具箱.institutional_flow import score_dzjy
    df = pd.DataFrame([_make_dzjy_row(rate=-5.0)])
    df['_code6'] = df['证券代码']
    score, reason = score_dzjy('600001', df)
    assert score == 70


def test_dzjy_no_records():
    """该 code 不在 df 中 → 55 分,reason 含'无大宗'。"""
    from 短线工具箱.institutional_flow import score_dzjy
    df = pd.DataFrame([_make_dzjy_row(code='600002')])
    df['_code6'] = df['证券代码']
    score, reason = score_dzjy('600001', df)
    assert score == 55
    assert '无大宗' in reason


def test_dzjy_data_missing():
    """df=None → 50 分,reason 含'缺失'。"""
    from 短线工具箱.institutional_flow import score_dzjy
    score, reason = score_dzjy('600001', None)
    assert score == 50
    assert '缺失' in reason


# ============================================================
# score_margin 测试
# ============================================================
def _make_margin_row(code='600001', balance=1e9):
    """构造融资融券单行(单位:元)。"""
    return {'标的代码': code, '融资余额': balance}


def test_margin_sharp_decline():
    """融资余额周降 12% → 25 分(杠杆踩踏)。"""
    from 短线工具箱.institutional_flow import score_margin
    df = pd.DataFrame([_make_margin_row(balance=8.8e8)])
    df['_code6'] = df['标的代码']
    score, reason = score_margin('600001', df, decline_pct=12.0)
    assert score == 25
    assert '降' in reason or '踩踏' in reason


def test_margin_mild_decline():
    """周降 5% → 40 分。"""
    from 短线工具箱.institutional_flow import score_margin
    df = pd.DataFrame([_make_margin_row()])
    df['_code6'] = df['标的代码']
    score, reason = score_margin('600001', df, decline_pct=5.0)
    assert score == 40


def test_margin_increase():
    """周升 8% → 70 分(杠杆加仓)。"""
    from 短线工具箱.institutional_flow import score_margin
    df = pd.DataFrame([_make_margin_row()])
    df['_code6'] = df['标的代码']
    score, reason = score_margin('600001', df, decline_pct=-8.0)
    assert score == 70


def test_margin_data_missing():
    """df=None → 50 分。"""
    from 短线工具箱.institutional_flow import score_margin
    score, reason = score_margin('600001', None)
    assert score == 50
    assert '缺失' in reason


# ============================================================
# score_holder 测试
# ============================================================
def _make_holder_row(code='600001', holder_count=10000):
    """构造股东户数单行。"""
    return {'代码': code, '股东户数': holder_count}


def test_holder_big_disperse():
    """户数环比 +25% → 25 分(筹码大幅分散)。"""
    from 短线工具箱.institutional_flow import score_holder
    df = pd.DataFrame([_make_holder_row()])
    df['_code6'] = df['代码']
    score, reason = score_holder('600001', df, change_pct=25.0)
    assert score == 25
    assert '分散' in reason


def test_holder_mild_disperse():
    """户数 +12% → 35 分。"""
    from 短线工具箱.institutional_flow import score_holder
    df = pd.DataFrame([_make_holder_row()])
    df['_code6'] = df['代码']
    score, reason = score_holder('600001', df, change_pct=12.0)
    assert score == 35


def test_holder_concentrate():
    """户数 -15% → 65 分(筹码集中)。"""
    from 短线工具箱.institutional_flow import score_holder
    df = pd.DataFrame([_make_holder_row()])
    df['_code6'] = df['代码']
    score, reason = score_holder('600001', df, change_pct=-15.0)
    assert score == 65
    assert '集中' in reason


def test_holder_data_missing():
    """df=None → 50 分。"""
    from 短线工具箱.institutional_flow import score_holder
    score, reason = score_holder('600001', None)
    assert score == 50
    assert '缺失' in reason


# ============================================================
# score_restricted 测试
# ============================================================
def _make_restricted_row(code='600001', pct=1.0):
    """构造解禁单行(解禁数量/总股本比例,单位:%)。"""
    return {'代码': code, '占总股本比例': pct}


def test_restricted_heavy():
    """30 日内解禁 12% → 20 分(强卖压)。"""
    from 短线工具箱.institutional_flow import score_restricted
    df = pd.DataFrame([_make_restricted_row(pct=12.0)])
    df['_code6'] = df['代码']
    score, reason = score_restricted('600001', df, pct_30d=12.0)
    assert score == 20
    assert '12' in reason or '卖压' in reason or '解禁' in reason


def test_restricted_mild():
    """30 日解禁 6% → 35 分。"""
    from 短线工具箱.institutional_flow import score_restricted
    df = pd.DataFrame([_make_restricted_row(pct=6.0)])
    df['_code6'] = df['代码']
    score, reason = score_restricted('600001', df, pct_30d=6.0)
    assert score == 35


def test_restricted_none():
    """30 日解禁 0% → 75 分。"""
    from 短线工具箱.institutional_flow import score_restricted
    df = pd.DataFrame([_make_restricted_row()])
    df['_code6'] = df['代码']
    score, reason = score_restricted('600001', df, pct_30d=0.0)
    assert score == 75


def test_restricted_data_missing():
    """df=None → 50 分。"""
    from 短线工具箱.institutional_flow import score_restricted
    score, reason = score_restricted('600001', None)
    assert score == 50
    assert '缺失' in reason


# ============================================================
# compute_institutional_score 测试
# ============================================================
def test_inst_all_pass():
    """4 子分都好(80+70+75+75)→ 综合分 ≥ 70。"""
    from 短线工具箱.institutional_flow import compute_institutional_score
    dzjy = pd.DataFrame([_make_dzjy_row(rate=-8.0)])  # 溢价 8% → 80
    dzjy['_code6'] = dzjy['证券代码']
    holder = pd.DataFrame([_make_holder_row()])
    holder['_code6'] = holder['代码']
    restricted = pd.DataFrame([_make_restricted_row()])
    restricted['_code6'] = restricted['代码']
    margin = pd.DataFrame([_make_margin_row()])
    margin['_code6'] = margin['标的代码']

    score, subs = compute_institutional_score(
        '600001', dzjy, margin, holder, restricted,
        margin_decline_pct=-8.0, holder_change_pct=-25.0, restricted_pct_30d=0.0,
    )
    assert score >= 70
    assert 'dzjy' in subs and 'margin' in subs and 'holder' in subs and 'restricted' in subs


def test_inst_all_fail():
    """4 子分都差(15+25+25+20)→ 综合分 ≤ 35。"""
    from 短线工具箱.institutional_flow import compute_institutional_score
    dzjy = pd.DataFrame([_make_dzjy_row(rate=12.0, seller='机构专用席位')])  # 15
    dzjy['_code6'] = dzjy['证券代码']
    holder = pd.DataFrame([_make_holder_row()])
    holder['_code6'] = holder['代码']
    restricted = pd.DataFrame([_make_restricted_row()])
    restricted['_code6'] = restricted['代码']
    margin = pd.DataFrame([_make_margin_row()])
    margin['_code6'] = margin['标的代码']

    score, subs = compute_institutional_score(
        '600001', dzjy, margin, holder, restricted,
        margin_decline_pct=15.0, holder_change_pct=25.0, restricted_pct_30d=12.0,
    )
    assert score <= 35


# ============================================================
# score_main_force_split 测试
# ============================================================
def _make_fund_flow_row(code='600001', super_large=1e7, large=5e6, mid=-1e6, small=2e6):
    """构造主力分单单行(单位:元,正数=流入,负数=流出)。"""
    return {
        '代码': code,
        '特大单净额': super_large, '大单净额': large,
        '中单净额': mid, '小单净额': small,
    }


def test_split_institutional_buying():
    """特大单+大单流入,中单+小单流出 → 70 分(机构吸筹)。"""
    from 短线工具箱.institutional_flow import score_main_force_split
    df = pd.DataFrame([_make_fund_flow_row(super_large=1e8, large=5e7, mid=-1e7, small=-2e7)])
    df['_code6'] = df['代码']
    score, reason = score_main_force_split('600001', df)
    assert score >= 60
    assert '吸筹' in reason or '流入' in reason or '大单' in reason


def test_split_institutional_selling():
    """特大单+大单流出,中单+小单流入 → 30 分(派发给散户)。"""
    from 短线工具箱.institutional_flow import score_main_force_split
    df = pd.DataFrame([_make_fund_flow_row(super_large=-1e8, large=-5e7, mid=1e7, small=2e7)])
    df['_code6'] = df['代码']
    score, reason = score_main_force_split('600001', df)
    assert score <= 40
    assert '派发' in reason or '流出' in reason or '大单' in reason


def test_split_mixed():
    """特大单流入但大单流出 → 50 分(混合信号)。"""
    from 短线工具箱.institutional_flow import score_main_force_split
    df = pd.DataFrame([_make_fund_flow_row(super_large=1e8, large=-5e7, mid=1e7, small=-2e7)])
    df['_code6'] = df['代码']
    score, reason = score_main_force_split('600001', df)
    assert 40 <= score <= 60


def test_split_no_records():
    """code 不在 df 中 → 55 分。"""
    from 短线工具箱.institutional_flow import score_main_force_split
    df = pd.DataFrame([_make_fund_flow_row(code='600002')])
    df['_code6'] = df['代码']
    score, reason = score_main_force_split('600001', df)
    assert score == 55


def test_split_data_missing():
    """df=None → 50 分。"""
    from 短线工具箱.institutional_flow import score_main_force_split
    score, reason = score_main_force_split('600001', None)
    assert score == 50
    assert '缺失' in reason
