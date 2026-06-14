"""
akshare_resilient.py — akshare 降级重试通用模块

6 个数据源统一通过 call_with_fallback() 调用，自动处理：
- 多接口候选降级（第 1 个失败 → 第 2 个 → ...）
- 超时控制（默认 8s，防卡死 30s+）
- 失败重试（默认 2 次，间隔 1s）
- 缓存命中直接返回（当日 + source_name）
- 全失败返回 None（调用方 @safe_score 兜底到 50 分）

用法：
    from 短线工具箱.akshare_resilient import call_with_fallback
    df = call_with_fallback(
        attempts=[(ak.stock_yjbb_em, {'date': '20260331'})],
        cache_key='yjbb',
    )

不引入新依赖（仅 pandas / 标准库）。
"""

import pandas as pd
import time
import datetime
import os

# ============================================================
# 缓存
# ============================================================
_CACHE_DIR = os.path.join(os.path.dirname(__file__), '.akshare_cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
_SESSION_CACHE: dict[str, pd.DataFrame] = {}

# 文件缓存
def _cache_path(key: str) -> str:
    today = datetime.date.today().isoformat().replace('-', '')
    return os.path.join(_CACHE_DIR, f"{today}_{key}.pkl")

def _cache_get(key: str) -> pd.DataFrame | None:
    if key in _SESSION_CACHE:
        return _SESSION_CACHE[key]
    fpath = _cache_path(key)
    if os.path.exists(fpath):
        try:
            df = pd.read_pickle(fpath)
            _SESSION_CACHE[key] = df
            return df
        except Exception:
            pass
    return None

def _cache_set(key: str, df: pd.DataFrame):
    _SESSION_CACHE[key] = df
    try:
        df.to_pickle(_cache_path(key))
    except Exception:
        pass  # 文件缓存失败不阻塞调用
# spec deviation: pickle 代替 parquet (免 pyarrow 依赖)。empty df 当失败触发降级链。

# ============================================================
# 超时装饰器（通过信号实现，仅 Unix 可用；Windows fallback 用 time.sleep 检查）
# ============================================================
def _timeout_call(func, args, kwargs, timeout_s: float):
    """带超时的函数调用。Windows 上利用 _thread + Timer 实现。"""
    import threading
    result_container = []
    exc_container = []

    def worker():
        try:
            r = func(*args, **kwargs)
            result_container.append(r)
        except Exception as e:
            exc_container.append(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        # 线程还在跑，超时了
        raise TimeoutError(f"call timed out after {timeout_s}s")
    if exc_container:
        raise exc_container[0]
    return result_container[0] if result_container else None


# ============================================================
# 核心函数
# ============================================================
def call_with_fallback(
    attempts: list,
    cache_key: str = None,
    timeout: float = 8.0,
    retries: int = 2,
    retry_delay: float = 1.0,
) -> pd.DataFrame | None:
    """按顺序尝试每个接口，全失败返回 None。

    Parameters
    ----------
    attempts : list of (callable, dict)
        接口候选列表，如 [(func1, {'arg': 'val'}), (func2, {'arg': 'val'})]
    cache_key : str, optional
        缓存键，命中直接返回
    timeout : float
        单次调用超时秒数
    retries : int
        每个 attempt 失败后重试次数
    retry_delay : float
        重试间隔秒数

    Returns
    -------
    pd.DataFrame or None
    """
    if cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    for attempt_idx, (func, kwargs) in enumerate(attempts):
        func_name = getattr(func, '__name__', str(func))
        for r in range(retries + 1):
            try:
                result = _timeout_call(func, (), kwargs, timeout)

                if result is None:
                    _log("warn", f"{func_name} 返回 None")
                    break  # 换下一个 attempt
                if isinstance(result, pd.DataFrame):
                    if result.empty:
                        _log("warn", f"{func_name} 返回空 df")
                        break
                else:
                    # 不是 DataFrame 但有值，也接受
                    if cache_key:
                        _cache_set(cache_key, result if isinstance(result, pd.DataFrame) else pd.DataFrame())
                    return result

                # 成功
                if cache_key:
                    _cache_set(cache_key, result)
                return result

            except TimeoutError:
                _log("warn", f"{func_name} attempt {r+1}/{retries+1}: 超时 {timeout}s")
                if r < retries:
                    time.sleep(retry_delay)
                else:
                    break
            except Exception as e:
                _log("warn", f"{func_name} attempt {r+1}/{retries+1}: {type(e).__name__}: {str(e)[:80]}")
                if r < retries:
                    time.sleep(retry_delay)
                else:
                    break

    _log("warn", f"全链失败: key={cache_key}, attempts={len(attempts)}")
    return None


def _log(level: str, msg: str):
    """统一日志，level 仅用于未来扩展（如文件日志）。"""
    print(f"[akshare] {msg}")


# ============================================================
# 缓存统计（用于 pytest 验证）
# ============================================================
def cache_stats() -> dict:
    """返回当前缓存统计。"""
    return {
        'session_keys': list(_SESSION_CACHE.keys()),
        'session_count': len(_SESSION_CACHE),
        'cache_dir': _CACHE_DIR,
        'cache_dir_exists': os.path.exists(_CACHE_DIR),
    }


def clear_cache():
    """清空进程内缓存和当日文件缓存。"""
    _SESSION_CACHE.clear()
    import glob
    today = datetime.date.today().isoformat().replace("-", "")
    for fp in glob.glob(os.path.join(_CACHE_DIR, today + "_*.pkl")):
        try: os.remove(fp)
        except OSError: pass


# ============================================================
# 源特定辅助函数（可选，调用方也可以直接用 call_with_fallback）
# ============================================================
def fetch_earnings(date_str: str = None) -> pd.DataFrame | None:
    """业绩表，默认最新季度末。"""
    if date_str is None:
        # 复制 _latest_quarter_end 逻辑
        today = datetime.date.today()
        m, y = today.month, today.year
        if m <= 3:      date_str = str(y-1) + '1231'
        elif m <= 6:    date_str = str(y) + '0331'
        elif m <= 9:    date_str = str(y) + '0630'
        else:           date_str = str(y) + '0930'
    import akshare as ak
    return call_with_fallback(
        attempts=[(ak.stock_yjbb_em, {'date': date_str})],
        cache_key=f'yjbb_{date_str}',
        timeout=15,
        retries=1,
    )


def fetch_notice(date_str: str = None) -> pd.DataFrame | None:
    """当日公告全表。"""
    if date_str is None:
        date_str = datetime.date.today().isoformat().replace('-', '')
    import akshare as ak
    return call_with_fallback(
        attempts=[
            (ak.stock_notice_report, {'date': date_str}),
        ],
        cache_key=f'notice_{date_str}',
        timeout=10,
    )


def fetch_lhb() -> pd.DataFrame | None:
    """近一月龙虎榜全表。"""
    import akshare as ak
    return call_with_fallback(
        attempts=[(ak.stock_lhb_stock_statistic_em, {'symbol': '近一月'})],
        cache_key='lhb',
        timeout=10,
        retries=1,
    )



def fetch_lhb_inst() -> pd.DataFrame | None:
    """近一月机构席位追踪全表(P1)。ak.stock_lhb_jgstatistic_em 返回 ~100 条。"""
    import akshare as ak
    return call_with_fallback(
        attempts=[(ak.stock_lhb_jgstatistic_em, {'symbol': '近一月'})],
        cache_key='lhb_inst',
        timeout=10,
        retries=1,
    )

def fetch_fund_flow_rank(indicator: str = '5日') -> pd.DataFrame | None:
    """主力资金流排名表。代理封push2.eastmoney.com，不重试。"""
    import akshare as ak
    return call_with_fallback(
        attempts=[
            (ak.stock_individual_fund_flow_rank, {'indicator': indicator}),
            (ak.stock_individual_fund_flow, {'stock': '600000', 'market': 'sh'}),
        ],
        cache_key=f'fundflow_{indicator}',
        timeout=8,
        retries=0,
    )


def fetch_hsgt(symbol: str) -> pd.DataFrame | None:
    """个股北向资金持股明细。非HSGT标的直接返回None，不重试。"""
    import akshare as ak
    return call_with_fallback(
        attempts=[(ak.stock_hsgt_individual_em, {'symbol': symbol})],
        timeout=8,
        retries=0,
    )


def fetch_news(symbol: str) -> pd.DataFrame | None:
    """个股新闻。"""
    import akshare as ak
    return call_with_fallback(
        attempts=[(ak.stock_news_em, {'symbol': symbol})],
        timeout=10,
    )


def fetch_zt_pool(date: str | None = None) -> pd.DataFrame | None:
    """涨停股池 21 字段(v1.3)。ak.stock_zt_pool_em 默认拉今日。
    date 形如 '20260614'。"""
    import akshare as ak
    if date is None:
        from datetime import datetime
        date = datetime.now().strftime('%Y%m%d')
    return call_with_fallback(
        attempts=[(ak.stock_zt_pool_em, {'date': date})],
        cache_key=f'zt_pool_{date}',
        timeout=10,
        retries=1,
    )


def fetch_market_activity() -> pd.DataFrame | None:
    """乐咕乐股市场活跃度(v1.3)。ak.stock_market_activity_legu 返回 1 行
    含'涨停'/'跌停'/'连板'等字段。"""
    import akshare as ak
    return call_with_fallback(
        attempts=[(ak.stock_market_activity_legu, {})],
        cache_key='market_activity',
        timeout=10,
        retries=1,
    )
