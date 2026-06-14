"""涨停板首板小盘候选池(v1.3)。从涨停股池里筛主板首板小盘
+ 4 维分 ≥60 + 业绩雷区已过 → 当晚锁仓清单。"""

import pandas as pd

DABANG_FILTERS = {
    'price_max':     30.0,      # 单价 ≤30 元
    'mv_max_yi':     300.0,     # 流通市值 ≤300 亿
    'feng_time_max': '14:30',   # 封板时间 ≤14:30(去尾盘抢)
    'zhaban_max':    5,         # 炸板次数 ≤5
    'lianban_eq':    1,         # 只要首板
    'score_min':     60,        # 4 维综合 ≥60
}


def _col(df, keyword):
    """模糊匹配列名,返回第一个含 keyword 的列;无则返回 None。"""
    for c in df.columns:
        if keyword in str(c):
            return c
    return None


def _is_mainboard(code: str) -> bool:
    """主板 = 00xxxx + 60xxxx(科创北交所创业板都剔除)。"""
    c = str(code).zfill(6)
    return c.startswith('00') or c.startswith('60')


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_dabang_candidates(zt_pool_df, score_dict, top_n=5) -> list:
    """返回符合条件的涨停首板候选,按 4 维综合分降序。
      zt_pool_df: ak.stock_zt_pool_em 的 df,带'代码'/'最新价'/'流通市值'/'封板时间'/'炸板次数'/'连板数'。
      score_dict: {code6: {'composite': int, 'subscores': {...}, 'falsified': bool}}。
      失败/空 → 返回 []。"""
    if zt_pool_df is None or zt_pool_df.empty:
        return []

    code_col   = _col(zt_pool_df, '代码')
    name_col   = _col(zt_pool_df, '名称')
    price_col  = _col(zt_pool_df, '最新价') or _col(zt_pool_df, '价')
    mv_col     = _col(zt_pool_df, '流通市值') or _col(zt_pool_df, '市值')
    feng_col   = _col(zt_pool_df, '封板时间') or _col(zt_pool_df, '首次封板')
    zhaban_col = _col(zt_pool_df, '炸板')
    lianban_col= _col(zt_pool_df, '连板')

    if code_col is None:
        return []

    feng_max = DABANG_FILTERS['feng_time_max']
    out = []
    for _, row in zt_pool_df.iterrows():
        code = str(row[code_col]).zfill(6)
        if not _is_mainboard(code):
            continue

        price = _to_float(row[price_col]) if price_col else None
        if price is None or price > DABANG_FILTERS['price_max']:
            continue

        mv = _to_float(row[mv_col]) if mv_col else None
        if mv is not None:
            mv_yi = mv / 100_000_000
            if mv_yi > DABANG_FILTERS['mv_max_yi']:
                continue

        if feng_col:
            feng_v = str(row[feng_col])[:5] if pd.notna(row[feng_col]) else ''
            if feng_v and feng_v > feng_max:
                continue

        if zhaban_col:
            zb = _to_float(row[zhaban_col])
            if zb is not None and zb > DABANG_FILTERS['zhaban_max']:
                continue

        if lianban_col:
            lb = _to_float(row[lianban_col])
            if lb is None or int(lb) != DABANG_FILTERS['lianban_eq']:
                continue

        score = score_dict.get(code)
        if score is None:
            continue
        if score.get('falsified', False):
            continue
        composite = score.get('composite', 0)
        if composite < DABANG_FILTERS['score_min']:
            continue

        out.append({
            'code':      code,
            'name':      str(row[name_col]) if name_col else '',
            'price':     price,
            'mv_yi':     round(mv / 100_000_000, 1) if mv is not None else None,
            'feng_time': str(row[feng_col])[:5] if feng_col and pd.notna(row[feng_col]) else '',
            'zhaban':    int(_to_float(row[zhaban_col]) or 0) if zhaban_col else 0,
            'composite': composite,
            'subscores': score.get('subscores', {}),
        })

    out.sort(key=lambda r: r['composite'], reverse=True)
    return out[:top_n]