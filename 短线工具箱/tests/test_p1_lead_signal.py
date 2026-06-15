"""v1.2 P1 先行信号升级测试 — 北向 5→3 日 + 龙虎榜机构席位加成。

注意：主程序模块名以中文开头（筛选明日股票_v1.py），需要从父目录 import。
参见 test_scorer.py 的 sys.path 引导。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 必须在 import 主模块之前设置 argv，防止 argparse 吃掉 pytest 参数
# --mode backtest --days 0 让 backtest_score_history 返回 None（无需 histories 变量）
# 这避免了 scan 模式的 batch_get_history（耗时 2 分钟）和 backtest 模式对 histories 的引用
sys.argv = ['pytest', '--mode', 'backtest', '--days', '0']

import pytest
import pandas as pd


# ============================================================
# 北向 5→3 日测试
# ============================================================
def test_hsgt_3d_window_and_label(monkeypatch):
    """北向应使用 3 日窗口 + reason 标签为 '3日北向'。"""
    # 构造 5 日 fake 数据：第 1-3 日 0.5 亿净流入，第 4-5 日 0
    fake_df = pd.DataFrame({
        '今日资金净流入': [50_000_000, 50_000_000, 50_000_000, 0, 0],
    })

    import 筛选明日股票_v1 as m
    monkeypatch.setattr(m, 'fetch_hsgt', lambda symbol: fake_df)

    score, reason = m.get_hsgt_score('600000')

    # 3 日累计 = 1.5 亿 → 50 + 1.5 * 40 = 110 → 截断到 100
    assert score == 100
    assert '3日北向' in reason
    assert '5日北向' not in reason  # 旧标签不能残留


def test_hsgt_3d_negative(monkeypatch):
    """3 日累计为负 → 标签保留 '流出'。"""
    fake_df = pd.DataFrame({
        '今日资金净流入': [-30_000_000, -30_000_000, -30_000_000, 0, 0],
    })

    import 筛选明日股票_v1 as m
    monkeypatch.setattr(m, 'fetch_hsgt', lambda symbol: fake_df)

    score, reason = m.get_hsgt_score('600000')

    # 3 日累计 = -0.9 亿 → 50 + (-0.9) * 40 = 14
    assert score == 14
    assert '3日北向' in reason
    assert '流出' in reason


# ============================================================
# 龙虎榜机构席位加成测试
# ============================================================
def _setup_lhb_caches(monkeypatch, base_table, inst_table):
    """辅助：把 _LHB_CACHE / _LHB_INST_CACHE 注入到主模块。"""
    import 筛选明日股票_v1 as m
    monkeypatch.setattr(m, '\u005f\u004c\u0048\u0042\u005f\u0043\u0041\u0043\u0048\u0045', base_table)
    monkeypatch.setattr(m, '\u005f\u004c\u0048\u0042\u005f\u004c\u004f\u0041\u0044\u0045\u0044', True)
    monkeypatch.setattr(m, '\u005f\u004c\u0048\u0042\u005f\u0049\u004e\u0053\u0054\u005f\u0043\u0041\u0043\u0048\u0045', inst_table)
    monkeypatch.setattr(m, '\u005f\u004c\u0048\u0042\u005f\u0049\u004e\u0053\u0054\u005f\u004c\u004f\u0041\u0044\u0045\u0044', True)


def test_lhb_inst_50w_bonus(monkeypatch):
    """机构净买 60 万 → +20 分。"""
    base = {"600000": {"\u4ee3\u7801": "600000", "\u9f99\u864e\u699c\u51c0\u4e70\u989d": 200000.0}}
    inst = {"600000": {"\u4ee3\u7801": "600000", "\u673a\u6784\u51c0\u4e70\u989d": 600000.0}}
    _setup_lhb_caches(monkeypatch, base, inst)

    import 筛选明日股票_v1 as m
    score, reason = m.get_lhb_score("600000")
    assert score == 70
    assert "\u673a\u6784\u51c0\u4e7060\u4e07+20" in reason


def test_lhb_inst_10w_bonus(monkeypatch):
    """机构净买 1 万 → +10 分。"""
    base = {"600001": {"\u4ee3\u7801": "600001", "\u9f99\u864e\u699c\u51c0\u4e70\u989d": 100000.0}}
    inst = {"600001": {"\u4ee3\u7801": "600001", "\u673a\u6784\u51c0\u4e70\u989d": 10000.0}}
    _setup_lhb_caches(monkeypatch, base, inst)

    import 筛选明日股票_v1 as m
    score, reason = m.get_lhb_score("600001")
    assert score == 60
    assert "+10" in reason


def test_lhb_not_in_inst_table(monkeypatch):
    """票不在机构表 → 不加成。"""
    base = {"600002": {"\u4ee3\u7801": "600002", "\u9f99\u864e\u699c\u51c0\u4e70\u989d": 100000.0}}
    inst = {}
    _setup_lhb_caches(monkeypatch, base, inst)

    import 筛选明日股票_v1 as m
    score, reason = m.get_lhb_score("600002")
    assert score == 50
    assert "\u673a\u6784" not in reason


def test_lhb_inst_table_load_failure(monkeypatch):
    """机构表拉取失败 → _LHB_INST_CACHE = {} → 跳过加成。

    patch 的是 m.fetch_lhb_inst(已通过 importlib 导入到 v1.py 模块字典),
    不是 ar.call_with_fallback(后者已被闭包捕获,patch 不生效)。
    """
    import 筛选明日股票_v1 as m
    monkeypatch.setattr(m, "fetch_lhb_inst", lambda: None)
    monkeypatch.setattr(m, "_LHB_INST_LOADED", False)
    monkeypatch.setattr(m, "_LHB_INST_CACHE", {})

    table = m._load_lhb_inst_table()
    assert table == {}
