"""v2.0 机构流出深层次信号 — 大宗/主力分单/融资/股东户数/解禁。

设计原则:
- 5 子分独立计分,加权合成机构行为维 0-100
- 任一数据源拉取失败 → 该子分返回 50(中位),不影响总分
- 输出包含每个子分的 reason,用于证伪门 + 报告展示
"""
import pandas as pd
from typing import Optional, Tuple


# 子分 1: 大宗交易折价 + 卖方席位
def score_dzjy(code6: str, dzjy_df: Optional[pd.DataFrame]) -> Tuple[int, str]:
    """大宗交易子分 0-100。
    评分逻辑:
      - 平均折价率 >= 10% → 25 分(强出货)
      - 平均折价率 5~10% → 35 分
      - 平均折价率 0~5% → 45 分(微折)
      - 溢价 0~5% → 70 分
      - 溢价 >= 5% → 80 分(强接货)
      - 该 code 无记录 → 55 分(中性)
      - df 缺失 → 50 分(兜底)
    卖方席位含'机构专用' → 额外 -10 分(强出货证据)
    """
    if dzjy_df is None or dzjy_df.empty:
        return 50, '大宗数据缺失'

    code_col = '_code6' if '_code6' in dzjy_df.columns else '证券代码'
    rows = dzjy_df[dzjy_df[code_col].astype(str).str.zfill(6) == str(code6).zfill(6)]
    if rows.empty:
        return 55, '近30日无大宗交易'

    rate_col = next((c for c in rows.columns if '折溢' in str(c)), None)
    if rate_col is None:
        return 50, '大宗缺折溢率列'
    rates = pd.to_numeric(rows[rate_col], errors='coerce').dropna()
    if rates.empty:
        return 50, '大宗折溢率全NaN'
    avg_rate = float(rates.mean())

    if avg_rate >= 10:     base, desc = 25, f'大宗折价{avg_rate:.1f}%(强出货)'
    elif avg_rate >= 5:    base, desc = 35, f'大宗折价{avg_rate:.1f}%'
    elif avg_rate >= 0:    base, desc = 45, f'大宗折价{avg_rate:.1f}%(微折)'
    elif avg_rate >= -5:   base, desc = 70, f'大宗溢价{abs(avg_rate):.1f}%'
    else:                  base, desc = 80, f'大宗溢价{abs(avg_rate):.1f}%(强接货)'

    seller_col = next((c for c in rows.columns if '卖方' in str(c)), None)
    if seller_col and rows[seller_col].astype(str).str.contains('机构专用', na=False).any():
        base = max(0, base - 10)
        desc += '+机构席位'

    return base, desc


# 子分 2: 融资融券余额变化
def score_margin(code6: str, margin_df: Optional[pd.DataFrame],
                 decline_pct: Optional[float] = None) -> Tuple[int, str]:
    """融资融券子分 0-100。
    decline_pct: 7 日变化率(% 正数=下降,负数=上升)。
                  测试/调用方传入;若 None 则尝试从 margin_df 计算。
    评分逻辑:
      - 周降 >= 10% → 25 分(杠杆踩踏)
      - 周降 5~10% → 40 分
      - 周降 0~5% → 50 分
      - 周升 0~5% → 55 分
      - 周升 >= 5% → 70 分(杠杆加仓)
      - df 缺失 → 50 分
    """
    if margin_df is None or margin_df.empty:
        return 50, '融资数据缺失'

    if decline_pct is None:
        decline_pct = 0.0

    if decline_pct >= 10:    base, desc = 25, f'融资周降{decline_pct:.1f}%(杠杆踩踏)'
    elif decline_pct >= 5:   base, desc = 40, f'融资周降{decline_pct:.1f}%'
    elif decline_pct >= 0:   base, desc = 50, f'融资周降{decline_pct:.1f}%(微降)'
    elif decline_pct >= -5:  base, desc = 55, f'融资周升{abs(decline_pct):.1f}%(微升)'
    else:                    base, desc = 70, f'融资周升{abs(decline_pct):.1f}%(加仓)'

    return base, desc


# 子分 3: 股东户数变化(季报)
def score_holder(code6: str, holder_df: Optional[pd.DataFrame],
                 change_pct: Optional[float] = None) -> Tuple[int, str]:
    """股东户数子分 0-100。
    change_pct: 户数环比变化率(% 正数=户数增加=派发,负数=户数减少=吸筹)。
                 测试/调用方传入;若 None 则尝试从 holder_df 计算。
    评分逻辑:
      - 户数 +20% → 25 分(筹码大幅分散)
      - 户数 +10~20% → 35 分
      - 户数 ±10% → 50 分(平稳)
      - 户数 -10~-20% → 65 分(集中)
      - 户数 <-20% → 75 分(大幅集中)
      - df 缺失 → 50 分
    """
    if holder_df is None or holder_df.empty:
        return 50, '股东户数缺失'

    if change_pct is None:
        change_pct = 0.0

    if change_pct >= 20:     base, desc = 25, f'户数+{change_pct:.0f}%(大幅分散)'
    elif change_pct >= 10:   base, desc = 35, f'户数+{change_pct:.0f}%(分散)'
    elif change_pct >= -10:  base, desc = 50, f'户数{change_pct:+.0f}%(平稳)'
    elif change_pct >= -20:  base, desc = 65, f'户数{change_pct:.0f}%(集中)'
    else:                    base, desc = 75, f'户数{change_pct:.0f}%(大幅集中)'

    return base, desc


# 子分 4: 解禁压力(未来 30 日)
def score_restricted(code6: str, restricted_df: Optional[pd.DataFrame],
                     pct_30d: Optional[float] = None) -> Tuple[int, str]:
    """解禁压力子分 0-100。
    pct_30d: 未来 30 日累计解禁占总股本比例(%)。
              测试/调用方传入;若 None 则尝试从 restricted_df 计算。
    评分逻辑:
      - 解禁 >= 10% → 20 分(强卖压)
      - 解禁 5~10% → 35 分
      - 解禁 1~5% → 50 分
      - 解禁 0~1% → 65 分
      - 解禁 0% → 75 分
      - df 缺失 → 50 分
    """
    if restricted_df is None or restricted_df.empty:
        return 50, '解禁数据缺失'

    if pct_30d is None:
        pct_30d = 0.0

    if pct_30d >= 10:    base, desc = 20, f'30日解禁{pct_30d:.1f}%(强卖压)'
    elif pct_30d >= 5:   base, desc = 35, f'30日解禁{pct_30d:.1f}%'
    elif pct_30d >= 1:   base, desc = 50, f'30日解禁{pct_30d:.1f}%'
    elif pct_30d > 0:    base, desc = 65, f'30日解禁{pct_30d:.1f}%'
    else:                base, desc = 75, '30日内无解禁'

    return base, desc


# 机构行为综合分
INST_SUB_WEIGHTS = {
    'dzjy': 0.30,        # 大宗折价(出货信号)
    'margin': 0.25,      # 融资融券变化(杠杆撤退)
    'holder': 0.25,      # 股东户数(筹码集中度)
    'restricted': 0.20,  # 解禁压力(前瞻卖压)
}


def compute_institutional_score(
    code6: str,
    dzjy_df: Optional[pd.DataFrame],
    margin_df: Optional[pd.DataFrame],
    holder_df: Optional[pd.DataFrame],
    restricted_df: Optional[pd.DataFrame],
    margin_decline_pct: Optional[float] = None,
    holder_change_pct: Optional[float] = None,
    restricted_pct_30d: Optional[float] = None,
) -> Tuple[int, dict]:
    """机构行为综合分 0-100 = 4 子分加权。
    输入:4 张缓存表 + 3 个可选派生指标(优先用传入的派生值,避免重新计算)。
    输出:(综合分 0-100, {子分名: (score, reason)} dict)
    """
    sub_scores = {
        'dzjy':       score_dzjy(code6, dzjy_df),
        'margin':     score_margin(code6, margin_df, margin_decline_pct),
        'holder':     score_holder(code6, holder_df, holder_change_pct),
        'restricted': score_restricted(code6, restricted_df, restricted_pct_30d),
    }
    composite = sum(s * INST_SUB_WEIGHTS[k] for k, (s, _) in sub_scores.items())
    return round(composite), sub_scores


# 主力分单细粒度(资金面内部子分)
def score_main_force_split(code6: str, fund_flow_df: Optional[pd.DataFrame]) -> Tuple[int, str]:
    """主力分单子分 0-100,识别"机构吸筹 vs 派发给散户"。
    字段:特大单/大单/中单/小单净额(元,正数=流入)。
    评分逻辑:
      - 特大+大单净流入 且 中+小单净流出 → 70 分(典型吸筹)
      - 特大+大单净流入 → 60 分
      - 特大+大单净流出 且 中+小单净流入 → 30 分(典型派发)
      - 特大+大单净流出 → 40 分
      - 混合(单边不一致) → 50 分
      - code 不在 df → 55 分
      - df 缺失 → 50 分
    """
    if fund_flow_df is None or fund_flow_df.empty:
        return 50, '主力分单数据缺失'

    code_col = '_code6' if '_code6' in fund_flow_df.columns else '代码'
    rows = fund_flow_df[fund_flow_df[code_col].astype(str).str.zfill(6) == str(code6).zfill(6)]
    if rows.empty:
        return 55, '该票无主力分单数据'

    def _get_col(df, keywords, exclude_prefix=None):
        """根据关键词找列名,优先选第一个匹配;若 exclude_prefix 给定,排除以它开头的列。
        解决'大单净'在'特大单净额'中误匹配(index 1-3 是 '大单净')。"""
        for c in df.columns:
            cs = str(c)
            if exclude_prefix and cs.startswith(exclude_prefix):
                continue
            for kw in keywords:
                if kw in cs:
                    return c
        return None

    super_col = _get_col(rows, ['特大单'])
    large_col = _get_col(rows, ['大单'], exclude_prefix='特')  # 排除'特大单净额'开头的列
    mid_col   = _get_col(rows, ['中单'])
    small_col = _get_col(rows, ['小单'])

    if not (super_col and large_col and mid_col and small_col):
        return 50, '主力分单缺列'

    super_amt = float(pd.to_numeric(rows[super_col], errors='coerce').iloc[0] or 0)
    large_amt = float(pd.to_numeric(rows[large_col], errors='coerce').iloc[0] or 0)
    mid_amt   = float(pd.to_numeric(rows[mid_col], errors='coerce').iloc[0] or 0)
    small_amt = float(pd.to_numeric(rows[small_col], errors='coerce').iloc[0] or 0)

    main_amt = super_amt + large_amt
    retail_amt = mid_amt + small_amt

    # 优先检查:特大+大单方向不一致 → 混合信号(50 分)
    if (super_amt > 0) != (large_amt > 0):
        return 50, f'特大单({super_amt/1e6:+.0f}万)与 大单({large_amt/1e6:+.0f}万)方向不一致(混合)'

    if main_amt > 0 and retail_amt < 0:
        score, desc = 70, f'主力+{main_amt/1e6:.0f}万 散户{retail_amt/1e6:.0f}万(吸筹)'
    elif main_amt > 0:
        score, desc = 60, f'主力+{main_amt/1e6:.0f}万(流入)'
    elif main_amt < 0 and retail_amt > 0:
        score, desc = 30, f'主力{main_amt/1e6:.0f}万 散户+{retail_amt/1e6:.0f}万(派发)'
    elif main_amt < 0:
        score, desc = 40, f'主力{main_amt/1e6:.0f}万(流出)'
    else:
        score, desc = 50, '主力分单持平'

    return score, desc


# ============================================================
# 派生指标:融资余额 7 日变化率(供证伪门用)
# ============================================================
def compute_margin_change_pct(
    code6: str,
    today_df: Optional[pd.DataFrame],
    week_ago_df: Optional[pd.DataFrame],
) -> Optional[float]:
    """算 code6 的融资余额 7 日变化率(%)。

    返回值:
      - 正数:融资余额上升(杠杆加仓)
      - 负数:融资余额下降(杠杆撤退)
      - None :任一 df 缺失/无该 code/基线为 0

    字段约定(兼容 akshare `stock_margin_underlying_info_szse`):
      标的代码 / 融资余额(元)
    """
    if today_df is None or week_ago_df is None:
        return None
    if today_df.empty or week_ago_df.empty:
        return None

    def _bal(df):
        code_col = '_code6' if '_code6' in df.columns else '标的代码'
        rows = df[df[code_col].astype(str).str.zfill(6) == str(code6).zfill(6)]
        if rows.empty:
            return None
        bal_col = next((c for c in rows.columns if '融资余额' in str(c)), None)
        if not bal_col:
            return None
        v = pd.to_numeric(rows[bal_col], errors='coerce').iloc[0] if len(rows) else None
        return float(v) if v is not None and not pd.isna(v) else None

    today_bal = _bal(today_df)
    ago_bal = _bal(week_ago_df)
    if today_bal is None or ago_bal is None or ago_bal <= 0:
        return None
    return (today_bal - ago_bal) / ago_bal * 100.0
