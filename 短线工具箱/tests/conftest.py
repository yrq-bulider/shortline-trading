"""conftest: 通过 sys.meta_path 拦截 筛选明日股票_v1，patch 源码后 exec。

把耗时操作（batch_get_history / get_index_data / backtest_score_history）
替换为空实现，使 import 从 2 分钟降到 <5 秒。
"""
import sys
import os
import re
import importlib.abc
import importlib.machinery

# ============================================================
# 路径常量
# ============================================================
_CWD       = r'C:\Users\yan\Desktop\短线操作'
_MAIN_PATH = os.path.join(_CWD, '筛选明日股票_v1.py')
_AR_PATH   = os.path.join(_CWD, '短线工具箱', 'akshare_resilient.py')
_SC_PATH   = os.path.join(_CWD, '短线工具箱', 'scorer.py')

# ============================================================
# Loader
# ============================================================
class _PatchingLoader(importlib.abc.Loader):
    """Loader that patches source before exec."""

    def create_module(self, spec):
        return None  # use default module creation

    def exec_module(self, module):
        with open(_MAIN_PATH, 'r', encoding='utf-8') as fh:
            src = fh.read()

        # Patch 1: histories = batch_get_history(...) → histories = {}
        src = re.sub(
            r'^histories\s*=\s*batch_get_history\([^)]+\)\s*$',
            'histories = {}   # PATCHED by conftest.py',
            src, flags=re.MULTILINE)

        # Patch 2: index_data = get_index_data() → fake
        # 使用双引号避免字符串内的单引号冲突
        fake_index = (
            '{"rating": "一般", "trend": "震荡", "rating_val": 50,'
            '"index_name": "dummy", "index_code": "dummy",'
            '"sh_close": 3000.0, "hs300_close": 3000.0, "index_chg": 0.0}'
        )
        src = re.sub(
            r'^index_data\s*=\s*get_index_data\(\)\s*$',
            'index_data = ' + fake_index + '   # PATCHED by conftest.py',
            src, flags=re.MULTILINE)

        # Patch 3: report = backtest_score_history(...) → report = None
        src = re.sub(
            r'^report\s*=\s*backtest_score_history\([^)]+\)\s*$',
            'report = None   # PATCHED by conftest.py',
            src, flags=re.MULTILINE)

        # Patch 4: __file__ references → hardcoded paths
        src = src.replace(
            '__file__.replace("筛选明日股票_v1.py", "短线工具箱/akshare_resilient.py")',
            repr(_AR_PATH))
        src = src.replace(
            'os.path.join(os.path.dirname(__file__), "短线工具箱", "scorer.py")',
            repr(_SC_PATH))

        # Patch 5: sys.argv → scan mode
        orig_argv = sys.argv
        sys.argv = ['pytest', '--mode', 'scan']
        try:
            code = compile(src, _MAIN_PATH, 'exec')
            exec(code, module.__dict__)
        finally:
            sys.argv = orig_argv


# ============================================================
# Finder
# ============================================================
class _PatchingFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname != '筛选明日股票_v1':
            return None
        loader = _PatchingLoader()  # no args (reads _MAIN_PATH from closure)
        return importlib.machinery.ModuleSpec(
            fullname, loader, origin=_MAIN_PATH)

    # Python 3.4 fallback
    def find_module(self, fullname, path):
        return self if fullname == '筛选明日股票_v1' else None


# ============================================================
# 注册 finder
# ============================================================
sys.meta_path.insert(0, _PatchingFinder())

# ============================================================
# pytest fixture
# ============================================================
import pytest

@pytest.fixture(scope='session')
def main_mod():
    import 筛选明日股票_v1 as m
    return m
