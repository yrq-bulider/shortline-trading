# P1 先行信号升级 — 设计文档

> **状态**：✅ 用户拍板（2026-06-12 13:07）
> **作者**：Claude
> **目标 commit**：feat(news): 升级 hsgt 5→3 日 + lhb 加机构席位加成
> **对应路线图**：README §路线图 · P1 先行信号子分
> **版本**：v1

---

## 1. 背景与目标

### 1.1 现状

`筛选明日股票_v1.py` v1.1 已经在消息面里整合了 4 源（NEWS_SUB_WEIGHTS = ann 30% / newsfeed 30% / hsgt 20% / lhb 20%）。其中两个「先行信号」源：

- **北向（hsgt）**：`get_hsgt_score` 用 5 日累计净流入打分。问题是 5 日平均会「摊薄」近 1-2 日的异动，对短线介入点反应慢。
- **龙虎榜（lhb）**：`get_lhb_score` 用全市场近 1 月上榜表的「总净买入额」打分。问题是混入游资/散户席位，看不到真正的「机构动向」。

### 1.2 目标

把这两个先行信号从「温和」升级到「更贴近机构 4-6 周动作」（Serenity 风格），**不新增数据源**、**不破坏 4 维稳定性**。

### 1.3 非目标

- ❌ 新加独立的「先行信号」第 5 维（保持 4 维）
- ❌ 改 NEWS_SUB_WEIGHTS 权重（保持 4 源权重不变）
- ❌ 加新 akshare 依赖（只用已有接口）
- ❌ 触发 证伪门 改造（v2 证伪门是按现子分算的）
- ❌ 改 baostock 流程（baostock 不参与 P1）

---

## 2. 设计

### 2.1 北向升级：5 日 → 3 日异动

**改动位置**：`筛选明日股票_v1.py:737`

```python
# 改前
flow_5d = df[flow_col].head(5).sum()
score = 50 + flow_5d / 100000000 * 40
direction = "流入" if flow_5d > 0 else "流出"
return score, f"5日北向{direction}{abs(flow_5d)/100000000:.2f}亿"

# 改后
flow_3d = df[flow_col].head(3).sum()
score = 50 + flow_3d / 100000000 * 40
direction = "流入" if flow_3d > 0 else "流出"
return score, f"3日北向{direction}{abs(flow_3d)/100000000:.2f}亿"
```

**理由**：3 日更敏感，1 亿净流入对应 +40 分（保持量级一致）。1 行 × 3 处的最小改动。

**回滚**：1 行替换，1 分钟可回。

### 2.2 龙虎榜升级：加「机构席位」加成

**新增函数**：`筛选明日股票_v1.py` 在 `_load_lhb_table()` 之后追加：

```python
# 龙虎榜机构席位全市场缓存（v1.2 P1 新增）
_LHB_INST_LOADED = False
_LHB_INST_CACHE = {}


def _load_lhb_inst_table():
    """预拉全市场近 1 月机构席位追踪表。ak.stock_lhb_jgstatistic_em 返回 ~100 条。
    失败兜底：返回空 dict，机构加成跳过，不影响原 lhb 子分。"""
    global _LHB_INST_LOADED, _LHB_INST_CACHE
    if _LHB_INST_LOADED:
        return _LHB_INST_CACHE
    _LHB_INST_LOADED = True
    try:
        from 短线工具箱.akshare_resilient import call_with_fallback
        import akshare as ak
        df = call_with_fallback(
            attempts=[(ak.stock_lhb_jgstatistic_em, {'symbol': '近一月'})],
            cache_key='lhb_inst',
            timeout=10,
            retries=1,
        )
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

**修改 `get_lhb_score`**：

```python
@safe_score('龙虎失败')
def get_lhb_score(code):
    """龙虎榜子分 0-100 = 上榜净买入（基础）+ 机构席位加成。
    v1.2 P1：叠加机构净买入 > 0 时 +10，> 50 万时 +20。"""
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

**机构表选型**：`ak.stock_lhb_jgstatistic_em(symbol='近一月')` —— 东方财富-龙虎榜-个股-机构席位追踪，**签名与现有 `_load_lhb_table` 完全一致**（同样是 `symbol='近一月'` 默认），便于复用降级模式。

**机构净买列名**：东方财富历史上列名变过几次（`机构净买额` / `净额` / `机构净额`），所以用 `next()` 模糊匹配 `('净买' in k) and ('机构' in k)`，降级到任意 `净买` 列。

**理由**：保留原 lhb 评分 = 兼容；机构加成叠加 = 增量信号。机构表拉取失败 → 完全跳过 → 不影响 4 维稳定性。

**回滚**：删 `_load_lhb_inst_table` + 删 `get_lhb_score` 里 `inst_*` 段，回退到原版本。

### 2.3 数据流（变化部分）

```
每日扫描启动
   ↓
_load_lhb_table()        # 已有：净买入额全表 ~811 条
   ↓
_load_lhb_inst_table()   # 新增：机构席位追踪 ~100 条
   ↓  (并行/串行 — 由 Python 解释器自然串行)
get_lhb_score(code)      # 改：基础分 + 机构加成
   ↓
get_news_catalyst_score  # 不变
   ↓
composite_score          # 不变
```

**预拉时机**：在 `daily.py` 入口处 `init_lhb_cache()` 序列里追加一行（具体行号待实施时确认），保证全市场只拉一次。

### 2.4 错误处理

| 失败点 | 行为 | 4 维影响 |
|--------|------|---------|
| 北向 fetch 失败 | 维持原 `@safe_score` 兜底 50 | 无 |
| 龙虎榜全表 fetch 失败 | 维持原 `print` 跳过 | 无（lhb 子分 50） |
| 机构席位表 fetch 失败 | `_LHB_INST_CACHE = {}`，加成段跳过 | 无（lhb 子分 = 基础分） |
| 机构表有但该票无记录 | `inst_row is None`，跳过 | 无 |
| 机构表有记录但净买 ≤ 0 | 不加分 | 无 |

**设计原则**：所有失败路径都"**降级到 v1.1 行为**"——P1 不会让 4 维评分比 v1.1 差。

### 2.5 不动的东西

- ❌ `WEIGHT_TECH / EARN / FLOW / NEWS`（保持 30/25/20/25）
- ❌ `NEWS_SUB_WEIGHTS`（保持 ann 30 / newsfeed 30 / hsgt 20 / lhb 20）
- ❌ 证伪门 9 条
- ❌ `dynamic_position_pct` 仓位规则
- ❌ 排除清单 / 价格区间
- ❌ 任何 baostock / 资金面 / 业绩面 / 技术面 函数

---

## 3. 测试

### 3.1 单元测试

**新文件**：`短线工具箱/tests/test_lhb_inst.py`

```python
"""v1.2 P1 机构席位加成测试。"""
import pytest
from unittest.mock import patch
import pandas as pd


@pytest.fixture
def fake_lhb_inst_table():
    """模拟 3 只票：机构 +50 万、机构 +1 万、未上榜。"""
    return {
        '600000': {'代码': '600000', '机构净买额': 500000.0},
        '600001': {'代码': '600001', '机构净买额': 10000.0},
        # '600002' 不在表里
    }


def test_lhb_inst_50w_bonus(monkeypatch, fake_lhb_inst_table):
    """机构净买 > 50 万 → +20。"""
    from 筛选明日股票_v1 import _LHB_INST_CACHE, get_lhb_score, _LHB_CACHE
    monkeypatch.setattr('筛选明日股票_v1._LHB_INST_CACHE', fake_lhb_inst_table)
    monkeypatch.setattr('筛选明日股票_v1._LHB_INST_LOADED', True)
    monkeypatch.setattr('筛选明日股票_v1._LHB_CACHE', {
        '600000': {'代码': '600000', '龙虎榜净买额': 200000.0}  # 基础 50+0.2=50.2
    })
    monkeypatch.setattr('筛选明日股票_v1._LHB_LOADED', True)
    score, reason = get_lhb_score('600000')
    assert score == 70  # 50 + 20
    assert '机构净买50万+20' in reason


def test_lhb_inst_10w_bonus(monkeypatch, fake_lhb_inst_table):
    """机构净买 0~50 万 → +10。"""
    from 筛选明日股票_v1 import _LHB_INST_CACHE, get_lhb_score, _LHB_CACHE
    monkeypatch.setattr('筛选明日股票_v1._LHB_INST_CACHE', fake_lhb_inst_table)
    monkeypatch.setattr('筛选明日股票_v1._LHB_INST_LOADED', True)
    monkeypatch.setattr('筛选明日股票_v1._LHB_CACHE', {
        '600001': {'代码': '600001', '龙虎榜净买额': 100000.0}
    })
    monkeypatch.setattr('筛选明日股票_v1._LHB_LOADED', True)
    score, reason = get_lhb_score('600001')
    assert score == 60  # 50 + 10
    assert '+10' in reason


def test_lhb_not_in_inst_table(monkeypatch):
    """票不在机构表 → 不加成。"""
    from 筛选明日股票_v1 import _LHB_INST_CACHE, get_lhb_score, _LHB_CACHE
    monkeypatch.setattr('筛选明日股票_v1._LHB_INST_CACHE', {})
    monkeypatch.setattr('筛选明日股票_v1._LHB_INST_LOADED', True)
    monkeypatch.setattr('筛选明日股票_v1._LHB_CACHE', {
        '600002': {'代码': '600002', '龙虎榜净买额': 100000.0}
    })
    monkeypatch.setattr('筛选明日股票_v1._LHB_LOADED', True)
    score, reason = get_lhb_score('600002')
    assert score == 50  # 基础 50+0.1=50.1 ≈ 50
    assert '机构' not in reason


def test_lhb_inst_load_failure(monkeypatch):
    """机构表拉取失败 → _LHB_INST_CACHE = {}，跳过加成。"""
    from 短线工具箱 import akshare_resilient
    monkeypatch.setattr(akshare_resilient, 'call_with_fallback', lambda **kw: None)
    # 模拟 _load_lhb_inst_table 失败
    from 筛选明日股票_v1 import _load_lhb_inst_table, _LHB_INST_CACHE, _LHB_INST_LOADED
    monkeypatch.setattr('筛选明日股票_v1._LHB_INST_LOADED', False)
    monkeypatch.setattr('筛选明日股票_v1._LHB_INST_CACHE', {})
    table = _load_lhb_inst_table()
    assert table == {}
```

**目标 4 用例**（机构 +20 / 机构 +10 / 不在表 / 拉取失败）。

### 3.2 自检

- `python -m py_compile 筛选明日股票_v1.py` — 必须无 SyntaxError
- `python -c "import 筛选明日股票_v1"` — 必须能 import（§9.1 main 永远可跑）
- `pytest 短线工具箱/tests/test_lhb_inst.py -v` — 4 用例全过
- `pytest 短线工具箱/tests/test_scorer.py -v` — 13 旧用例不回归
- `python daily.py --help` — 退出 0（不能跳过）

### 3.3 不做的测试

- ❌ 端到端 `--backtest`（样本 < 20 笔无意义）
- ❌ 性能 benchmark（3 日 vs 5 日差距 < 1ms）
- ❌ 真实 akshare 调用（用 monkeypatch，避免污染日缓存）

---

## 4. 文档更新

### 4.1 README.md

在 §证伪门 之前新增 §先行信号升级（v1.2）一节：

```markdown
## 先行信号升级（v1.2 · 2026-06-12 加）

消息面里 2 个先行信号源升级，更贴近机构 4-6 周动作（Serenity 风格）：

- **北向 3 日异动**：原 5 日累计 → 3 日累计，反应更灵敏
- **龙虎榜 + 机构席位**：原仅看「上榜净买入额」→ 叠加「机构净买入额」
  - 机构净买 > 0 → +10 分
  - 机构净买 ≥ 50 万 → +20 分
  - 机构表拉取失败 → 跳过加成，不影响原 lhb 子分

权重未动（ann 30% / newsfeed 30% / hsgt 20% / lhb 20%）。
```

### 4.2 不更新的文档

- ❌ QUICKSTART.md（用户视角无变化）
- ❌ AGENTS.md（协作规则无变化）
- ❌ AGENT_LOG.md 历史事件段（实施后追一条即可）

---

## 5. 实施步骤（给 Codex）

按 AGENTS.md §3 工作流 A：

1. **Codex**：本 spec 转 Codex 任务清单（`docs/superpowers/specs/2026-06-12-p1-lead-signal-tasks.md`？ 或直接在 commit message 列出）
2. **Codex**：实施 3 处改动（北向 5→3、新增 `_load_lhb_inst_table`、改 `get_lhb_score`）
3. **Codex**：写 `test_lhb_inst.py` 4 用例
4. **Codex**：跑自检（py_compile + import + pytest）
5. **Claude**：review diff + commit
6. **Claude**：更新 README.md §先行信号升级
7. **Claude**：AGENT_LOG.md 追历史事件
8. **用户**：过目 diff → push 拍板

---

## 6. 风险与回滚

### 6.1 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `ak.stock_lhb_jgstatistic_em` 接口改版 | 中 | 机构表为空 | 失败兜底 → 跳过加成（已设计） |
| 机构表数据延迟/缺失 | 中 | 大量票不在表里 | 不在表 → 跳过（已设计） |
| 3 日累计太敏感，噪声大 | 低 | 胜率下降 | 数据样本 > 20 笔后用 `--backtest` 验证，回滚 head(3) → head(5) |
| 列名变化 `机构净买额` | 低 | 找不到列 | 模糊匹配 `'机构' in k and '净买' in k`，降级到任意 `净买` |
| 主程序 1900 行 → 突破 2000 上限 | 低 | 触发 §10.1 拆分规则 | P1 加 ~40 行 → 1940，仍安全 |

### 6.2 回滚

- **轻度回滚（北向）**：`head(3)` → `head(5)`，单行
- **完全回滚**：删除 `_load_lhb_inst_table` + 删除 `get_lhb_score` 里的 inst 段，1 commit revert 即可

### 6.3 验证窗口

- 跑 5-10 个交易日攒样本
- `python daily.py --backtest` 看 4 维相关性子分（hsgt / lhb 段）
- 胜率无回归 → 保留；下降 > 5% → 回滚 3 日改动
- 机构加成命中率 < 30% → 调阈值（> 50 万 → > 100 万）

---

## 7. 业务约束继承

不违反现有约束：

- ✅ 股票池仍只 00xxx + 60xxx
- ✅ 稳准 > 效率（无并发、零新依赖）
- ✅ AI 不擅自 push（push 等用户拍板）
- ✅ 不动 baostock / 资金面 / 业绩面 / 技术面

---

*Spec 写完。等用户过目 → 移交 writing-plans。*
