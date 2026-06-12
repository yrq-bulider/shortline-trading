"""
明日短线股票筛选器 v1.0  4维评分 · T+1/T+0双模式 · 动态仓位
================================================================
v0.3 → v1.0 升级清单（基于6月5日复盘）：
1. 新增「业绩过滤」: 一季报归母净利润同比为正，排除地雷股
2. 新增「资金流过滤」: 5日主力净流入不为大额净流出
3. 新增「消息催化评分」: 近30日有定增/并购/订单/新产品/政策加分
4. 新增「板块联动过滤」: 只选板块当日涨幅前1/3 + MA5向上
5. 4维综合评分: 权重随模式自动调整
6. T+1/T+0双模式（核心思维差异）：
   T+1（A股股票默认）= 隔夜发酵思维，消息催化权重25%最高
   T+0（ETF/可转债） = 日内分时思维，技术权重50%最高
7. 动态仓位分配: 综合分85+给40%，75-84给25%，65-74给15%
8. 复盘跟踪区: 自动记录每日评分+次日实际涨跌，用于回测胜率

T+1 vs T+0 关键差异（务必看）：
┌──────────┬───────────────────────┬──────────────────────┐
│ 维度     │ T+1                    │ T+0                  │
├──────────┼───────────────────────┼──────────────────────┤
│ 风险敞口 │ 过夜（次跳跳空风险）   │ 日内（无隔夜风险）   │
│ 核心     │ 消息驱动+资金共识     │ 分时技术+量能        │
│ 权重     │ 技术30/业绩25/资金20/ │ 技术50/业绩15/资金25/│
│          │ 消息25                 │ 消息10               │
│ 止盈     │ +5%减半               │ +2%减半              │
│ 止损     │ -5%                    │ -1.5%（更严）         │
│ 卖出时间 │ 次日9:25-9:45分情景   │ 当日14:30前必清      │
│ 选股     │ 重视催化+板块         │ 重视振幅+流动性      │
└──────────┴───────────────────────┴──────────────────────┘
"""

import baostock as bs
import pandas as pd
import numpy as np
import warnings
import time
import datetime
import json
import os
import functools
import threading
import queue
from concurrent.futures import ThreadPoolExecutor


# akshare wrapper
import importlib.util as _ilu
_res_spec = _ilu.spec_from_file_location("akshare_resilient",
    __file__.replace("筛选明日股票_v1.py", "短线工具箱/akshare_resilient.py"))
_res_mod = _ilu.module_from_spec(_res_spec)
_res_spec.loader.exec_module(_res_mod)
for _k in ["fetch_earnings","fetch_notice","fetch_lhb","fetch_lhb_inst","fetch_fund_flow_rank","fetch_hsgt","fetch_news"]: locals()[_k] = getattr(_res_mod, _k)

# scorer module (pure algorithm functions)
_sco_spec = _ilu.spec_from_file_location("scorer",
    os.path.join(os.path.dirname(__file__), "短线工具箱", "scorer.py"))
_sco_mod = _ilu.module_from_spec(_sco_spec)
_sco_spec.loader.exec_module(_sco_mod)
for _sn in ["init_mode_config","safe_score","composite_score","dynamic_position_pct","WEIGHT_TECH","WEIGHT_EARN","WEIGHT_FLOW","WEIGHT_NEWS","POSITION_TIERS","MARKET_POSITION_CAP"]: locals()[_sn] = getattr(_sco_mod, _sn)


warnings.filterwarnings('ignore')

# akshare 软依赖：缺则降级（只用技术层）
try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False
def _latest_quarter_end():
    """返回最近完整季度末日期字符串（YYYYMMDD），用于 akshare 业绩查询参数。
    如 6/9 调用 → '20260331'（Q1 末），9/15 → '20250630'（半年末）。"""
    m, y = TODAY.month, TODAY.year
    if m <= 3:
        return f"{y-1}1231"  # 去年年报
    elif m <= 6:
        return f"{y}0331"     # 今年一季报
    elif m <= 9:
        return f"{y}0630"     # 今年半年报
    else:
        return f"{y}0930"     # 今年三季报

# ============================================================
# 【核心配置】交易模式：'T+1'（A股股票）或 'T+0'（ETF/可转债）
# ============================================================
# T+1（A股股票默认）:
#   - 风险敞口过夜，必须看消息催化是否发酵
#   - 评分权重偏业绩+资金+消息（消息权重要更高）
#   - 次日开盘分情景应对
# T+0（ETF/可转债）:
#   - 当日可平仓，技术精准度决定胜负
#   - 评分权重偏技术+资金（消息催化权重降低）
#   - 日内分时择时，尾盘必清
# ============================================================

# ===== 动态日期 =====
TODAY = datetime.date.today()
START_DATE = (TODAY - datetime.timedelta(days=120)).isoformat()
TODAY_STR = TODAY.isoformat()
PREDICTION_DIR = "短线操作md文档"  # 当日预测 MD 统一放这里（不进 git）
HISTORY_FILE = "短线工具箱/历史评分.jsonl"  # 记录每日评分+次日实际涨跌

TRADING_MODE = 'T+1'  # ← 在这里切换模式

print(f"扫描日期: {TODAY} | 交易模式: {TRADING_MODE} | akshare: {HAS_AKSHARE}")

# ===== 通用配置 =====
CAPITAL = 5000  # 总资金（元）
EXCLUDE_INDUSTRIES = [
    '银行', '保险', '证券', '房地产', '建筑装饰', '钢铁', '煤炭', '石油开采',
    '电力', '高速公路', '铁路公路', '机场航运', '港口', '水电', '燃气'
]
MIN_PRICE = 5
MAX_PRICE = 50
MIN_VOLUME = 1000  # 万元


# ============================================================
# 通用工具
# ============================================================
def normalize_code(code):
    """剥离 'sh./sz./bj.' 前缀，返回 6 位代码字符串"""
    s = str(code)
    return s.split('.')[-1] if '.' in s else s



    return deco


def fetch_kline(code, start_date, end_date, bs=None,
                fields="date,open,high,low,close,volume,amount", min_rows=0):
    """单只股票拉 K 线，返回 DataFrame 或 None。bs 为 None 时用模块级默认 session。"""
    if bs is None:
        bs = globals().get('bs') or __import__('baostock')
    rs = bs.query_history_k_data_plus(
        code, fields,
        start_date=start_date, end_date=end_date,
        frequency="d", adjustflag="3"
    )
    data = []
    while rs.next():
        data.append(rs.get_row_data())
    if not data or (min_rows and len(data) < min_rows):
        return None
    df = pd.DataFrame(data, columns=rs.fields)
    for col in ('open', 'high', 'low', 'close', 'volume', 'amount'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    dropna_cols = [c for c in ('close', 'volume') if c in df.columns]
    if dropna_cols:
        df = df.dropna(subset=dropna_cols)
    return df


# ============================================================
# 【模式配置】权重 + 风险参数 单一来源
# ============================================================
# MODE_CONFIGS imported from 短线工具箱.scorer
def get_index_data():
    indices = {
        'sh.000001': '上证指数',
        'sz.399001': '深证成指',
        'sz.399006': '创业板指',
        'sh.000688': '科创50',
    }
    results = {}
    bs.login()
    for code, name in indices.items():
        df = fetch_kline(code, START_DATE, TODAY_STR)
        if df is not None and not df.empty:
            results[code] = (name, df)
    bs.logout()
    return results

def analyze_market(index_data):
    print("\n" + "=" * 60)
    print("                    大盘趋势分析")
    print("=" * 60)
    market_scores = []
    for code, (name, df) in index_data.items():
        if len(df) < 20:
            continue
        c = df['close'].values
        day_chg = (c[-1] - c[-2]) / c[-2] * 100 if len(c) >= 2 else 0
        ma5 = np.mean(c[-5:]); ma5_prev = np.mean(c[-6:-1])
        ma5_trend = "↑" if ma5 > ma5_prev else "↓"
        ma20 = np.mean(c[-20:]); ma20_prev = np.mean(c[-21:-1]) if len(c) >= 21 else ma20
        ma20_trend = "↑" if ma20 > ma20_prev else "↓"
        vol_20 = np.std(c[-20:]) / np.mean(c[-20:]) * 100
        if ma5 > ma20 and ma5_trend == "↑":
            trend, score = "强势", 3
        elif ma5 < ma20 and ma5_trend == "↓":
            trend, score = "弱势", 1
        elif ma5 > ma20:
            trend, score = "偏强", 2
        else:
            trend, score = "偏弱", 1
        chg_str = f"{'▲' if day_chg >= 0 else '▼'}{abs(day_chg):.2f}%"
        print(f"  {name:<8} 今日:{chg_str}  MA5:{ma5_trend}  MA20:{ma20_trend}  波动:{vol_20:.1f}%  趋势:{trend}")
        market_scores.append(score)
    avg_score = np.mean(market_scores) if market_scores else 2
    if avg_score >= 2.5:
        market_rating, advice, op_level = "★★★★★ 强势市场", "仓位可提升至60-80%，积极操作信号较强的个股", "积极"
    elif avg_score >= 2.0:
        market_rating, advice, op_level = "★★★★☆ 偏强市场", "仓位40-60%，精选信号明确的个股操作", "稳健"
    elif avg_score >= 1.5:
        market_rating, advice, op_level = "★★★☆☆ 震荡市场", "仓位20-40%，严格止损，快进快出", "谨慎"
    else:
        market_rating, advice, op_level = "★★☆☆☆ 弱势市场", "仓位10-20%或不操作，观望为主", "观望"
    print(f"\n  市场评级: {market_rating}")
    print(f"  操作建议: {advice}")
    print("=" * 60)
    return {'rating': market_rating, 'score': avg_score, 'advice': advice, 'level': op_level}


# ============================================================
# 行业分类（同v0.3）
# ============================================================
print("获取行业分类...")
lg = bs.login()
rs = bs.query_stock_industry()
rows = []
while rs.next():
    rows.append(rs.get_row_data())
bs.logout()
df_ind = pd.DataFrame(rows, columns=rs.fields)
df_filtered = df_ind[
    df_ind['industry'].notna() & (df_ind['industry'] != '') &
    (~df_ind['industry'].isin(EXCLUDE_INDUSTRIES))
]
print(f"过滤后: {len(df_filtered)} 只，覆盖 {df_filtered['industry'].nunique()} 个行业")
# 过滤可交易代码前缀(仅00xxx和60xxx开头)
df_filtered = df_filtered[df_filtered['code'].str[-6:].str.startswith(('00', '60'))]
print("  代码过滤: {} 只".format(len(df_filtered)))
# v1.1 修：原版按 code 升序遍历，sh 先填满 3 个名额导致 sz 几乎全被跳过（241 只里 sz 仅 18 只）
# 改为按 industry 分组后组内打乱顺序再取 3 只 → sh/sz 按行业实际比例平衡，总数/耗时不变
industry_groups = {}
shuffled = df_filtered.sample(frac=1, random_state=42).reset_index(drop=True)
for _, row in shuffled.iterrows():
    ind = row['industry']
    if ind not in industry_groups:
        industry_groups[ind] = []
    if len(industry_groups[ind]) < 3:
        industry_groups[ind].append(row)
sampled = pd.DataFrame([item for group in industry_groups.values() for item in group])

# ============================================================
# 批量查历史数据（同v0.3）
# ============================================================
def batch_get_history(codes, start_date=None, end_date=None, min_rows=60):
    """批量拉历史日 K，min_rows 默认 60（risk_stars 需要 60 个收盘价）"""
    if start_date is None: start_date = START_DATE
    if end_date is None: end_date = TODAY_STR
    results = {}
    bs.login()
    for code in codes:
        df = fetch_kline(code, start_date, end_date, min_rows=min_rows)
        if df is not None:
            results[code] = df
    bs.logout()
    return results


# ============================================================
# 【并发版】批量拉历史 K 线 —— 4 线程 + 限流 + 错误隔离
# ============================================================
# 设计要点（v1 → v1.1 提速改造 2026-06-09）：
# 1) baostock 官方未承诺线程安全 → 每线程独立 login/logout 拿独立 token/socket
# 2) 限流：0.15s sleep + 4 worker semaphore，避免高频触发反爬
# 3) 错误隔离：单只失败只记 None，不拖死整批
# 4) 进度聚合：主线程统一打印，避免 print 交错
# 5) results 用 code 当 key，与原版接口一致
_BS_THREAD_LOCAL = threading.local()

def _worker_login():
    """每个 worker 线程独立 login baostock。"""
    import baostock as bs_local
    bs_local.login()
    _BS_THREAD_LOCAL.bs = bs_local
    return bs_local

def _fetch_with_own_session(code, start_date, end_date, min_rows, sleep_s):
    """在调用线程内自己 login（lazy），拉一只票后 sleep 礼貌限流。"""
    bs_local = getattr(_BS_THREAD_LOCAL, 'bs', None)
    if bs_local is None:
        bs_local = _worker_login()
    try:
        df = fetch_kline(code, start_date, end_date, bs=bs_local, min_rows=min_rows)
    except Exception:
        df = None
    time.sleep(sleep_s)
    return code, df

def batch_get_history_concurrent(codes, start_date=None, end_date=None, min_rows=60,
                                 max_workers=4, sleep_per_req=0.15, progress=True):
    """并发批量拉 K 线。结果用 code 索引，缺失的票不在 dict 里（与原版语义一致）。"""
    if start_date is None: start_date = START_DATE
    if end_date is None: end_date = TODAY_STR
    codes = list(codes)
    total = len(codes)
    results = {}
    fail_log = []
    t0 = time.time()

    def _one(code):
        return _fetch_with_own_session(code, start_date, end_date, min_rows, sleep_per_req)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_one, code): code for code in codes}
        done = 0
        for fut in as_completed_iter(futures):
            done += 1
            try:
                code, df = fut.result()
                if df is not None:
                    results[code] = df
                else:
                    fail_log.append(code)
            except Exception:
                fail_log.append(futures[fut])
            if progress and (done % 20 == 0 or done == total):
                print(f"  并发进度: {done}/{total}  已用时 {time.time()-t0:.1f}s", flush=True)

    if progress:
        print(f"  并发完成: 成功 {len(results)} / 失败 {len(fail_log)}  总耗时 {time.time()-t0:.1f}s")
        if fail_log:
            print(f"  失败列表(前10): {fail_log[:10]}")
    return results


def as_completed_iter(futures):
    """as_completed 的薄封装，便于测试时 mock。"""
    from concurrent.futures import as_completed
    return as_completed(futures)


# ============================================================
# 技术指标（同v0.3）
# ============================================================
def calc_ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

def calc_macd(df, fast=12, slow=26, signal=9):
    c = df['close']
    ema_fast = calc_ema(c, fast); ema_slow = calc_ema(c, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_hist = (dif - dea) * 2
    return dif.values, dea.values, macd_hist.values

def calc_rsi_series(close, n=14):
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gains = pd.Series(gains).ewm(alpha=1/n, adjust=False).mean().values
    avg_losses = pd.Series(losses).ewm(alpha=1/n, adjust=False).mean().values
    rs = avg_gains / (avg_losses + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return np.concatenate([[50], rsi])

def calc_bollinger(df, n=20, k=2):
    c = df['close'].values
    if len(c) < n:
        return np.full(len(c), np.nan), np.full(len(c), np.nan), np.full(len(c), np.nan)
    mid = np.convolve(c, np.ones(n)/n, mode='valid')
    std = pd.Series(c).rolling(n).std().values
    upper = mid + k * std[n-1:]
    lower = mid - k * std[n-1:]
    upper = np.concatenate([np.full(n-1, np.nan), upper])
    lower = np.concatenate([np.full(n-1, np.nan), lower])
    mid = np.concatenate([np.full(n-1, np.nan), mid])
    return upper, mid, lower


# ============================================================
# 【新】维度1: 技术信号（v0.3原detect_signals，扩展返回子分）
# ============================================================
def detect_signals(df):
    if len(df) < 25:
        return [], {}, 0
    c = df['close'].values
    v = df['volume'].values
    h = df['high'].values
    o = df['open'].values
    cur = c[-1]
    signals = []
    signal_scores = {}
    ma5 = np.mean(c[-5:]); ma20 = np.mean(c[-20:])
    ma5p = np.mean(c[-6:-1]); ma20p = np.mean(c[-21:-1])
    vol_today = v[-1]
    vol_10avg = np.mean(v[-11:-1]) if len(v) >= 11 else np.mean(v[:-1])
    dif, dea, macd_hist = calc_macd(df)
    dif_cur, dif_prev = dif[-1], dif[-2]
    dea_cur, dea_prev = dea[-1], dea[-2]
    macd_bar = macd_hist[-1]
    rsi_arr = calc_rsi_series(c)
    rsi_cur = rsi_arr[-1]; rsi_prev = rsi_arr[-2] if len(rsi_arr) >= 2 else 50
    bb_upper, bb_mid, bb_lower = calc_bollinger(df)
    bb_width_arr = (bb_upper - bb_lower) / (bb_mid + 1e-10)
    bb_width_cur = bb_width_arr[-1]
    bb_width_prev = bb_width_arr[-2] if len(bb_width_arr) >= 2 else bb_width_cur

    if ma5 > ma20 and ma5p <= ma20p and vol_today > vol_10avg * 1.2:
        signals.append("MA金叉"); signal_scores['MA金叉'] = 2
    if len(c) >= 2 and v[-2] > 0:
        pc = (c[-1] - c[-2]) / c[-2]
        vc = (v[-1] - v[-2]) / v[-2]
        if vc >= 0.5 and pc >= 0.02:
            signals.append("量价齐升"); signal_scores['量价齐升'] = 2
    if len(df) >= 21:
        high_n = np.max(h[-21:-1])
        avg_v = np.mean(v[-21:-1])
        vol_ratio = v[-1] / avg_v if avg_v > 0 else 0
        if cur > high_n * 1.001 and vol_ratio >= 1.5:
            signals.append("突破放量"); signal_scores['突破放量'] = 2
    if len(c) >= 8:
        vol_3avg = np.mean(v[-3:])
        vol_5prev = np.mean(v[-8:-3])
        if vol_5prev > 0 and vol_3avg / vol_5prev > 1.3 and c[-1] > c[-4]:
            signals.append("持续放量"); signal_scores['持续放量'] = 1
    if len(c) >= 2 and c[-2] > 0:
        gap = (c[-1] - c[-2]) / c[-2]
        if 0.015 <= gap <= 0.07 and v[-1] > np.mean(v[-5:-1]) * 1.2:
            signals.append("跳空高开"); signal_scores['跳空高开'] = 1
    if not np.isnan(dif_cur) and not np.isnan(dea_cur):
        if dif_prev <= dea_prev and dif_cur > dea_cur and dea_cur > 0:
            signals.append("MACD金叉"); signal_scores['MACD金叉'] = 2
        elif dif_prev <= dea_prev and dif_cur > dea_cur and dif_cur > 0 and dea_cur < 0:
            signals.append("MACD零下金叉"); signal_scores['MACD零下金叉'] = 1
    if len(macd_hist) >= 2 and macd_bar > 0 and macd_hist[-2] > 0:
        if macd_bar > macd_hist[-2] * 1.1:
            signals.append("MACD红柱扩张"); signal_scores['MACD红柱扩张'] = 1
    if 30 <= rsi_prev < 35 and rsi_cur >= rsi_prev + 3:
        signals.append("RSI超卖反弹"); signal_scores['RSI超卖反弹'] = 2
    elif 35 <= rsi_cur < 45 and rsi_cur > rsi_prev:
        signals.append("RSI转多"); signal_scores['RSI转多'] = 1
    if not np.isnan(bb_lower[-1]):
        lower_band = bb_lower[-1]
        if cur > lower_band and c[-2] <= bb_lower[-2] + 0.01:
            signals.append("布林下轨支撑"); signal_scores['布林下轨支撑'] = 2
        elif cur > bb_mid[-1] and bb_mid[-1] > bb_mid[-2]:
            signals.append("布林中轨多头"); signal_scores['布林中轨多头'] = 1
    if not np.isnan(bb_width_cur) and not np.isnan(bb_width_prev):
        if bb_width_cur > bb_width_prev * 1.1 and c[-1] > c[-4]:
            signals.append("布林开口扩张"); signal_scores['布林开口扩张'] = 1

    total_score = sum(signal_scores.values())
    # 技术子分 0-100：归一化（满分按10分信号算）
    tech_subscore = min(100, total_score * 10)
    indicator_info = {
        'rsi': round(rsi_cur, 1),
        'macd_dif': round(dif_cur, 4) if not np.isnan(dif_cur) else None,
        'macd_dea': round(dea_cur, 4) if not np.isnan(dea_cur) else None,
        'macd_bar': round(macd_bar, 4) if not np.isnan(macd_bar) else None,
        'bb_upper': round(bb_upper[-1], 2) if not np.isnan(bb_upper[-1]) else None,
        'bb_mid': round(bb_mid[-1], 2) if not np.isnan(bb_mid[-1]) else None,
        'bb_lower': round(bb_lower[-1], 2) if not np.isnan(bb_lower[-1]) else None,
    }
    if total_score < 2:
        return [], indicator_info, 0
    return signals, indicator_info, tech_subscore


# ============================================================
# 【新】维度2: 业绩过滤（akshare）
# ============================================================
_EARNINGS_LOADED = False
_EARNINGS_CACHE = {}  # 模块级缓存，避免 5000+ 次重复下载全表


def _load_earnings_table():
    """首次调用时拉取整张业绩表并建立 code 索引；失败或无数据返回空 dict。"""
    global _EARNINGS_LOADED, _EARNINGS_CACHE
    if _EARNINGS_LOADED:
        return _EARNINGS_CACHE
    _EARNINGS_LOADED = True  # 试过就标记，避免反复重试拖慢扫描
    try:
        df = fetch_earnings()
        if df is None or df.empty:
            print(f"[预拉] 业绩表为空（akshare返回空，维度分将拉平到50）")
            return _EARNINGS_CACHE
        col_map = {'股票代码': 'code', '股票名称': 'name'}
        df = df.rename(columns=col_map)
        if 'code' not in df.columns:
            df['code'] = df.iloc[:, 0].astype(str).str.zfill(6)
        df['_code6'] = df['code'].astype(str).str[-6:]
        # 用 dict 而不是 set_index 避免重复代码 KeyError
        _EARNINGS_CACHE = {c6: row for c6, row in zip(df['_code6'], df.to_dict('records'))}
        print(f"[预拉] 业绩表 {len(_EARNINGS_CACHE)} 条")
    except Exception as e:
        print(f"[预拉] 业绩表失败: {type(e).__name__}（akshare故障，维度分将拉平到50，建议稍后重跑）")
    return _EARNINGS_CACHE


@safe_score('业绩失败')
def get_earnings_score(code, name):
    """
    返回 (subscore 0-100, reason_str)
    评分规则：归母净利润同比 > 50%→100；0~50%→70-90；-30%~0%→40-60；<-30%→0（淘汰）
    """
    if not HAS_AKSHARE:
        return 50, "akshare未安装"
    table = _load_earnings_table()
    if not table:
        return 50, "无业绩数据"
    code6 = normalize_code(code)
    row = table.get(code6)
    if row is None:
        return 50, "未匹配到业绩"
    yoy = None
    for col in ('归母净利润同比', '净利润同比', '归母净利润-同比增长', '归母净利润同比增长'):
        if col in row and pd.notna(row[col]):
            yoy = float(str(row[col]).replace('%', ''))
            break
    if yoy is None:
        return 50, "无同比数据"
    if yoy > 50:
        return 100, f"业绩高增+{yoy:.0f}%"
    elif yoy > 0:
        return 70 + min(20, yoy * 0.4), f"业绩正增+{yoy:.0f}%"
    elif yoy > -30:
        return 40 + (yoy + 30) * 1.0, f"业绩下滑{yoy:.0f}%"
    else:
        return 0, f"业绩地雷{yoy:.0f}%"


# ============================================================
# 【新】维度3: 资金流过滤（akshare）
# ============================================================
_CAPITAL_FLOW_LOADED = False
_CAPITAL_FLOW_CACHE = {}


def _load_capital_flow_table():
    global _CAPITAL_FLOW_LOADED, _CAPITAL_FLOW_CACHE
    if _CAPITAL_FLOW_LOADED:
        return _CAPITAL_FLOW_CACHE
    _CAPITAL_FLOW_LOADED = True
    try:
        df = fetch_fund_flow_rank()
        if df is None or df.empty:
            print(f"[预拉] 资金流表为空（akshare返回空，维度分将拉平到50）")
            return _CAPITAL_FLOW_CACHE
        col_map = {'代码': 'code', '股票代码': 'code'}
        df = df.rename(columns=col_map)
        if 'code' not in df.columns:
            df['code'] = df.iloc[:, 0].astype(str)
        df['_code6'] = df['code'].astype(str).str[-6:]
        _CAPITAL_FLOW_CACHE = {c6: row for c6, row in zip(df['_code6'], df.to_dict('records'))}
        print(f"[预拉] 资金流表 {len(_CAPITAL_FLOW_CACHE)} 条")
    except Exception as e:
        print(f"[预拉] 资金流表失败: {type(e).__name__}（akshare故障，维度分将拉平到50，建议稍后重跑）")
    return _CAPITAL_FLOW_CACHE


@safe_score('资金流失败')
def get_capital_flow_score(code):
    """返回 (subscore 0-100, reason_str)。规则按 5 日主力净流入金额映射。"""
    if not HAS_AKSHARE:
        return 50, "akshare未安装"
    table = _load_capital_flow_table()

    if not table:
        # v1.1.1 review：原 ab5093d 降级用 hsgt/lhb 与 news 维度双计（同一数据算两次分）。
        # 改用 histories 已有的 amount 5 日均量比作资金动量代理，零额外 IO、与 hsgt/lhb 完全正交。
        df = globals().get('histories', {}).get(code)
        if df is not None and len(df) >= 6:
            today_amt = float(df['amount'].iloc[-1])
            avg_5d = float(df['amount'].iloc[-6:-1].mean())
            if avg_5d > 0:
                ratio = today_amt / avg_5d
                if ratio >= 2.0:    return 85, f"放量{ratio:.1f}x"
                elif ratio >= 1.5:  return 70, f"放量{ratio:.1f}x"
                elif ratio >= 0.85: return 50, f"量平稳{ratio:.2f}x"
                elif ratio >= 0.6:  return 35, f"缩量{ratio:.2f}x"
                else:               return 20, f"严重缩量{ratio:.2f}x"
        return 50, "资金流数据缺失"  # 完全没数据兜底

    row = table.get(normalize_code(code))
    if row is None:
        return 50, "未匹配到资金流"
    for col in ('主力净流入-5日', '5日主力净流入', '主力净流入'):
        if col in row and pd.notna(row[col]):
            flow = float(row[col])  # 万元
            if flow > 5000:    return 100, f"5日主力净流入{flow/10000:.2f}亿"
            elif flow > 0:     return 70 + min(20, flow / 250), f"5日小幅流入{flow:.0f}万"
            elif flow > -5000: return 40 + (flow + 5000) / 125, f"5日小幅流出{abs(flow):.0f}万"
            else:              return max(0, 20 + flow / 250), f"5日主力出逃{abs(flow)/10000:.2f}亿"
    return 50, "无主力净流入字段"


# ============================================================
# 【新】维度4: 消息/事件催化（akshare公告）
# ============================================================
KEYWORD_HOT = [
    ('定增', 25), ('增持', 15), ('回购', 15), ('中标', 20), ('签订', 15),
    ('订单', 20), ('合作', 10), ('新产品', 20), ('投产', 15), ('突破', 15),
    ('利好', 10), ('政策', 10), ('入选', 8), ('认证', 10), ('专利', 8),
    ('重组', 25), ('并购', 20), ('分红', 8), ('业绩预增', 25), ('扭亏', 20),
]
KEYWORD_COLD = [
    ('减持', -20), ('减仓', -15), ('业绩预减', -25), ('亏损', -25),
    ('处罚', -20), ('诉讼', -10), ('退市', -30), ('ST', -40), ('问询', -10),
]


_NOTICE_LOADED = False
_NOTICE_CACHE = {}


def _load_notice_table():
    """预拉全市场当日公告表（~700 条）按 code6 缓存，单只票本地过滤。
    替代 stock_individual_notice_report(symbol=X)（新版 akshare 不支持单票查询）。"""
    global _NOTICE_LOADED, _NOTICE_CACHE
    if _NOTICE_LOADED:
        return _NOTICE_CACHE
    _NOTICE_LOADED = True
    try:
        temp = fetch_notice()
        if temp is None or temp.empty:
            print('[预拉] 公告表为空')
            return _NOTICE_CACHE
        cc = next((c for c in temp.columns if "代码" in c), None)
        if cc is None:
            return _NOTICE_CACHE
        for rec in temp.to_dict('records'):
            c6 = str(rec[cc]).zfill(6)[-6:]
            _NOTICE_CACHE.setdefault(c6, []).append(rec)
        print(f'[预拉] 公告表 {len(temp)} 条，覆盖 {len(_NOTICE_CACHE)} 只票')
    except Exception as e:
        print(f'[预拉] 公告表失败: {type(e).__name__}（建议稍后重跑）')
    return _NOTICE_CACHE


@safe_score('公告失败', extras=([],))
def get_ann_score(code, name):
    """公告子分 0-100（v1.1 拆出，便于 4 源融合复用）。
    akshare 多版本兼容：尝试老接口 + 多个新接口名，全部失败兜底 50。"""
    if not HAS_AKSHARE:
        return 50, "akshare未安装", []
    code6 = normalize_code(code)
    df = None
    # 尝试多种 akshare 接口名（新旧版本）。用户 v1.1.1 全表缓存 (#3) 已覆盖 #2 的能力，#2 留作兼容旧 akshare
    for attempt in [
        lambda: getattr(ak, 'stock_announcement_em', None) and ak.stock_announcement_em(symbol=code6),
        lambda: getattr(ak, 'stock_individual_notice_report', None) and ak.stock_individual_notice_report(security='股票', symbol=code6),
        lambda: _load_notice_table() and _NOTICE_CACHE.get(normalize_code(code)) and pd.DataFrame(_NOTICE_CACHE.get(normalize_code(code))),
    ]:
        try:
            result = attempt()
            if result is not None and not result.empty:
                df = result
                break
        except Exception:
            continue
    if df is None or df.empty:
        return 50, "公告接口暂不可用", []
    title_col = next((c for c in df.columns if '标题' in c), None)
    if title_col is None:
        return 50, "无标题字段", []
    titles = df[title_col].astype(str).head(30).tolist()
    if not titles:
        return 50, "无标题", []
    bonus = 0
    hot_tags = []
    for t in titles:
        for kw, score in KEYWORD_HOT:
            if kw in t:
                bonus += score
                hot_tags.append(kw)
                break
        for kw, score in KEYWORD_COLD:
            if kw in t:
                bonus += score
                hot_tags.append(f"!{kw}")
                break
    bonus = min(bonus, 60)
    bonus = max(bonus, -50)
    final = max(0, min(100, 50 + bonus))
    unique_tags = list(set(hot_tags))[:5]
    return final, f"公告{len(titles)}条,催化{'+'.join(unique_tags[:3]) if unique_tags else '无'}", unique_tags


# v1.1 新增：新闻情感关键词（4 源融合用）
NEWS_HOT = ['利好', '突破', '增长', '中标', '签约', '订单', '获批', '提速', '受益', '扩产', '投产', '创新高']
NEWS_COLD = ['下滑', '亏损', '下调', '降级', '处罚', '问询', '退市', '诉讼', '资金出逃', '业绩雷']


@safe_score('新闻失败')
def get_newsfeed_score(code, name):
    """个股新闻子分 0-100。ak.stock_news_em 拉近 N 条新闻，关键词情感。"""
    if not HAS_AKSHARE:
        return 50, "akshare未安装"
    try:
        df = fetch_news(symbol=normalize_code(code))
    except Exception as e:
        return 50, f"新闻拉取失败:{type(e).__name__}"
    if df is None or df.empty:
        return 50, "无新闻"
    title_col = next((c for c in df.columns if '标题' in c), None)
    if title_col is None:
        return 50, "无标题字段"
    titles = df[title_col].astype(str).tolist()[:10]
    if not titles:
        return 50, "无标题"
    bonus = 0
    for t in titles:
        for kw in NEWS_HOT:
            if kw in t:
                bonus += 8
                break
        for kw in NEWS_COLD:
            if kw in t:
                bonus -= 10
                break
    bonus = max(-50, min(50, bonus))
    final = max(0, min(100, 50 + bonus))
    return final, f"新闻{len(titles)}条,情感{'+' if bonus>0 else ''}{bonus}"


@safe_score('北向失败')
def get_hsgt_score(code):
    """北向资金 3 日净流入子分 0-100(P1: 5→3 日, 反应更灵敏)。"""
    if not HAS_AKSHARE:
        return 50, "akshare未安装"
    try:
        df = fetch_hsgt(symbol=normalize_code(code))
    except Exception as e:
        return 50, f"北向拉取失败:{type(e).__name__}"
    if df is None or df.empty or len(df) < 3:
        return 50, "北向数据不足"
    flow_col = next((c for c in df.columns if '资金' in c and '今日' in c), None)
    if flow_col is None:
        return 50, "无资金流字段"
    flow_3d = df[flow_col].head(3).sum()  # v1.2 P1: 5→3 日  # 单位：元（A 股个股 5 日净流入通常 ±1 亿）
    score = 50 + flow_3d / 100000000 * 40  # 1 亿净流入对应 +40 分，-1 亿对应 -40 分
    score = max(0, min(100, round(score)))
    direction = "流入" if flow_3d > 0 else "流出"
    return score, f"3日北向{direction}{abs(flow_3d)/100000000:.2f}亿"


# 龙虎榜全市场缓存（v1.1 新增）
_LHB_LOADED = False
_LHB_CACHE = {}


def _load_lhb_table():
    """预拉全市场近 1 月龙虎榜表。ak.stock_lhb_stock_statistic_em 一次返回 811 条。"""
    global _LHB_LOADED, _LHB_CACHE
    if _LHB_LOADED:
        return _LHB_CACHE
    _LHB_LOADED = True
    try:
        df = fetch_lhb()
        if df is None or df.empty:
            print('[预拉] 龙虎榜表为空')
            return _LHB_CACHE
        code_col = next((c for c in df.columns if '代码' in c), df.columns[0])
        df['_code6'] = df[code_col].astype(str).str.zfill(6)
        for c6, row in df.set_index('_code6').iterrows():
            _LHB_CACHE[c6] = row.to_dict()
        print(f'[预拉] 龙虎榜表 {len(_LHB_CACHE)} 条')
    except Exception as e:
        print(f'[预拉] 龙虎榜表失败: {type(e).__name__}（建议稍后重跑）')
    return _LHB_CACHE


# 龙虎榜机构席位全市场缓存(P1 新增)
_LHB_INST_LOADED = False
_LHB_INST_CACHE = {}


def _load_lhb_inst_table():
    """预拉全市场近 1 月机构席位追踪表。fetch_lhb_inst 返回 ~100 条。
    失败兜底：返回空 dict，机构加成跳过，不影响原 lhb 子分。"""
    global _LHB_INST_LOADED, _LHB_INST_CACHE
    if _LHB_INST_LOADED:
        return _LHB_INST_CACHE
    _LHB_INST_LOADED = True
    try:
        df = fetch_lhb_inst()
        if df is None or df.empty:
            print('[预拉] 机构席位表为空')
            return _LHB_INST_CACHE
        code_col = next((c for c in df.columns if '代码' in c), df.columns[0])
        df['_code6'] = df[code_col].astype(str).str.zfill(6)
        for c6, row in df.set_index('_code6').iterrows():
            _LHB_INST_CACHE[c6] = row.to_dict()
        print(f'[预拉] 机构席位表 {len(_LHB_INST_CACHE)} 条')
    except Exception as e:
        print(f'[预拉] 机构席位表失败: {type(e).__name__}(跳过机构加成)')
    return _LHB_INST_CACHE


@safe_score('龙虎失败')
def get_lhb_score(code):
    """龙虎榜子分 0-100 = 上榜净买入(基础) + 机构席位加成。
    P1：叠加机构净买入 > 0 时 +10，>= 50 万时 +20。
    机构表拉取失败时跳过加成，回退原 v1.1 行为。"""
    table = _load_lhb_table()
    code6 = normalize_code(code)
    row = table.get(code6)
    if row is None:
        return 50, "近1月未上榜"
    net_buy_col = next((k for k in row.keys() if '净买' in str(k)), None)
    if not (net_buy_col and pd.notna(row[net_buy_col])):
        return 70, "近1月有上榜"

    net_buy = float(row[net_buy_col])
    base = 50 + net_buy / 1000000
    base = max(0, min(100, round(base)))
    reason = f"龙虎榜净买{net_buy/10000:.0f}万"

    # 机构席位加成(P1)
    inst_table = _load_lhb_inst_table()
    inst_row = inst_table.get(code6)
    if inst_row is not None:
        inst_net_col = next((k for k in inst_row.keys() if '净买' in str(k) and '机构' in str(k)), None)
        if not inst_net_col:
            inst_net_col = next((k for k in inst_row.keys() if '净买' in str(k)), None)
        if inst_net_col and pd.notna(inst_row[inst_net_col]):
            inst_net = float(inst_row[inst_net_col])
            if inst_net >= 500000:
                base = min(100, base + 20)
                reason += f"|机构净买{inst_net/10000:.0f}万+20"
            elif inst_net > 0:
                base = min(100, base + 10)
                reason += f"|机构净买{inst_net/10000:.0f}万+10"

    return base, reason


# 4 源融合权重（v1.1 新增）
NEWS_SUB_WEIGHTS = {'ann': 0.30, 'newsfeed': 0.30, 'hsgt': 0.20, 'lhb': 0.20}


@safe_score('信息失败', extras=([],))
def get_news_catalyst_score(code, name):
    """
    v1.1 重构：4 源融合
    总分 = 公告(30%) + 新闻(30%) + 北向(20%) + 龙虎榜(20%)
    单源失败时该源按 50 中性化，不影响总分结构。
    """
    ann_sub, ann_reason, ann_tags = get_ann_score(code, name)
    nf_sub, nf_reason = get_newsfeed_score(code, name)
    hsgt_sub, hsgt_reason = get_hsgt_score(code)
    lhb_sub, lhb_reason = get_lhb_score(code)

    total = (ann_sub * NEWS_SUB_WEIGHTS['ann'] +
             nf_sub  * NEWS_SUB_WEIGHTS['newsfeed'] +
             hsgt_sub * NEWS_SUB_WEIGHTS['hsgt'] +
             lhb_sub  * NEWS_SUB_WEIGHTS['lhb'])
    total = round(total, 1)

    reason = (f"公告{ann_sub}({ann_reason})|"
              f"新闻{nf_sub}({nf_reason})|"
              f"北向{hsgt_sub}({hsgt_reason})|"
              f"龙虎{lhb_sub}({lhb_reason})")
    return total, reason, ann_tags


# ============================================================
# 【新】维度5: 板块联动（用同行业所有股票表现估算）
# ============================================================
def get_sector_rotation_score(industry, all_industry_data):
    """
    返回 (subscore 0-100, reason_str)
    简化：用同行业股票当日平均涨跌+MA5方向作为板块强度代理
    """
    if industry not in all_industry_data:
        return 50, "无板块数据"
    peers = all_industry_data[industry]
    if len(peers) < 2:
        return 50, "板块个股<2"
    chgs = [p['chg'] for p in peers if p['chg'] is not None]
    ma5_dirs = [p['ma5_up'] for p in peers if p['ma5_up'] is not None]
    if not chgs:
        return 50, "无涨跌数据"
    avg_chg = np.mean(chgs)
    ma5_up_ratio = sum(ma5_dirs) / len(ma5_dirs) if ma5_dirs else 0.5
    # 综合：板块当日涨跌幅 + MA5向上的股票占比
    score = 50 + avg_chg * 30 + (ma5_up_ratio - 0.5) * 40
    score = max(0, min(100, score))
    return round(score), f"板块{industry}均涨跌{avg_chg:+.2f}%,MA5向上占比{ma5_up_ratio*100:.0f}%"


# ============================================================
# 4维综合评分
# ============================================================
# ============================================================
# 【新】智能去重：防"信号耗尽"重复推荐
# ============================================================
def load_recent_recommendations(days=3):
    """
    读历史jsonl，返回近N天推荐过的股票代码集合 + 推荐次数
    返回: (recent_codes: set, recent_with_score: list of {code, name, date, composite})
    """
    if not os.path.exists(HISTORY_FILE):
        return set(), []
    recent = []
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                rec = json.loads(line)
                for s in rec.get('top3', []):
                    recent.append({
                        'code': s['code'],
                        'name': s['name'],
                        'date': rec['date'],
                        'composite': s['composite'],
                    })
            except Exception:
                continue
    # 只保留近N天
    if recent:
        cutoff = (TODAY - datetime.timedelta(days=days)).isoformat()
        recent = [r for r in recent if r['date'] >= cutoff]
    return {r['code'] for r in recent}, recent


def should_skip_stock(code, name, df, recent_codes):
    """
    决定是否跳过这只票
    规则：
    1) 近3日推荐过 → 跳过（信号已发酵/可能被套）
    2) 近5日累计涨幅>5% → 跳过（已涨过，短线空间小）
    返回: (should_skip: bool, reason: str)
    """
    if code in recent_codes:
        return True, "近3日已推荐(信号已消耗)"
    if df is None or len(df) < 6:
        return False, ""
    c = df['close'].values
    # 近5日累计涨幅
    chg_5d = (c[-1] - c[-6]) / c[-6] * 100 if c[-6] > 0 else 0
    if chg_5d > 5:
        return True, f"近5日已涨{chg_5d:.1f}%(空间不足)"
    if chg_5d < -10:
        return True, f"近5日已跌{abs(chg_5d):.1f}%(弱势/可能继续跌)"
    return False, ""


# ============================================================
# 【新】自动回测：验证评分体系是否真的"更准"
# ============================================================
def backtest_score_history(days_back=20):
    """
    读历史jsonl，对每只TOP3票，拉次日实际数据，计算真实表现
    返回统计报告: dict
    """
    if not os.path.exists(HISTORY_FILE):
        return None
    records = []
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    if not records:
        return None
    # 限定最近N天
    cutoff = (TODAY - datetime.timedelta(days=days_back)).isoformat()
    records = [r for r in records if r['date'] >= cutoff]

    # 对每条记录，懒加载次日数据
    detailed = []
    cache = {}  # code -> {date_str: (open, close)}
    bs.login()
    try:
        for rec in records:
            rec_date = rec['date']
            # 找次日（跳过周末）
            d = datetime.datetime.strptime(rec_date, '%Y-%m-%d').date() + datetime.timedelta(days=1)
            while d.weekday() >= 5:
                d += datetime.timedelta(days=1)
            next_date = d.isoformat()
            for stock in rec.get('top3', []):
                code = stock['code']
                rec_price = stock.get('price', 0)
                composite = stock.get('composite', 0)
                if rec_price <= 0:
                    continue
                if code not in cache:
                    # v1.1 优化：主扫已拉 120 天 K 线到 histories[code]，直接复用 3 天窗口
                    # 避免 backtest 段对同一只票重复发 baostock 请求（days_back×top3 次冗余 fetch）
                    if code in histories:
                        sub = histories[code]
                        end_dt = pd.Timestamp(next_date) + datetime.timedelta(days=2)
                        sub = sub[(sub['date'] >= pd.Timestamp(next_date)) & (sub['date'] <= end_dt)]
                        if not sub.empty:
                            cache[code] = {row['date'].strftime('%Y-%m-%d'): (float(row['open']), float(row['close']))
                                           for _, row in sub.iterrows()}
                        else:
                            cache[code] = {}
                    else:
                        # 兜底：这只票没在主扫池里（如 6/8 之前历史 top3 已退市）
                        try:
                            df = fetch_kline(code, next_date,
                                             (d + datetime.timedelta(days=2)).isoformat(),
                                             fields="date,open,close")
                            if df is not None and not df.empty:
                                cache[code] = {row['date'].strftime('%Y-%m-%d'): (float(row['open']), float(row['close']))
                                               for _, row in df.iterrows()}
                            else:
                                cache[code] = {}
                        except Exception:
                            cache[code] = {}
                day_data = cache[code].get(next_date)
                if day_data is None:
                    # 找不到次日（可能停牌或数据延迟）
                    continue
                next_open, next_close = day_data
                gap_ret = (next_open - rec_price) / rec_price * 100
                day_ret = (next_close - rec_price) / rec_price * 100
                detailed.append({
                    'rec_date': rec_date, 'code': code, 'name': stock['name'],
                    'composite': composite, 'subscores': stock.get('subscores', {}),
                    'rec_price': rec_price,
                    'next_open': next_open, 'next_close': next_close,
                    'gap_ret': round(gap_ret, 2), 'day_ret': round(day_ret, 2),
                })
    finally:
        bs.logout()

    if not detailed:
        return None

    # 整体统计
    total = len(detailed)
    win = sum(1 for r in detailed if r['day_ret'] > 0)
    win_rate = round(win / total * 100, 1)
    avg_ret = round(np.mean([r['day_ret'] for r in detailed]), 2)
    avg_gap = round(np.mean([r['gap_ret'] for r in detailed]), 2)
    max_win = round(max(r['day_ret'] for r in detailed), 2)
    max_loss = round(min(r['day_ret'] for r in detailed), 2)

    # 按分桶
    buckets = {'90+': [], '80-89': [], '70-79': [], '60-69': [], '<60': []}
    for r in detailed:
        s = r['composite']
        if s >= 90: buckets['90+'].append(r)
        elif s >= 80: buckets['80-89'].append(r)
        elif s >= 70: buckets['70-79'].append(r)
        elif s >= 60: buckets['60-69'].append(r)
        else: buckets['<60'].append(r)

    bucket_stats = {}
    for name, items in buckets.items():
        if not items:
            continue
        w = sum(1 for r in items if r['day_ret'] > 0)
        bucket_stats[name] = {
            'count': len(items),
            'win_rate': round(w / len(items) * 100, 1),
            'avg_ret': round(np.mean([r['day_ret'] for r in items]), 2),
            'max_win': round(max(r['day_ret'] for r in items), 2),
            'max_loss': round(min(r['day_ret'] for r in items), 2),
        }

    # 调参建议（基于分桶）
    recommendations = []
    best_bucket = max(bucket_stats.items(), key=lambda x: x[1]['win_rate'] * 100 + x[1]['avg_ret'] * 10) if bucket_stats else None
    if best_bucket:
        recommendations.append(f"综合分{best_bucket[0]}表现最好（胜率{best_bucket[1]['win_rate']}%, 均收益{best_bucket[1]['avg_ret']}%），优先推荐该区间")
    if bucket_stats.get('90+', {}).get('win_rate', 0) < 60:
        recommendations.append("90+区间胜率偏低，建议把'高仓位门槛'从85提到88")
    if bucket_stats.get('60-69', {}).get('win_rate', 0) > 70:
        recommendations.append("60-69区间胜率意外好，可放宽推荐门槛")
    if abs(avg_gap) > 1.5:
        direction = "高开" if avg_gap > 0 else "低开"
        recommendations.append(f"平均次日{direction}{abs(avg_gap):.1f}%，开盘跳空明显，T+1应对要严格按规则")

    return {
        'days_back': days_back,
        'total_trades': total,
        'win_rate': win_rate,
        'avg_return': avg_ret,
        'avg_gap': avg_gap,
        'max_win': max_win,
        'max_loss': max_loss,
        'bucket_stats': bucket_stats,
        'recommendations': recommendations,
        'detailed': detailed,
    }


def print_backtest_report(report):
    """打印回测报告"""
    if report is None:
        print("\n[回测] 暂无历史数据（需要先跑几次扫描积累评分）")
        return
    print("\n" + "=" * 70)
    print(f"  [回测] 4维评分体系回测报告（近{report['days_back']}天）")
    print("=" * 70)
    print(f"  样本数:        {report['total_trades']} 笔")
    print(f"  胜率:          {report['win_rate']}%")
    print(f"  平均收益:      {report['avg_return']}%")
    print(f"  平均跳空:      {report['avg_gap']:+.2f}%")
    print(f"  最大盈利:      +{report['max_win']}%")
    print(f"  最大亏损:      {report['max_loss']}%")
    print()
    print(f"  {'分桶':<10}{'样本':<6}{'胜率':<8}{'均收益':<10}{'最大盈利':<10}{'最大亏损':<10}")
    print("  " + "-" * 60)
    for bucket, s in report['bucket_stats'].items():
        print(f"  {bucket:<10}{s['count']:<6}{s['win_rate']}%{'':<3}{s['avg_ret']:+}%{'':<6}+{s['max_win']}%{'':<5}{s['max_loss']}%")
    print()
    if report['recommendations']:
        print("  [建议] 调参建议：")
        for r in report['recommendations']:
            print(f"     - {r}")
    print("=" * 70)


# ============================================================
# 【新】分维度归因：4维评分到底有没有用？哪个维度最有"预言力"？
# ============================================================
def backtest_dimension_attribution(report):
    """
    3层归因分析：
    1) 相关性：每个子分维度 vs 次日实际收益的相关系数
    2) 分桶胜率：每个维度分高/中/低三档，对比胜率差
    3) 消融实验：4维全开 vs 单维度挑选的胜率对比

    核心思想：如果一个子分跟收益强相关（|r| > 0.2）→ 该维度有效
              如果 |r| < 0.1 → 该维度可能是噪声，应降权

    接受已经跑过 backtest_score_history 的 report，复用 detailed 列表，
    避免重复读 jsonl + 重复拉 baostock 历史价。
    """
    if report is None or not report.get('detailed'):
        return None

    detailed = report['detailed']
    n = len(detailed)
    if n < 5:
        return {
            'note': f'样本太少（{n}笔），归因不可靠。建议积累到20+笔再分析。',
            'sample_size': n,
        }

    dimensions = ['tech', 'earn', 'flow', 'news']
    rets = np.array([t['day_ret'] for t in detailed])

    # ---- 1) 相关性分析 ----
    correlations = {}
    for dim in dimensions:
        scores = np.array([t['subscores'][dim] for t in detailed])
        if scores.std() == 0:
            correlations[dim] = {'corr': 0, 'high_win': 0, 'low_win': 0, 'win_diff': 0, 'practical': '无变化'}
            continue
        corr = float(np.corrcoef(scores, rets)[0, 1])
        # 实际区分度：高分组 vs 低分组的胜率差
        sorted_pairs = sorted(zip(scores, rets), key=lambda x: -x[0])
        top_n = max(3, n // 3)
        high_ret = [r for _, r in sorted_pairs[:top_n]]
        low_ret = [r for _, r in sorted_pairs[-top_n:]]
        high_win = sum(1 for r in high_ret if r > 0) / len(high_ret) * 100
        low_win = sum(1 for r in low_ret if r > 0) / len(low_ret) * 100
        win_diff = round(high_win - low_win, 1)
        avg_diff = round(np.mean(high_ret) - np.mean(low_ret), 2)
        # 评价
        if abs(corr) >= 0.3 and win_diff >= 20:
            practical = '强有效'
        elif abs(corr) >= 0.15 or win_diff >= 10:
            practical = '中等有效'
        elif abs(corr) < 0.05 and abs(win_diff) < 5:
            practical = '! 噪声'
        else:
            practical = '弱有效'
        correlations[dim] = {
            'corr': round(corr, 3),
            'high_win': round(high_win, 1),
            'low_win': round(low_win, 1),
            'win_diff': win_diff,
            'avg_diff': avg_diff,
            'practical': practical,
        }

    # ---- 2) 消融实验 ----
    # 用 4 维全开 vs 单一维度，看哪种策略挑出的票胜率最高
    ablation = {}
    for strategy_name, score_fn in [
        ('4维综合', lambda t: t['composite']),
        ('只看技术', lambda t: t['subscores']['tech']),
        ('只看业绩', lambda t: t['subscores']['earn']),
        ('只看资金', lambda t: t['subscores']['flow']),
        ('只看消息', lambda t: t['subscores']['news']),
    ]:
        ranked = sorted(detailed, key=lambda t: -score_fn(t))
        top_n = max(3, n // 3)
        chosen = ranked[:top_n]
        win = sum(1 for t in chosen if t['day_ret'] > 0) / len(chosen) * 100
        avg_ret = np.mean([t['day_ret'] for t in chosen])
        ablation[strategy_name] = {
            'chosen': len(chosen),
            'win_rate': round(win, 1),
            'avg_ret': round(avg_ret, 2),
        }

    # ---- 3) 自动调参建议 ----
    recommendations = []
    # 按 practical 强度排序
    rank_order = {'强有效': 3, '中等有效': 2, '弱有效': 1, '! 噪声': 0, '无变化': 0}
    ranked_dims = sorted(dimensions, key=lambda d: rank_order[correlations[d]['practical']], reverse=True)
    best = ranked_dims[0]
    worst = ranked_dims[-1]
    best_corr = correlations[best]
    worst_corr = correlations[worst]

    # 提升最强维度的权重
    if best_corr['practical'] in ('强有效', '中等有效'):
        recommendations.append(
            f"维度「{dim_name_cn(best)}」相关性{correlations[best]['corr']}，胜率差{win_diff_cn(best_corr)}，建议权重提升5-10%"
        )
    # 降低最弱维度的权重
    if worst_corr['practical'] == '! 噪声':
        recommendations.append(
            f"维度「{dim_name_cn(worst)}」相关性近0、胜率差仅{worst_corr['win_diff']}%，判定为噪声，建议权重降到5%以下"
        )
    elif worst_corr['practical'] == '弱有效':
        recommendations.append(
            f"维度「{dim_name_cn(worst)}」偏弱，可考虑权重从{int(WEIGHT_TECH*100 if worst=='tech' else WEIGHT_EARN*100 if worst=='earn' else WEIGHT_FLOW*100 if worst=='flow' else WEIGHT_NEWS*100)}%降到{5 if worst != 'tech' else 15}%"
        )

    # 消融建议
    best_strategy = max(ablation.items(), key=lambda x: x[1]['win_rate'] * 10 + x[1]['avg_ret'])
    if best_strategy[0] != '4维综合':
        recommendations.append(
            f"消融发现「{best_strategy[0]}」策略胜率{best_strategy[1]['win_rate']}%/均收益{best_strategy[1]['avg_ret']}%，比4维全开{best_strategy[1]['win_rate']}更好，建议简化或调权重"
        )
    else:
        recommendations.append(
            f"消融验证：4维综合胜率{best_strategy[1]['win_rate']}%，是{len(ablation)}种策略中最高的，4维体系有效"
        )

    return {
        'sample_size': n,
        'correlations': correlations,
        'ablation': ablation,
        'recommendations': recommendations,
    }


def dim_name_cn(d):
    return {'tech': '技术', 'earn': '业绩', 'flow': '资金', 'news': '消息'}.get(d, d)


def win_diff_cn(c):
    if c['win_diff'] > 0:
        return f"高分组胜率高{c['win_diff']}%"
    elif c['win_diff'] < 0:
        return f"高分组胜率反低{abs(c['win_diff'])}%（反向！）"
    else:
        return "无差异"


def print_attribution_report(attr):
    """打印归因报告"""
    if attr is None:
        print("\n[归因] 暂无回测数据")
        return
    if 'note' in attr:
        print(f"\n[归因] {attr['note']}")
        return

    print("\n" + "=" * 75)
    print(f"  [归因] 4维评分归因分析（样本{attr['sample_size']}笔）")
    print("=" * 75)

    # 相关性表
    print("\n  【1】子分 vs 次日收益 相关性 + 胜率区分度")
    print(f"  {'维度':<8}{'相关性':<10}{'高分组胜率':<14}{'低分组胜率':<14}{'胜率差':<10}{'评价':<10}")
    print("  " + "-" * 70)
    for dim in ['tech', 'earn', 'flow', 'news']:
        c = attr['correlations'][dim]
        print(f"  {dim_name_cn(dim):<8}{c['corr']:+.3f}    "
              f"{c['high_win']}%{'':<8}{c['low_win']}%{'':<8}"
              f"{c['win_diff']:+}%{'':<6}{c['practical']}")

    # 消融
    print("\n  【2】消融实验：4维 vs 单维策略（前1/3样本的胜率）")
    print(f"  {'策略':<14}{'样本':<6}{'胜率':<10}{'均收益':<10}")
    print("  " + "-" * 40)
    for name, s in attr['ablation'].items():
        marker = ' ←' if name == '4维综合' else ''
        print(f"  {name:<14}{s['chosen']:<6}{s['win_rate']}%{'':<5}{s['avg_ret']:+}%{marker}")

    # 建议
    print("\n  [建议] 自动调参建议：")
    for r in attr['recommendations']:
        print(f"     * {r}")
    print("=" * 75)


# ============================================================
# 【新】HTML 报告：把扫描+回测合并成一个漂亮的页面
# ============================================================
def generate_html_report(results, top3, market_info, backtest=None, history_recos=None, attribution=None):
    """生成HTML报告"""
    html_path = "短线工具箱/今日报告.html"
    rows_html = ""
    for idx, r in enumerate(results[:20], 1):
        s = r['subscores']
        # 子分柱状条
        def bar(score, color):
            w = int(score)
            return f'<div style="background:{color};width:{w}px;height:14px;display:inline-block;border-radius:2px"></div>'
        rows_html += f"""
<tr>
  <td>{idx}</td>
  <td><b>{r['code']}</b><br><small>{r['name']}</small></td>
  <td>{r['industry']}</td>
  <td><b>{r['composite']}</b></td>
  <td>{r['price']:.2f}</td>
  <td>{bar(s['tech'], '#4CAF50')}{s['tech']}</td>
  <td>{bar(s['earn'], '#2196F3')}{s['earn']}</td>
  <td>{bar(s['flow'], '#FF9800')}{s['flow']}</td>
  <td>{bar(s['news'], '#9C27B0')}{s['news']}</td>
  <td><small>{'/'.join(r['signals'])}</small></td>
</tr>"""

    # TOP3 卡片
    top3_html = ""
    for i, r in enumerate(top3, 1):
        s = r['subscores']
        bear_items = ''.join(f'<li>{x}</li>' for x in compute_falsification_signals(r))
        top3_html += f"""
<div class="card">
  <h3>#{i} {r['name']} ({r['code']}) — 综合分 {r['composite']}</h3>
  <p><b>行业：</b>{r['industry']} | <b>价格：</b>{r['price']}元 | <b>仓位：</b>{r['position_pct']}%</p>
  <div class="bear-box">
    <b>⚠ 证伪信号（明日跌的可能理由，先看这块再决定要不要买）</b>
    <ol>{bear_items}</ol>
  </div>
  <p><b>4维子分：</b>技术 {s['tech']} | 业绩 {s['earn']} | 资金 {s['flow']} | 消息 {s['news']}</p>
  <p><b>信号：</b>{' / '.join(r['signals'])}</p>
  <p><b>说明：</b>{s['earn_reason']} | {s['flow_reason']} | {s['news_reason']}</p>
</div>"""

    # 回测部分
    bt_html = ""
    if backtest:
        bucket_rows = ""
        for b, s in backtest['bucket_stats'].items():
            bucket_rows += f"<tr><td>{b}</td><td>{s['count']}</td><td>{s['win_rate']}%</td><td>{s['avg_ret']:+.2f}%</td><td>+{s['max_win']}%</td><td>{s['max_loss']}%</td></tr>"
        recs_html = "".join(f"<li>{r}</li>" for r in backtest['recommendations'])
        bt_html = f"""
<div class="section">
  <h2>[回测] 历史回测（近{backtest['days_back']}天）</h2>
  <p><b>样本数：</b>{backtest['total_trades']} | <b>胜率：</b>{backtest['win_rate']}% | <b>均收益：</b>{backtest['avg_return']:+.2f}% | <b>最大亏损：</b>{backtest['max_loss']}%</p>
  <table>
    <tr><th>分桶</th><th>样本</th><th>胜率</th><th>均收益</th><th>最大盈利</th><th>最大亏损</th></tr>
    {bucket_rows}
  </table>
  <h3>[建议] 调参建议</h3>
  <ul>{recs_html}</ul>
</div>"""

    # 归因部分
    attr_html = ""
    if attribution and 'correlations' in attribution:
        corr_rows = ""
        for dim in ['tech', 'earn', 'flow', 'news']:
            c = attribution['correlations'][dim]
            corr_rows += f"<tr><td>{dim_name_cn(dim)}</td><td>{c['corr']:+.3f}</td><td>{c['high_win']}%</td><td>{c['low_win']}%</td><td>{c['win_diff']:+}%</td><td>{c['practical']}</td></tr>"
        abl_rows = ""
        for name, s in attribution['ablation'].items():
            marker = ' ← 当前' if name == '4维综合' else ''
            abl_rows += f"<tr><td>{name}{marker}</td><td>{s['chosen']}</td><td>{s['win_rate']}%</td><td>{s['avg_ret']:+.2f}%</td></tr>"
        attr_recs = "".join(f"<li>{r}</li>" for r in attribution['recommendations'])
        attr_html = f"""
<div class="section">
  <h2>[归因] 4维归因分析（4维评分是否真的有效？）</h2>
  <p><b>样本：</b>{attribution['sample_size']} 笔 | 相关性 > 0.2 = 强有效，< 0.1 = 噪声</p>
  <h3>子分 vs 收益 相关性 + 胜率区分度</h3>
  <table>
    <tr><th>维度</th><th>相关性</th><th>高分组胜率</th><th>低分组胜率</th><th>胜率差</th><th>评价</th></tr>
    {corr_rows}
  </table>
  <h3>消融实验：4维 vs 单维策略</h3>
  <table>
    <tr><th>策略</th><th>样本</th><th>胜率</th><th>均收益</th></tr>
    {abl_rows}
  </table>
  <h3>[建议] 自动调参建议</h3>
  <ul>{attr_recs}</ul>
</div>"""

    # 历史去重
    recos_html = ""
    if history_recos:
        for r in history_recos:
            recos_html += f"<li>{r['date']}: <b>{r['name']}</b> ({r['code']}) 综合分{r['composite']}</li>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>短线操作报告 {TODAY_STR}</title>
<style>
  body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; margin: 20px; background: #f5f5f5; }}
  .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; }}
  .header h1 {{ margin: 0; }}
  .meta {{ color: #ddd; font-size: 14px; margin-top: 8px; }}
  .section {{ background: white; margin: 20px 0; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
  .card {{ background: #f9f9f9; border-left: 4px solid #667eea; padding: 15px; margin: 10px 0; border-radius: 4px; }}
  .bear-box {{ background: #fff3f3; border-left: 3px solid #d32f2f; padding: 10px 12px; margin: 8px 0; border-radius: 4px; }}
  .bear-box ol {{ margin: 6px 0 0 0; padding-left: 22px; }}
  .bear-box ol li {{ color: #b71c1c; margin: 3px 0; line-height: 1.5; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
  th {{ background: #f0f0f0; padding: 8px; text-align: left; }}
  td {{ padding: 8px; border-bottom: 1px solid #eee; }}
  .small {{ color: #888; font-size: 12px; }}
</style>
</head>
<body>
<div class="header">
  <h1>[报告] 短线操作报告 · {TODAY_STR}</h1>
  <div class="meta">模式：{TRADING_MODE} | 大盘：{market_info['rating']} | 扫描 {len(results)} 只 | 资金 {CAPITAL}元</div>
</div>

<div class="section">
  <h2>[推荐] TOP3 推荐（{TRADING_MODE}模式）</h2>
  {top3_html}
</div>

<div class="section">
  <h2>[扫描] 扫描结果前 20</h2>
  <table>
    <tr><th>#</th><th>代码/名称</th><th>行业</th><th>综合分</th><th>价格</th><th>技术</th><th>业绩</th><th>资金</th><th>消息</th><th>信号</th></tr>
    {rows_html}
  </table>
</div>

{bt_html}

{attr_html}

<div class="section">
  <h2>[回顾] 近3日推荐回顾</h2>
  <ul>{recos_html if recos_html else '<li>无</li>'}</ul>
</div>

<div class="section small">
  <p>生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 筛选器 v1.0 4维评分 · {TRADING_MODE}</p>
  <p>! 本报告基于历史数据和技术指标，不构成投资建议</p>
</div>

</body>
</html>"""
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return html_path


# ============================================================
# 【新】CLI 入口参数
# ============================================================
import argparse
def parse_args():
    p = argparse.ArgumentParser(description='短线筛选器 v1.0')
    p.add_argument('--mode', choices=['scan', 'backtest', 'full'], default='scan',
                   help='scan=扫描 backtest=回测 full=扫描+回测+HTML')
    p.add_argument('--days', type=int, default=20, help='回测看最近N天')
    p.add_argument('--trading-mode', choices=['T+1', 'T+0'], default=None,
                   help='覆盖TRADING_MODE配置')
    p.add_argument('--no-dedup', action='store_true', help='关闭智能去重')
    return p.parse_args()


# ============================================================
# 星级评分（沿用v0.3）
# ============================================================
def risk_stars(df):
    c = df['close'].values
    if len(c) < 60: return 0, 0
    cur = c[-1]
    vol_20 = np.std(c[-20:]) / np.mean(c[-20:]) if np.mean(c[-20:]) > 0 else 0
    high_60 = np.max(c[-60:]); low_60 = np.min(c[-60:])
    pos = (cur - low_60) / (high_60 - low_60) if high_60 > low_60 else 0.5
    ma20 = np.mean(c[-20:])
    bias = abs(cur - ma20) / ma20 if ma20 > 0 else 0
    pos_star = min(5, max(1, int(pos / 0.2) + 1))
    return max(1, min(5, round((vol_20*30 + pos*2) * 2))), int(bias * 100)

def opportunity_stars(signals, df):
    if len(df) < 5: return 0
    c = df['close'].values; v = df['volume'].values
    sig_count = len(signals)
    vol_chg = (v[-1] - v[-2]) / v[-2] if v[-2] > 0 else 0
    price_chg = (c[-1] - c[-2]) / c[-2]
    momentum = 1 + (vol_chg + price_chg) / 2
    momentum = max(0.5, min(2.0, momentum))
    return max(1, min(5, round(sig_count * momentum)))

def liquidity_stars(df):
    try:
        amount = df['amount'].iloc[-1]; c = df['close'].iloc[-1]
        if c > 0 and amount > 0:
            turnover = amount / (c * 10000) * 100
        else: turnover = 0
        if turnover < 1: return 1
        elif turnover < 3: return 2
        elif turnover < 5: return 3
        elif turnover < 10: return 4
        else: return 5
    except: return 3

def stars_display(n):
    if n <= 0: return "☆☆☆☆☆"
    n = max(1, min(5, int(n)))
    return "★" * n + "☆" * (5 - n)


# ============================================================
# 证伪门(bear-before-bull): 借鉴 Serenity 反确认偏误设计
# 纯派生自已抓数据(RSI/MACD/布林/乖离/4维子分/板块),不引新数据源
# ============================================================
def compute_falsification_signals(r):
    """
    返回明日可能跌的理由列表(最多 3 条,按严重度降序)。
    用于报告里强制呈现 bear 信号,逼用户先想反面再下单。
    """
    ind = r.get('indicators') or {}
    s = r.get('subscores') or {}
    price = r.get('price') or 0
    bias = r.get('bias') or 0
    sig_count = r.get('signal_count') or 0

    hits = []

    rsi = ind.get('rsi')
    if rsi is not None:
        if rsi >= 75:
            hits.append((3, f"RSI {rsi:.1f} 严重超买,均值回归压力大"))
        elif rsi >= 70:
            hits.append((2, f"RSI {rsi:.1f} 偏超买"))

    if bias and bias >= 8:
        hits.append((3, f"正乖离 {bias}% 过大,易回踩 MA20"))
    elif bias and bias >= 5:
        hits.append((1, f"正乖离 {bias}% 偏高"))

    macd = ind.get('macd_bar')
    if macd is not None and macd <= 0:
        hits.append((3, f"MACD 柱 {macd:.3f} 已转弱,动能衰竭"))

    bb_u = ind.get('bb_upper')
    if bb_u and price and price >= bb_u * 0.98:
        hits.append((2, f"贴近布林上轨({bb_u:.2f}元),涨势末段"))

    earn = s.get('earn', 100)
    if earn <= 40:
        hits.append((2, f"业绩面薄弱({earn}分:{s.get('earn_reason','')}),基本面不撑"))

    flow = s.get('flow', 100)
    if flow <= 40:
        hits.append((2, f"资金面薄弱({flow}分:{s.get('flow_reason','')}),主力承接不足"))

    news = s.get('news', 100)
    if news <= 30:
        hits.append((1, f"消息真空({news}分),无新催化推动"))

    sec = s.get('sector', 50)
    sec_reason = s.get('sector_reason', '')
    if sec <= 35 or ('均涨跌-' in sec_reason and 'MA5向上占比' in sec_reason):
        hits.append((2, f"板块退潮:{sec_reason}"))

    if sig_count <= 1:
        hits.append((1, f"技术信号仅 {sig_count} 个,买点共振不足"))

    hits.sort(key=lambda x: -x[0])
    reasons = [r for _, r in hits[:3]]
    if not reasons:
        return ["未发现明显证伪信号(注意:不代表零风险,大盘突发利空仍可能拖累)"]
    return reasons


# ============================================================
# 【CLI 入口】
# ============================================================
risk_params = init_mode_config(TRADING_MODE)
ARGS = parse_args()
if ARGS.trading_mode:
    TRADING_MODE = ARGS.trading_mode
    risk_params = init_mode_config(TRADING_MODE)
globals().update(risk_params)

print(f"运行模式: {ARGS.mode} | 交易模式: {TRADING_MODE} | 回测天数: {ARGS.days}")

# ============================================================
# 纯回测模式：跳过扫描，直接算胜率
# ============================================================
if ARGS.mode == 'backtest':
    print("\n>>> 回测模式：拉历史评分计算真实表现")
    report = backtest_score_history(days_back=ARGS.days)
    print_backtest_report(report)
    # 【新】分维度归因（复用上面的 report，不再重跑）
    attr = backtest_dimension_attribution(report)
    print_attribution_report(attr)
    if report:
        with open('短线工具箱/回测报告.json', 'w', encoding='utf-8') as f:
            json.dump({k: v for k, v in report.items() if k != 'detailed'}, f, ensure_ascii=False, indent=2)
        print(f"\n[已保存] 短线工具箱/回测报告.json")
    if attr:
        with open('短线工具箱/归因报告.json', 'w', encoding='utf-8') as f:
            json.dump(attr, f, ensure_ascii=False, indent=2)
        print(f"[已保存] 短线工具箱/归因报告.json")
    raise SystemExit(0)


# ============================================================
# 执行大盘分析
# ============================================================
index_data = get_index_data()
market_info = analyze_market(index_data)


# ============================================================
# 一次性拉取个股历史（原 v1 拉了两遍：板块预算 30 天 + 主扫 120 天）
# ============================================================
print("\n拉取个股历史数据...")
all_codes = sampled['code'].tolist()
BATCH = 50
histories = {}  # code -> DataFrame
total = len(all_codes)
t_fetch = time.time()
# 单次会话拉全量, 避免 batch 间重复 login/logout
print(f"  拉取 {total} 只(单会话预计约 {total//50*2}s) ...", end=' ')
t0 = time.time()
histories = batch_get_history(all_codes)
print(f"耗时:{time.time()-t0:.1f}s")
print(f"  共拉取 {len(histories)} 只，总耗时 {time.time()-t_fetch:.1f}s")

# 预建 code → (name, industry) 字典，避免主扫时 O(N) 反查 sampled
code_to_info = dict(zip(sampled['code'], zip(sampled['code_name'], sampled['industry'])))
code_to_industry = {c: i for c, (_, i) in code_to_info.items()}


# ============================================================
# 预计算板块数据（基于已有 histories，不再二次拉取 baostock）
# ============================================================
print("\n预计算板块数据...")
sector_data = {}
for code, df in histories.items():
    if len(df) < 6: continue
    c = df['close'].values
    chg = (c[-1] - c[-2]) / c[-2] * 100 if len(c) >= 2 else None
    ma5 = np.mean(c[-5:]); ma5p = np.mean(c[-6:-1])
    ma5_up = 1 if ma5 > ma5p else 0
    ind = code_to_industry.get(code)
    if ind is None: continue
    sector_data.setdefault(ind, []).append({'chg': chg, 'ma5_up': ma5_up})
print(f"  覆盖 {len(sector_data)} 个行业")


# ============================================================
# 【新】智能去重：加载近3日推荐过的票
# ============================================================
if not ARGS.no_dedup:
    recent_codes, recent_recos = load_recent_recommendations(days=3)
    if recent_codes:
        print(f"\n[去重] 近3日已推荐过 {len(recent_codes)} 只，将跳过: {', '.join(list(recent_codes)[:5])}{'...' if len(recent_codes)>5 else ''}")
    else:
        print("\n[去重] 无历史推荐记录，全市场扫描")
else:
    recent_codes, recent_recos = set(), []
    print("\n[去重] 已禁用 (--no-dedup)")
skipped_dedup = 0


# ============================================================
# 主扫阶段1：便宜过滤（价格/量/名称/去重/技术/业绩/资金）
# 业绩+资金已走预拉缓存（首次调用后变 O(1) dict 查询）
# ============================================================
print("\n开始4维扫描 阶段1: 技术+业绩+资金 ...")
t0 = time.time()
candidates = []
for code, df in histories.items():
    price = df['close'].iloc[-1]
    volume = df['amount'].iloc[-1]
    if price < MIN_PRICE or price > MAX_PRICE: continue
    if volume < MIN_VOLUME: continue
    name, industry = code_to_info.get(code, ('', ''))
    if '*' in name or 'ST' in name or '退' in name: continue

    skip, _ = should_skip_stock(code, name, df, recent_codes)
    if skip:
        skipped_dedup += 1
        continue

    sigs, indicators, tech_sub = detect_signals(df)
    if not sigs: continue
    rsi_val = indicators.get('rsi', 70)
    if market_info['score'] <= 2.5 and rsi_val and rsi_val > 70: continue

    earn_sub, earn_reason = get_earnings_score(code, name)
    if earn_sub == 0:  # 业绩地雷直接淘汰
        continue

    flow_sub, flow_reason = get_capital_flow_score(code)

    candidates.append({
        'code': code, 'name': name, 'industry': industry, 'df': df, 'price': price,
        'sigs': sigs, 'indicators': indicators, 'tech_sub': tech_sub,
        'earn_sub': earn_sub, 'earn_reason': earn_reason,
        'flow_sub': flow_sub, 'flow_reason': flow_reason,
    })
print(f"  阶段1 通过 {len(candidates)} 只 / 共 {len(histories)} 只（去重 {skipped_dedup} 只，耗时 {time.time()-t0:.1f}s）")


# ============================================================
# 主扫阶段2：并发拉公告催化（每只一次 HTTP，单线程下是瓶颈）
# ============================================================
print(f"\n开始4维扫描 阶段2: 并发拉 {len(candidates)} 只公告 ...")
t0 = time.time()
results = []

def _enrich(stock):
    """拉公告 + 算板块分 + 组装结果"""
    news_sub, news_reason, news_tags = get_news_catalyst_score(stock['code'], stock['name'])
    sector_sub, sector_reason = get_sector_rotation_score(stock['industry'], sector_data)
    tech_weighted = stock['tech_sub'] * 0.7 + sector_sub * 0.3
    composite = composite_score(tech_weighted, stock['earn_sub'], stock['flow_sub'], news_sub)
    df = stock['df']
    r_stars, bias_val = risk_stars(df)
    o_stars = opportunity_stars(stock['sigs'], df)
    l_stars = liquidity_stars(df)
    return {
        'code': stock['code'], 'name': stock['name'], 'industry': stock['industry'],
        'price': round(stock['price'], 2),
        'signals': stock['sigs'], 'signal_count': len(stock['sigs']),
        'risk_stars': r_stars, 'opp_stars': o_stars, 'liq_stars': l_stars,
        'bias': bias_val, 'indicators': stock['indicators'],
        'subscores': {
            'tech': round(tech_weighted, 1),
            'earn': stock['earn_sub'], 'earn_reason': stock['earn_reason'],
            'flow': stock['flow_sub'], 'flow_reason': stock['flow_reason'],
            'news': news_sub, 'news_reason': news_reason, 'news_tags': news_tags,
            'sector': sector_sub, 'sector_reason': sector_reason,
        },
        'composite': composite,
    }

# max_workers=5 是经验值：太大可能触发东方财富限流，太小起不到加速效果
with ThreadPoolExecutor(max_workers=5) as ex:
    for r in ex.map(_enrich, candidates):
        results.append(r)
print(f"  阶段2 完成 {len(results)} 只 (耗时 {time.time()-t0:.1f}s)")

print(f"\n4维扫描完成！共 {len(results)} 只股票通过所有过滤（去重跳过 {skipped_dedup} 只）\n")


# ============================================================
# 排序 & 展示
# ============================================================
# 按综合分降序
results.sort(key=lambda x: -x['composite'])

print("=" * 110)
print(f"{'排名':<5}{'代码':<12}{'名称':<8}{'价':<7}{'综合分':<8}{'技术':<6}{'业绩':<6}{'资金':<6}{'消息':<6}{'信号'}")
print("=" * 110)
for idx, r in enumerate(results[:30], 1):
    s = r['subscores']
    sig = '/'.join(r['signals'])
    print(f"{idx:<5}{r['code']:<12}{r['name']:<8}{r['price']:<7.2f}{r['composite']:<8}"
          f"{s['tech']:<6}{s['earn']:<6}{s['flow']:<6}{s['news']:<6}{sig}")

# 详细子分
print("\n" + "-" * 100)
print(f"{'名称':<8}{'业绩原因':<25}{'资金原因':<25}{'消息原因':<30}{'板块原因':<25}")
print("-" * 100)
for r in results[:15]:
    s = r['subscores']
    print(f"{r['name']:<8}{s['earn_reason']:<25}{s['flow_reason']:<25}{s['news_reason']:<30}{s['sector_reason']:<25}")


# ============================================================
# 计算下一个交易日
# ============================================================
def next_trading_day():
    d = TODAY + datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d

NEXT_DAY = next_trading_day()
NEXT_DAY_STR = f"{NEXT_DAY.year}年{NEXT_DAY.month}月{NEXT_DAY.day}日"
NEXT_DAY_FILE = f"{PREDICTION_DIR}/{NEXT_DAY.month}.{NEXT_DAY.day}短线操作.md"


# ============================================================
# 保存CSV
# ============================================================
if results:
    rows_out = []
    for r in results:
        ind = r['indicators']; s = r['subscores']
        rows_out.append({
            '股票代码': r['code'], '股票名称': r['name'], '行业': r['industry'],
            '最新价': r['price'], '综合分': r['composite'],
            '技术子分': s['tech'], '业绩子分': s['earn'], '资金子分': s['flow'],
            '消息子分': s['news'], '板块子分': s['sector'],
            '信号': '/'.join(r['signals']), '信号数': r['signal_count'],
            '风险星级': stars_display(r['risk_stars']),
            '机会星级': stars_display(r['opp_stars']),
            '流动性星级': stars_display(r['liq_stars']),
            '乖离率': f"{r['bias']}%",
            'RSI': f"{ind['rsi']:.1f}" if ind['rsi'] else "N/A",
            'MACD柱': f"{ind['macd_bar']:.4f}" if ind['macd_bar'] else "N/A",
            '业绩说明': s['earn_reason'], '资金说明': s['flow_reason'],
            '消息说明': s['news_reason'], '板块说明': s['sector_reason'],
            '大盘评级': market_info['rating'], '操作建议': market_info['advice'],
        })
    pd.DataFrame(rows_out).to_csv('短线工具箱/筛选结果.csv', index=False, encoding='utf-8-sig')
    print(f"\n已保存到 短线工具箱/筛选结果.csv")


    # ============================================================
    # TOP3 精选 + 动态仓位
    # ============================================================
    top_picks = results[:5]  # 选综合分前5，再具体到3只
    # 优先选MACD红柱的
    top_picks_macd = [r for r in top_picks if r['indicators'].get('macd_bar', 0) > 0]
    top3 = top_picks_macd[:3] if len(top_picks_macd) >= 3 else top_picks[:3]
    # 给每只分配动态仓位
    for r in top3:
        r['position_pct'] = dynamic_position_pct(r['composite'], market_info['level'])


    # ============================================================
    # 生成操作计划 Markdown（T+1版本）
    # ============================================================
    # 大盘指数数据
    index_lines = []
    for code, (name, df) in index_data.items():
        if len(df) < 20: continue
        c = df['close'].values
        day_chg = (c[-1] - c[-2]) / c[-2] * 100 if len(c) >= 2 else 0
        ma5_trend = "↑" if np.mean(c[-5:]) > np.mean(c[-6:-1]) else "↓"
        ma20_trend = "↑" if np.mean(c[-20:]) > np.mean(c[-21:-1]) else "↓"
        vol_20 = np.std(c[-20:]) / np.mean(c[-20:]) * 100
        icon = "▲" if day_chg >= 0 else "▼"
        chg_str = f"{icon}{abs(day_chg):.2f}%"
        index_lines.append(f"| {name} | {chg_str} | {ma5_trend} | {ma20_trend} | {vol_20:.1f}% |")
    index_table = "\n".join(index_lines)

    # 完整信号池
    signal_rows = []
    for r in results:
        ind = r['indicators']
        macd_ok = "OK" if (ind['macd_bar'] and ind['macd_bar'] > 0) else "--"
        sig = '/'.join(r['signals'])
        signal_rows.append(
            f"| {r['code']} | {r['name']} | {r['composite']} | {r['price']:.2f} | {sig} | {macd_ok} |"
        )
    signal_table = "\n".join(signal_rows)

    # TOP3详情（按TRADING_MODE渲染T+1或T+0规则）
    top3_detail = ""
    for i, r in enumerate(top3, 1):
        ind = r['indicators']
        s = r['subscores']
        rsi_str = f"{ind['rsi']:.1f}" if ind['rsi'] else "N/A"
        macd_str = f"{ind['macd_bar']:.3f}" if ind['macd_bar'] else "N/A"
        buy_low = round(r['price'] * 0.97, 2)
        buy_high = round(r['price'] * 1.02, 2)
        position_amt = int(CAPITAL * r['position_pct'] / 100 / r['price']) * r['price']
        rsi_ok = "OK" if (ind['rsi'] and ind['rsi'] <= 70) else "!"
        macd_ok = "OK" if (ind['macd_bar'] and ind['macd_bar'] > 0) else "--"
        bb_u = f"{ind['bb_upper']:.2f}" if ind['bb_upper'] else "N/A"
        bb_m = f"{ind['bb_mid']:.2f}" if ind['bb_mid'] else "N/A"
        bb_l = f"{ind['bb_lower']:.2f}" if ind['bb_lower'] else "N/A"
        news_tags_str = '、'.join(s['news_tags'][:3]) if s['news_tags'] else '无'

        if TRADING_MODE == 'T+1':
            # T+1 规则
            stop_loss = round(r['price'] * (1 + NEXT_DAY_STOP_LOSS_PCT), 2)
            take_profit = round(r['price'] * (1 + NEXT_DAY_TAKE_PROFIT_PCT), 2)
            mode_rules = f"""- **次日止损**：{stop_loss}元（{NEXT_DAY_STOP_LOSS_PCT*100:.0f}%，次日盘中触及即出）
- **次日止盈**：{take_profit}元（+{NEXT_DAY_TAKE_PROFIT_PCT*100:.0f}%减半仓，剩余用2%移动止损）
- **次日T+1规则**（9:25集合竞价 + 9:30-9:45应对）：
  - 高开>+{OPEN_GAP_HIGH*100:.0f}%：集合竞价减半仓锁利，不追
  - 平开±{OPEN_GAP_HIGH*100:.0f}%：按计划持有
  - 低开{OPEN_GAP_LOW*100:.0f}%~-3%：观察10:00修复情况
  - 低开<-3%：开盘第一笔出，承认错误（隔夜消息有鬼）
  - 盘中止损/止盈触发：坚决执行"""
        else:
            # T+0 规则
            stop_loss = round(r['price'] * (1 + INTRADAY_STOP_LOSS_PCT), 2)
            take_profit = round(r['price'] * (1 + INTRADAY_TAKE_PROFIT_PCT), 2)
            mode_rules = f"""- **日内止损**：{stop_loss}元（{INTRADAY_STOP_LOSS_PCT*100:.1f}%，触及即出）
- **日内止盈**：{take_profit}元（+{INTRADAY_TAKE_PROFIT_PCT*100:.1f}%先减半，剩余用{TRAILING_STOP_PCT*100:.0f}%移动止损）
- **当日T+0规则**（9:30-14:30分时波段）：
  - 9:30-9:45方向确认：放量突破→持有；缩量冲高回落→出
  - 10:00-11:30主升段：分时均线之上持有，跌破分时均线减半
  - 13:00-14:00尾盘段：缩量冲高是卖点，放量急拉是加仓信号
  - 14:30硬止损：未达止盈也强制清仓，不留隔夜
  - 严禁追涨杀跌：T+0分时容错率小，要按计划点位执行"""

        top3_detail += f"""
### {i}. {r['code']} {r['name']} ({r['industry']}) | 综合分 {r['composite']}

> **⚠ 证伪信号（先想反面再下单）**
{chr(10).join(f'> {n}. {x}' for n, x in enumerate(compute_falsification_signals(r), 1))}

- **价格**：{r['price']:.2f}元 | **RSI**：{rsi_str} {rsi_ok} | **MACD柱**：{macd_str} {macd_ok}
- **4维子分**：技术{s['tech']} | 业绩{s['earn']}({s['earn_reason']}) | 资金{s['flow']}({s['flow_reason']}) | 消息{s['news']}({news_tags_str})
- **板块**：{s['sector_reason']}
- **技术信号**：{' / '.join(r['signals'])}（{r['signal_count']}信号）
- **布林带**：上轨 {bb_u} / 中轨 {bb_m} / 下轨 {bb_l} | 乖离 {r['bias']}%
- **买入区间**：{buy_low} ~ {buy_high}元
- **仓位**：{r['position_pct']}% ≈ {int(position_amt)}元
{mode_rules}
"""

    # 备选
    others = results[3:8]
    other_rows = ""
    for r in others:
        ind = r['indicators']
        macd_ok = "OK" if (ind['macd_bar'] and ind['macd_bar'] > 0) else "--"
        s = r['subscores']
        other_rows += f"| {r['code']} | {r['name']} | {r['composite']} | {r['price']:.2f} | {s['earn']} | {s['flow']} | {s['news']} | {macd_ok} |\n"

    # 仓位汇总
    pos_rows = ""
    total_pos = 0
    for r in top3:
        amt = int(CAPITAL * r['position_pct'] / 100 / r['price']) * r['price']
        total_pos += amt
        pos_rows += f"| {r['name']} | {r['code']} | {r['position_pct']}% | {int(amt)}元 |\n"

    market_advice = market_info['advice']
    if market_info['level'] == '观望':
        risk_note = "**市场背景**：弱势市场，建议仓位10-20%或不操作"
    elif market_info['level'] == '谨慎':
        if TRADING_MODE == 'T+1':
            risk_note = "**市场背景**：震荡市场，T+1严格止损快进快出，盈利3%减半仓"
        else:
            risk_note = "**市场背景**：震荡市场，T+0日内波段为主，14:30前必清"
    elif market_info['level'] == '稳健':
        risk_note = "**市场背景**：偏强市场，可操作高综合分个股（85+）"
    else:
        risk_note = "**市场背景**：强势市场，可积极操作"

    # 模式说明（header用）
    if TRADING_MODE == 'T+1':
        mode_desc = f"4维扫描 | {TRADING_MODE}模式 | 次日开盘应对"
        weight_desc = f"评分权重：技术{int(WEIGHT_TECH*100)}%+业绩{int(WEIGHT_EARN*100)}%+资金{int(WEIGHT_FLOW*100)}%+消息{int(WEIGHT_NEWS*100)}%"
    else:
        mode_desc = f"4维扫描 | {TRADING_MODE}模式 | 当日分时波段"
        weight_desc = f"评分权重：技术{int(WEIGHT_TECH*100)}%+业绩{int(WEIGHT_EARN*100)}%+资金{int(WEIGHT_FLOW*100)}%+消息{int(WEIGHT_NEWS*100)}%"

    # 风险规则（按模式渲染）
    if TRADING_MODE == 'T+1':
        rules_section = f"""## 四、T+1 模式执行规则（重要！A股不支持当日买卖）

### 核心思维：隔夜发酵概率
T+1 = 买入后无法当日卖出，必须持有到次日。**风险点不在于当日跌多少，而在于次日开盘跳空**。
- 利好消息已被市场消化 → 次日可能高开低走
- 业绩地雷被掩盖 → 次日可能低开5%+
- 板块集体退潮 → 次日可能直接闷杀

### 次日早盘9:25-9:45分情景应对

| 开盘情况 | 应对策略 |
|----------|----------|
| **高开>+2%** | 集合竞价减半仓锁利，剩余看9:30后能否站稳 |
| **平开±2%** | 按计划正常持有，观察9:30-9:45方向 |
| **低开-2%~-3%** | 持有观察，不止损，看10:00能否修复 |
| **低开<-3%** | 9:25集合竞价或9:30第一笔直接出，承认错误 |

### 盘中T+1规则

- **止盈**：盈利达+5%先减半仓，剩余用2%移动止损跟踪
- **止损**：触及-5%立即出，不等收盘
- **时间止损**：14:00后无方向、缩量横盘 → 减仓一半
- **不打板追高**：T+1模式下追板风险极高（次日可能直接低开5%+）

### 弱势市场加严

大盘评级=观望时：
- 单只仓位上限10%（不是25%）
- 止损收窄到-3%
- 只选综合分85+的票"""
        checklist_section = """## 五、买入检查清单（次日早盘用）

- [ ] **大盘**：上证高开或平开（低开>0.5%放弃该股）
- [ ] **个股开盘**：在买入区间内（±2%）
- [ ] **成交量**：开盘5分钟量 > 昨日全天量10%
- [ ] **MACD柱**：仍为正值（开盘后5分钟看1分钟K线确认）
- [ ] **板块**：所属板块未大幅低开
- [ ] **公告**：未突发利空（开盘前查一次）"""
        record_header = "## 八、记录区（T+1模式下次日盘后填）"
    else:
        rules_section = """## 四、T+0 模式执行规则（ETF/可转债适用）

### 核心思维：分时精准度=命
T+0 = 当日可买卖，无隔夜风险，但**没有时间等你"想清楚"**。从买入到卖出的窗口可能就1-2小时。
- 选股标准：日内波动大（振幅>3%）、流动性好
- 买卖点：分时均线 + 量能 + 板块联动
- 资金管理：分批进出，不一次性all in

### 日内分时段规则

| 时段 | 操作要点 |
|------|----------|
| **9:30-9:45** | 方向确认期：放量突破分时均线→试仓；缩量冲高→放弃 |
| **9:45-10:00** | 二次确认：站稳分时均线+量价齐升→加仓 |
| **10:00-11:30** | 主升段：分时均线上方持有，跌破减半 |
| **13:00-14:00** | 尾盘段：缩量冲高=卖点；放量急拉=加仓信号 |
| **14:00-14:30** | 必须减仓一半以上，锁定利润 |
| **14:30-14:57** | 强制清仓时段，无论盈亏都出，不留隔夜 |

### 日内T+0规则

- **止盈**：盈利达+2%先减半仓，剩余用1%移动止损跟踪
- **止损**：触及-1.5%立即出（比T+1更严，分时容错率低）
- **不打板不打板**：T+0追板必被埋
- **不抄底不抄底**：下跌趋势不接飞刀，等反转信号

### 弱势市场加严

大盘评级=观望时：
- 只做早盘30分钟（9:30-10:00）
- 止损收窄到-1%
- 只选综合分85+的票"""
        checklist_section = """## 五、买入检查清单（当日9:30-9:45用）

- [ ] **大盘**：开盘30分钟不大幅杀跌（上证跌幅<0.3%）
- [ ] **分时方向**：股价在分时均线上方运行
- [ ] **量能**：开盘5分钟量 > 昨日5分钟均量1.5倍
- [ ] **板块联动**：所属板块涨幅>0.2%（不逆势）
- [ ] **振幅**：个股5日平均振幅>3%（T+0要波幅）
- [ ] **不在涨停板**：不打板"""
        record_header = "## 八、记录区（T+0模式当日14:30前填）"

    plan_content = f"""# {NEXT_DAY_STR} 短线操作计划 v1.0

> 更新时间：{TODAY_STR}（今日收盘） | {mode_desc}
> 资金：{CAPITAL}元 | 风格：稳健精准 | {weight_desc}
> {risk_note}

---

## 一、大盘趋势分析

**数据来源**：{TODAY_STR} 收盘

| 指数 | 今日涨跌 | MA5方向 | MA20方向 | 波动率 |
|------|---------|---------|---------|--------|
{index_table}

> **{market_info['rating']}**
> {market_info['advice']}

---

## 二、4维扫描结果（{TODAY_STR}收盘数据）

**筛选条件**：股价5-50元，成交额>1000万，至少2个技术信号
**4维过滤**：业绩同比为正 | 5日主力非大额出逃 | 近30日有催化/无利空 | 板块强度中等以上
**评分体系**：综合分 = 技术{int(WEIGHT_TECH*100)}% + 业绩{int(WEIGHT_EARN*100)}% + 资金{int(WEIGHT_FLOW*100)}% + 消息{int(WEIGHT_NEWS*100)}%（各维度0-100）
**当前模式**：{TRADING_MODE}

### 综合分前30名

| 代码 | 名称 | 综合分 | 价格 | 信号 | MACD |
|------|------|--------|------|------|------|
{signal_table}

---

## 三、明日操作计划（{NEXT_DAY_STR}）

{risk_note}

### 优先推荐（按综合分排序）

{top3_detail}

### 备选观察

| 代码 | 名称 | 综合分 | 价格 | 业绩 | 资金 | 消息 | MACD |
|------|------|--------|------|------|------|------|------|
{other_rows.strip()}

---

{rules_section}

---

{checklist_section}

---

## 六、仓位汇总

| 股票 | 代码 | 仓位 | 金额 |
|------|------|------|------|
{pos_rows.strip()}| **合计** | | **{sum(r['position_pct'] for r in top3)}%** | **{int(total_pos)}元** |

> 剩余 {CAPITAL - int(total_pos)}元作为机动资金

---

## 七、风险提示

- 本计划基于历史数据和技术指标，**不构成投资建议**
- {"A股T+1模式下，次日跳空低开风险无法当日对冲" if TRADING_MODE == 'T+1' else "T+0模式下日内分时容错率小，需严格按点位执行"}
- 4维评分体系是过滤器，不是预测器；过滤后的票仍需人工确认
- 弱势市场信号可靠性下降，宁可错过不要做错

---

{record_header}

| 日期 | 股票 | 买入价 | {"次日开盘" if TRADING_MODE == 'T+1' else "当日卖出价"} | {"次日收盘" if TRADING_MODE == 'T+1' else "当日收盘"} | 盈亏% | 触发规则 | 备注 |
|------|------|--------|----------|----------|-------|----------|------|
| | | | | | | | |

---

## 九、复盘区（每周填一次）

| 周次 | 胜率 | 平均收益 | 最大亏损 | 触发最多规则 | 改进点 |
|------|------|----------|----------|--------------|--------|
| W1 | | | | | |
| W2 | | | | | |
| W3 | | | | | |
| W4 | | | | | |

---

*v1.0 4维评分 · {TRADING_MODE}模式 · 动态仓位 | 计划仅供参考，操作风险自负*
"""

    os.makedirs(PREDICTION_DIR, exist_ok=True)
    with open(NEXT_DAY_FILE, 'w', encoding='utf-8') as f:
        f.write(plan_content)
    print(f"已生成操作计划：{NEXT_DAY_FILE}")

    # ============================================================
    # 记录评分历史（用于后续回测）
    # ============================================================
    if top3:
        history_record = {
            'date': TODAY_STR,
            'market_rating': market_info['rating'],
            'top3': [
                {
                    'code': r['code'], 'name': r['name'],
                    'composite': r['composite'],
                    'subscores': r['subscores'],
                    'price': r['price'],
                } for r in top3
            ]
        }
        os.makedirs(os.path.dirname(HISTORY_FILE) or '.', exist_ok=True)
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(history_record, ensure_ascii=False) + '\n')
        print(f"评分已记录到 {HISTORY_FILE}")

    # ============================================================
    # 【新】自动回测 + 归因 + HTML 报告
    # ============================================================
    backtest_report = None
    attr_report = None
    if ARGS.mode == 'full' or os.path.exists(HISTORY_FILE):
        print("\n>>> 跑回测...")
        backtest_report = backtest_score_history(days_back=ARGS.days)
        print_backtest_report(backtest_report)
        if backtest_report:
            with open('短线工具箱/回测报告.json', 'w', encoding='utf-8') as f:
                json.dump({k: v for k, v in backtest_report.items() if k != 'detailed'},
                          f, ensure_ascii=False, indent=2)
        # 归因分析（复用 backtest_report 的 detailed 列表）
        attr_report = backtest_dimension_attribution(backtest_report)
        print_attribution_report(attr_report)
        if attr_report:
            with open('短线工具箱/归因报告.json', 'w', encoding='utf-8') as f:
                json.dump(attr_report, f, ensure_ascii=False, indent=2)

    if ARGS.mode == 'full':
        html_path = generate_html_report(results, top3, market_info, backtest_report, recent_recos, attr_report)
        print(f"\nHTML报告: {html_path}")

    # 总结
    print("\n" + "=" * 60)
    print("[完成] 全部完成！")
    print("=" * 60)
    print(f"  扫描结果:    短线工具箱/筛选结果.csv")
    print(f"  操作计划:    {NEXT_DAY_FILE}")
    print(f"  评分历史:    {HISTORY_FILE}")
    if ARGS.mode == 'full':
        print(f"  HTML报告:    短线工具箱/今日报告.html")
        print(f"  回测报告:    短线工具箱/回测报告.json")
    print("=" * 60)
