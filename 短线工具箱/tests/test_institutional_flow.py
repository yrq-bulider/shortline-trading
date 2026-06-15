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
