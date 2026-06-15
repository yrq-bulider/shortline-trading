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
