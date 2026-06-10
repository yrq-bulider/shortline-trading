"""
test_akshare_resilient.py — akshare_resilient 模块单元测试

覆盖：超时 / 空返回 / 全失败 / 缓存命中 4 个核心场景。
不依赖真实 akshare 网络调用（用 mock 替代）。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import pytest
from unittest.mock import Mock, patch

# 被测试模块
from 短线工具箱.akshare_resilient import (
    call_with_fallback,
    cache_stats,
    clear_cache,
    _SESSION_CACHE,
)


def test_timeout_scenario():
    """场景 1: 超时 — 函数超过 timeout 应抛出 TimeoutError 并返回 None。"""
    clear_cache()

    def slow_func(**kwargs):
        import time
        time.sleep(10)  # 远超 0.1s timeout
        return pd.DataFrame({'a': [1]})

    result = call_with_fallback(
        attempts=[(slow_func, {})],
        timeout=0.1,
        retries=0,
    )
    assert result is None, "超时应返回 None"


def test_empty_return():
    """场景 2: 空返回 — empty df 不算失败但要 warn，返回 None。"""
    clear_cache()

    def empty_func(**kwargs):
        return pd.DataFrame()

    result = call_with_fallback(
        attempts=[(empty_func, {})],
        timeout=2,
        retries=0,
    )
    assert result is None, "空 DataFrame 应返回 None"


def test_none_return():
    """场景 2b: None 返回 — 函数返回 None 视为失败。"""
    clear_cache()

    def none_func(**kwargs):
        return None

    result = call_with_fallback(
        attempts=[(none_func, {})],
        timeout=2,
        retries=0,
    )
    assert result is None, "返回 None 时应返回 None"


def test_all_fail():
    """场景 3: 全失败 — 所有 attempt 都失败返回 None。"""
    clear_cache()

    def fail_func(**kwargs):
        raise ValueError("模拟失败")

    result = call_with_fallback(
        attempts=[(fail_func, {})],
        timeout=2,
        retries=0,
    )
    assert result is None, "全失败应返回 None"


def test_all_fail_with_retries():
    """场景 3b: 全失败 + 重试 — 重试 2 次后仍失败。"""
    clear_cache()
    call_count = []

    def fail_func(**kwargs):
        call_count.append(1)
        raise ValueError("模拟失败")

    result = call_with_fallback(
        attempts=[(fail_func, {})],
        timeout=2,
        retries=2,
    )
    assert result is None
    assert len(call_count) == 1 + 2  # 初始调用 + 2 次重试 = 3


def test_cache_hit():
    """场景 4: 缓存命中 — 首次调用后缓存，第二次直接返回不调函数。"""
    clear_cache()
    call_count = []

    def good_func(**kwargs):
        call_count.append(1)
        return pd.DataFrame({'x': [1, 2, 3]})

    # 第一次：调函数
    r1 = call_with_fallback(
        attempts=[(good_func, {})],
        cache_key='test_cache_hit',
        timeout=2,
        retries=0,
    )
    assert r1 is not None
    assert len(r1) == 3
    assert len(call_count) == 1

    # 第二次：缓存命中，不调函数
    r2 = call_with_fallback(
        attempts=[(good_func, {})],
        cache_key='test_cache_hit',
        timeout=2,
        retries=0,
    )
    assert r2 is not None
    assert len(r2) == 3
    assert len(call_count) == 1, "缓存命中不应再调函数"


def test_fallback_chain():
    """场景 5: 降级链 — 第 1 个失败换第 2 个。"""
    clear_cache()

    def fail_func(**kwargs):
        raise RuntimeError("第一个接口失败")

    def ok_func(**kwargs):
        return pd.DataFrame({'y': [10]})

    result = call_with_fallback(
        attempts=[(fail_func, {}), (ok_func, {})],
        timeout=2,
        retries=0,
    )
    assert result is not None
    assert result['y'].iloc[0] == 10


def test_consecutive_fail():
    """场景 6: attempt 1 重试用完 → 换 attempt 2 → 也失败 → 全链 None。"""
    clear_cache()

    def fail1(**kwargs):
        raise ValueError("接口1失败")

    def fail2(**kwargs):
        raise KeyError("接口2失败")

    result = call_with_fallback(
        attempts=[(fail1, {}), (fail2, {})],
        timeout=2,
        retries=0,
    )
    assert result is None


def test_retry_then_succeed():
    """场景 7: 首次失败，重试成功。"""
    clear_cache()
    call_count = []

    def flaky_func(**kwargs):
        call_count.append(1)
        if len(call_count) < 2:
            raise ConnectionError("首次失败")
        return pd.DataFrame({'z': [7]})

    result = call_with_fallback(
        attempts=[(flaky_func, {})],
        timeout=2,
        retries=2,
    )
    assert result is not None
    assert result['z'].iloc[0] == 7
    assert len(call_count) == 2


def test_cache_stats():
    """场景 8: cache_stats 返回当前缓存信息。"""
    clear_cache()
    stats = cache_stats()
    assert 'session_keys' in stats
    assert 'session_count' in stats
    assert stats['session_count'] == 0

    # 放一点数据
    _SESSION_CACHE['test'] = pd.DataFrame()
    stats2 = cache_stats()
    assert stats2['session_count'] == 1
    clear_cache()
