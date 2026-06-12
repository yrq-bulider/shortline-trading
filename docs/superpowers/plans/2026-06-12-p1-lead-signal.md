# P1 先行信号升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 升级 v1.1 消息面里的两个先行信号源（北向 / 龙虎榜），更贴近机构 4-6 周动作。零新数据源，零新依赖。

**Architecture:** 单文件改动（`筛选明日股票_v1.py`）+ 单测试文件（`短线工具箱/tests/test_p1_lead_signal.py`）+ 单 README 段。北向 1 行 + 龙虎榜 ~30 行（新增预拉函数 + 评分函数叠加机构加成）。所有失败路径降级到 v1.1 行为，不破坏 4 维稳定性。

**Tech Stack:** Python 3.10+ / akshare（已有）/ pytest（已有）

**Spec:** `docs/superpowers/specs/2026-06-12-p1-lead-signal-design.md`

---

## File Structure

| 文件 | 操作 | 行数预期 | 职责 |
|------|------|---------|------|
| `筛选明日股票_v1.py` | Modify | +40 | 北向 5→3；import 列表加 `fetch_lhb_inst`；新增 `_load_lhb_inst_table`；改 `get_lhb_score` |
| `短线工具箱/akshare_resilient.py` | Modify | +10 | 追加 `fetch_lhb_inst` 包装（ak.stock_lhb_jgstatistic_em） |
| `短线工具箱/tests/test_p1_lead_signal.py` | Create | ~100 | 6 用例（北向 2 + 龙虎 4） |
| `README.md` | Modify | +20 | 加 §先行信号升级 段 |
| `AGENT_LOG.md` | Modify（不入 git） | +1 | 历史事件追一条 |

**不动**：`短线工具箱/scorer.py` / `WEIGHT_*` / `NEWS_SUB_WEIGHTS` / 证伪门 / 仓位规则

---

## Task 1: 北向 5 日 → 3 日改造

**Files:**
- Modify: `筛选明日股票_v1.py:737,741`（2 处替换）
- Create: `短线工具箱/tests/test_p1_lead_signal.py`

- [ ] **Step 1: 写失败测试 — 北向 3 日窗口验证**

在 `短线工具箱/tests/` 下新建 `test_p1_lead_signal.py`：

```python
"""v1.2 P1 先行信号升级测试 — 北向 5→3 日 + 龙虎榜机构席位加成。

注意：主程序模块名以中文开头（筛选明日股票_v1.py），需要从父目录 import。
参见 test_scorer.py 的 sys.path 引导。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import pandas as pd
from unittest.mock import patch


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
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd "C:\Users\yan\Desktop\短线操作" && pytest 短线工具箱/tests/test_p1_lead_signal.py -v`

Expected: `test_hsgt_3d_window_and_label` FAIL（reason 包含 "5日北向" 而不是 "3日北向"）；`test_hsgt_3d_negative` FAIL（同上）。

- [ ] **Step 3: 改 `筛选明日股票_v1.py:723-741` 北向函数**

把 `get_hsgt_score` 改为：

```python
@safe_score('北向失败')
def get_hsgt_score(code):
    """北向资金 3 日净流入子分 0-100（v1.2 P1：5→3 日，反应更灵敏）。"""
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
    flow_3d = df[flow_col].head(3).sum()  # v1.2 P1: 5→3 日
    score = 50 + flow_3d / 100000000 * 40
    score = max(0, min(100, round(score)))
    direction = "流入" if flow_3d > 0 else "流出"
    return score, f"3日北向{direction}{abs(flow_3d)/100000000:.2f}亿"
```

**改动点**（4 处）:
1. docstring 加 `(v1.2 P1：5→3 日，反应更灵敏)`
2. `len(df) < 5` → `len(df) < 3`
3. `flow_5d = df[flow_col].head(5).sum()` → `flow_3d = df[flow_col].head(3).sum()` + 注释
4. `f"5日北向{...}"` → `f"3日北向{...}"`（reason 字符串）

- [ ] **Step 4: 跑测试，确认通过**

Run: `cd "C:\Users\yan\Desktop\短线操作" && pytest 短线工具箱/tests/test_p1_lead_signal.py::test_hsgt_3d_window_and_label 短线工具箱/tests/test_p1_lead_signal.py::test_hsgt_3d_negative -v`

Expected: 2 passed

- [ ] **Step 5: 主程序自检**

Run: `cd "C:\Users\yan\Desktop\短线操作" && python -m py_compile 筛选明日股票_v1.py && python -c "import 筛选明日股票_v1; print('import ok')"`

Expected: 无 SyntaxError，输出 `import ok`

- [ ] **Step 6: Commit**

```bash
cd "C:\Users\yan\Desktop\短线操作"
git add 筛选明日股票_v1.py 短线工具箱/tests/test_p1_lead_signal.py
git commit -m "$(cat <<'EOF'
feat(news): 北向 5 日 → 3 日异动

P1 先行信号升级第 1 步。3 日累计更灵敏，对短线介入点反应更快。
零新数据源，单函数 4 处改动 + 2 用例。

详见 docs/superpowers/specs/2026-06-12-p1-lead-signal-design.md §2.1
EOF
)"
```

---

## Task 2: 龙虎榜机构席位加成

**Files:**
- Modify: `短线工具箱/akshare_resilient.py`（追加 `fetch_lhb_inst` 包装）
- Modify: `筛选明日股票_v1.py:51`（import 列表加 `fetch_lhb_inst`）+ `:744-784`（新增预拉函数 + 改 `get_lhb_score`）
- Modify: `短线工具箱/tests/test_p1_lead_signal.py`（追加 4 用例）

- [ ] **Step 1: 追加 4 个失败测试**

打开 `短线工具箱/tests/test_p1_lead_signal.py`，在文件末尾追加：

```python


# ============================================================
# 龙虎榜机构席位加成测试
# ============================================================
def _setup_lhb_caches(monkeypatch, base_table, inst_table):
    """辅助：把 _LHB_CACHE / _LHB_INST_CACHE 注入到主模块。"""
    import 筛选明日股票_v1 as m
    monkeypatch.setattr(m, '_LHB_CACHE', base_table)
    monkeypatch.setattr(m, '_LHB_LOADED', True)
    monkeypatch.setattr(m, '_LHB_INST_CACHE', inst_table)
    monkeypatch.setattr(m, '_LHB_INST_LOADED', True)


def test_lhb_inst_50w_bonus(monkeypatch):
    """机构净买 60 万 → +20 分。"""
    base = {'600000': {'代码': '600000', '龙虎榜净买额': 200_000.0}}
    inst = {'600000': {'代码': '600000', '机构净买额': 600_000.0}}
    _setup_lhb_caches(monkeypatch, base, inst)

    import 筛选明日股票_v1 as m
    score, reason = m.get_lhb_score('600000')
    # 基础 50 + 0.2 = 50.2 → 50；机构 ≥50万 +20 → 70
    assert score == 70
    assert '机构净买60万+20' in reason


def test_lhb_inst_10w_bonus(monkeypatch):
    """机构净买 1 万 → +10 分。"""
    base = {'600001': {'代码': '600001', '龙虎榜净买额': 100_000.0}}
    inst = {'600001': {'代码': '600001', '机构净买额': 10_000.0}}
    _setup_lhb_caches(monkeypatch, base, inst)

    import 筛选明日股票_v1 as m
    score, reason = m.get_lhb_score('600001')
    # 基础 50 + 0.1 = 50.1 → 50；机构 >0 +10 → 60
    assert score == 60
    assert '+10' in reason


def test_lhb_not_in_inst_table(monkeypatch):
    """票不在机构表 → 不加成。"""
    base = {'600002': {'代码': '600002', '龙虎榜净买额': 100_000.0}}
    inst = {}  # 600002 不在表
    _setup_lhb_caches(monkeypatch, base, inst)

    import 筛选明日股票_v1 as m
    score, reason = m.get_lhb_score('600002')
    # 基础 50 + 0.1 = 50.1 → 50
    assert score == 50
    assert '机构' not in reason


def test_lhb_inst_table_load_failure(monkeypatch):
    """机构表拉取失败 → _LHB_INST_CACHE = {} → 跳过加成。

    monkeypatch 短线工具箱.akshare_resilient.call_with_fallback 返回 None。
    """
    import 短线工具箱.akshare_resilient as ar
    monkeypatch.setattr(ar, 'call_with_fallback', lambda **kw: None)

    import 筛选明日股票_v1 as m
    monkeypatch.setattr(m, '_LHB_INST_LOADED', False)
    monkeypatch.setattr(m, '_LHB_INST_CACHE', {})

    table = m._load_lhb_inst_table()
    assert table == {}
```

- [ ] **Step 2: 跑 4 个新测试，确认失败**

Run: `cd "C:\Users\yan\Desktop\短线操作" && pytest 短线工具箱/tests/test_p1_lead_signal.py -v -k lhb`

Expected: 4 failed（`fetch_lhb_inst` / `_load_lhb_inst_table` 未定义 + `get_lhb_score` 不接受机构加成）

- [ ] **Step 3: 在 `短线工具箱/akshare_resilient.py` 追加 `fetch_lhb_inst` 包装**

打开 `短线工具箱/akshare_resilient.py`，在 `fetch_lhb()` 函数（line 225-233）之后追加：

```python
def fetch_lhb_inst() -> pd.DataFrame | None:
    """近一月机构席位追踪全表（v1.2 P1）。ak.stock_lhb_jgstatistic_em 返回 ~100 条。
    失败兜底：call_with_fallback 返回 None。"""
    import akshare as ak
    return call_with_fallback(
        attempts=[(ak.stock_lhb_jgstatistic_em, {'symbol': '近一月'})],
        cache_key='lhb_inst',
        timeout=10,
        retries=1,
    )
```

- [ ] **Step 4: 在 `筛选明日股票_v1.py:51` import 列表加 `fetch_lhb_inst`**

打开 `筛选明日股票_v1.py`，把 line 51：

```python
for _k in ["fetch_earnings","fetch_notice","fetch_lhb","fetch_fund_flow_rank","fetch_hsgt","fetch_news"]: locals()[_k] = getattr(_res_mod, _k)
```

改为：

```python
for _k in ["fetch_earnings","fetch_notice","fetch_lhb","fetch_lhb_inst","fetch_fund_flow_rank","fetch_hsgt","fetch_news"]: locals()[_k] = getattr(_res_mod, _k)
```

（仅插入 `"fetch_lhb_inst"`）

- [ ] **Step 5: 在 `筛选明日股票_v1.py:744` 之后插入机构表预拉函数**

在第 744 行的 `# 龙虎榜全市场缓存（v1.1 新增）` 之后、第 745 行的 `_LHB_LOADED = False` 之前，插入：

```python
# 龙虎榜机构席位全市场缓存（v1.2 P1 新增）
_LHB_INST_LOADED = False
_LHB_INST_CACHE = {}


def _load_lhb_inst_table():
    """预拉全市场近 1 月机构席位追踪表。fetch_lhb_inst 返回 ~100 条。
    失败兜底：返回空 dict，机构加成跳过，不影响原 lhb 子分（v1.2 P1）。"""
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
        print(f'[预拉] 机构席位表失败: {type(e).__name__}（跳过机构加成）')
    return _LHB_INST_CACHE
```

- [ ] **Step 6: 改 `get_lhb_score`（line 770-784）加机构加成**

把现有 `get_lhb_score` 替换为：

```python
@safe_score('龙虎失败')
def get_lhb_score(code):
    """龙虎榜子分 0-100 = 上榜净买入（基础）+ 机构席位加成。
    v1.2 P1：叠加机构净买入 > 0 时 +10，≥ 50 万时 +20。
    机构表拉取失败时跳过加成，回退到原 v1.1 行为。"""
    table = _load_lhb_table()
    code6 = normalize_code(code)
    row = table.get(code6)
    if row is None:
        return 50, "近1月未上榜"
    net_buy_col = next((k for k in row.keys() if '净买' in str(k)), None)
    if not (net_buy_col and pd.notna(row[net_buy_col])):
        return 70, "近1月有上榜"

    net_buy = float(row[net_buy_col])  # 元
    base = 50 + net_buy / 1000000
    base = max(0, min(100, round(base)))
    reason = f"龙虎榜净买{net_buy/10000:.0f}万"

    # 机构席位加成（v1.2 P1）
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
```

**改动点**（1 函数整体替换，行为兼容 v1.1）:
- 前 8 行（查 `_LHB_CACHE` + 算基础分）保持 v1.1 行为不变
- 后 16 行（机构加成）新增

- [ ] **Step 7: 跑 4 个新测试，确认通过**

Run: `cd "C:\Users\yan\Desktop\短线操作" && pytest 短线工具箱/tests/test_p1_lead_signal.py -v -k lhb`

Expected: 4 passed

- [ ] **Step 8: 主程序自检**

Run: `cd "C:\Users\yan\Desktop\短线操作" && python -m py_compile 筛选明日股票_v1.py 短线工具箱/akshare_resilient.py && python -c "import 筛选明日股票_v1; print('import ok')"`

Expected: 无 SyntaxError，输出 `import ok`

- [ ] **Step 9: 跑全量测试，确认无回归**

Run: `cd "C:\Users\yan\Desktop\短线操作" && pytest 短线工具箱/tests/ -v`

Expected:
- test_scorer.py 13 passed
- test_akshare_resilient.py 10 passed
- test_p1_lead_signal.py 6 passed（北向 2 + 龙虎 4）
- 0 failed

- [ ] **Step 10: Commit**

```bash
cd "C:\Users\yan\Desktop\短线操作"
git add 筛选明日股票_v1.py 短线工具箱/akshare_resilient.py 短线工具箱/tests/test_p1_lead_signal.py
git commit -m "$(cat <<'EOF'
feat(news): 龙虎榜叠加机构席位加成

P1 先行信号升级第 2 步。
- akshare_resilient 加 fetch_lhb_inst 包装（ak.stock_lhb_jgstatistic_em）
- 筛选明日股票_v1 新增 _load_lhb_inst_table 预拉全市场 ~100 条
- get_lhb_score 叠加机构净买入加成：> 0 +10，≥ 50万 +20
- 拉取失败 / 票不在表 → 跳过加成，回退 v1.1 行为（不破 4 维稳定性）

零新数据源（akshare 已有接口），2 文件改 + 4 用例。

详见 docs/superpowers/specs/2026-06-12-p1-lead-signal-design.md §2.2
EOF
)"
```

---

## Task 3: 集成自检 + 文档

**Files:**
- Modify: `README.md`（加 §先行信号升级 段）
- Modify: `AGENT_LOG.md`（追 1 条历史事件，不入 git）

- [ ] **Step 1: README 文档更新**

打开 `README.md`，在 `## 证伪门（2026-06-10 加 · 借鉴 Serenity 反确认偏误）` 之前，插入新段：

```markdown
## 先行信号升级（v1.2 · 2026-06-12 加）

消息面里 2 个先行信号源升级，更贴近机构 4-6 周动作（Serenity 风格）：

- **北向 3 日异动**——原 5 日累计 → 3 日累计，反应更灵敏
- **龙虎榜 + 机构席位**——原仅看「上榜净买入额」→ 叠加「机构净买入额」
  - 机构净买 > 0 → +10 分
  - 机构净买 ≥ 50 万 → +20 分
  - 机构表拉取失败 → 跳过加成，不影响原 lhb 子分

权重未动（ann 30% / newsfeed 30% / hsgt 20% / lhb 20%）。
```

- [ ] **Step 2: AGENT_LOG.md 追历史事件**

打开 `AGENT_LOG.md`，在 `## § 历史事件` 段最上方（倒序最新一条）插入：

```markdown
- **2026-06-12 13:30 · Codex · 筛选明日股票_v1.py + tests/test_p1_lead_signal.py · P1 实施 · <待填 commit-sha>**
  备注: P1 先行信号升级实施。hsgt 5→3 日 + 龙虎榜加机构席位加成。
  4 个新 pytest 用例全过 + 23 个旧用例无回归。
  Handoff: 下次接手可跑 `python daily.py` 看真实效果，跑 5-10 个交易日后用 `--backtest` 验证胜率。
```

把 `<待填 commit-sha>` 替换为 Task 2 实际 commit 的 SHA（`git log -1 --format=%H` 拿）。

- [ ] **Step 3: 跑最终自检**

Run: `cd "C:\Users\yan\Desktop\短线操作" && python -m py_compile 筛选明日股票_v1.py && python 筛选明日股票_v1.py --help && pytest 短线工具箱/tests/ -v`

Expected:
- `python -m py_compile` 无 SyntaxError
- `--help` 退出 0（§9.1 main 永远可跑 + §12 禁止跳过 --help 自检）
- pytest 全部通过

- [ ] **Step 4: Commit 文档**

```bash
cd "C:\Users\yan\Desktop\短线操作"
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): 加 §先行信号升级 v1.2 段

P1 实施后文档同步。说明 hsgt 3 日异动 + 龙虎榜机构席位加成规则。
权重未动，强调失败降级路径。

对应 commit: <Task 2 commit-sha>
EOF
)"
```

把 `<Task 2 commit-sha>` 替换为实际 SHA。

- [ ] **Step 5: 给用户看 diff**

Run: `cd "C:\Users\yan\Desktop\短线操作" && git log --oneline HEAD~3..HEAD && echo "---" && git diff HEAD~3 --stat`

预期 3 个新 commit 在 main HEAD 前。**不要 push**（§9.5 等用户拍板）。

---

## Self-Review

✅ **Spec 覆盖检查**:
- §2.1 北向 5→3 → Task 1
- §2.2 龙虎榜机构加成 → Task 2
- §3.1 4 用例 → Task 1（2 用例）+ Task 2（4 用例）
- §4 README 段 → Task 3 Step 1
- §3.2 自检 → Task 1 Step 5 / Task 2 Step 6-7 / Task 3 Step 3
- §5 实施步骤 → 整个 plan

✅ **Placeholder 扫描**: 无 "TBD" / "fill in" / "similar to Task N"。所有代码块都完整。

✅ **类型一致性**:
- `_LHB_INST_CACHE` 在 Task 2 Step 3 定义，Step 4 读，Step 5 测试也读 — 命名一致
- `_load_lhb_inst_table` 签名一致（无参数，返回 `dict`）
- `inst_net` 单位统一（元），reason 显示用 `inst_net/10000` 转万

✅ **不破坏现有约束**:
- 不动 `WEIGHT_*` / `NEWS_SUB_WEIGHTS`
- 不动证伪门 / 仓位规则
- 零新数据源
- 失败路径降级到 v1.1
