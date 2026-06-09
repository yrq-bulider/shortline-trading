# Codex 接力手册 · v1.1 → v1.2

> 接收人：Codex
> 发送人：Claude (v1.1 完成 2026-06-09)
> 协议：AGENTS.md §3 交接协议 + §3.5 双向 Review 原则

## 0. 起步必做

```bash
cd "C:\Users\yan\Desktop\短线操作"
git pull                            # 拿最新
git log --oneline -5                # 看 v1.1 commit (2b9cded)
git show 2b9cded --stat            # 看本会话 285 行 + / 47 行 - 改动
git show 2b9cded -- "筛选明日股票_v1.py" | head -100   # 看清主体逻辑
```

**必读 3 份文件**（按重要性）：
1. `AGENTS.md` v3（§3 交接协议 / §3.5 双向 Review / §6 分工 / §11 Review 清单）
2. `docs/handbox-v1.1.md`（本文件）
3. `筛选明日股票_v1.py` line 628-810（4 源融合实现）

## 1. 现状摘要（v1.1 现状）

### 1.1 已完成
- 权重调整：tech 25 / earn 20 / flow 20 / **news 35**
- news 4 源融合：公告 30% + 新闻 30% + 北向 20% + 龙虎榜 20%
- 公告 akshare 接口 try 多种名字（老/新/备用），全失败降级 50
- emoji 全 ASCII 化（GBK 兼容）
- 股票池取样 sh/sz 平衡（shuffle + random_state=42）
- backtest 段复用 histories 字典（省 days_back×top3 冗余 fetch）
- 归因段多个 dict 缺 key bug 修复

### 1.2 未解决（Codex 接手起点）

| 痛点 | 根因 | 影响 |
|------|------|------|
| 业绩 akshare 失败 (TypeError) | `stock_yjbb_em` 接口不兼容 | 业绩子分 50 兜底，4 维过滤虚化 |
| 资金 akshare 失败 (ProxyError) | `stock_individual_fund_flow_rank` 不兼容 | 资金子分 50 兜底 |
| 公告/新闻/北向/龙虎榜 全靠手动 try | 6 个源各自 try 失败，重复代码 6 处 | 改一处忘改五处 |
| 无 pytest 覆盖 | §6 明确分工是 Codex 活 | 改动 4 维子分后无回归保护 |
| 无 CI 每日盘后自动跑 | 没装 | 周末/节假日手动跑易忘 |

## 2. 派活清单（按优先级）

### 任务 A · akshare 降级重试通用模块 【高优】

**目标**：写 `短线工具箱/akshare_resilient.py`，提供一个通用 wrapper，6 个数据源都能复用。

**接口设计**（建议但不是死命令，按 §3.5 你可调整）：

```python
def call_with_fallback(
    attempts: list,           # [(func, kwargs), (func, kwargs), ...] 多个接口候选
    cache_key: str = None,    # 命中缓存直接返回，不重试
    timeout: float = 8.0,     # 单次调用超时（秒）
    retries: int = 2,         # 失败重试次数（每个 attempt 内）
) -> pd.DataFrame | None:
    """按顺序尝试每个接口，每个内部 retry+timeout，全失败返回 None。
    缓存命中直接返回（可选）。"""
```

**预期行为**：
- 输入：6 个 akshare 数据源 + 各源候选接口名
- 输出：dataframe 或 None
- 内部：try 第 1 个接口 → 失败重试 2 次（间隔 1s）→ 还不成换第 2 个接口 → 全失败 return None + 写日志
- 缓存：当日 (date_str + source_name) 命中直接返回（避免重复拉）

**边界条件**（至少 3 个）：
1. **网络超时**：socket timeout 8s 内必须放弃（akshare 经常卡死 30s+）
2. **接口返回空**：empty dataframe 不算"失败"，但要 warn（可能数据本身没出来，不是接口问题）
3. **全失败返回 None**：调用方按现有 `@safe_score` 装饰器自动降级到 50 分

**禁区**（**不要改**）：
- ❌ 不要动 `筛选明日股票_v1.py` 现有 6 个子分函数（`get_ann_score` / `get_newsfeed_score` / `get_hsgt_score` / `get_lhb_score` / `get_earnings_score` / `get_capital_flow_score`）的内部实现
- ❌ 不要把数据缓存到全局变量（用文件 parquet，每天一个）
- ❌ 不要破坏现有 `@safe_score` 装饰器的接口（`func(...) -> (subscore, reason, [tags])`）
- ❌ 不要引入新 pip 依赖（用标准库 + 已装的 pandas/numpy）

**完成标准**：
- [ ] `短线工具箱/akshare_resilient.py` 写完，~120 行
- [ ] 6 个数据源都改成调用新 wrapper（每个函数瘦身 5-10 行）
- [ ] 跑一次 `python 筛选明日股票_v1.py --mode scan`，6 个子分都正常返回（哪怕降级到 50 也不崩）
- [ ] 写个 `短线工具箱/test_akshare_resilient.py` 单元测试，覆盖：超时 / 空返回 / 全失败 / 缓存命中 4 个场景

---

### 任务 B · pytest 单测覆盖 4 维评分函数 【中优】

**目标**：写 `短线工具箱/tests/test_scorer.py`，覆盖 4 维评分纯算法部分。

**目标函数**（4 个，不依赖 baostock/akshare）：
- `composite_score(tech, earn, flow, news, weights=...)` — 4 维加权
- `dynamic_position_pct(score, market_level)` — 仓位档位
- `safe_score` 装饰器 — 异常兜底

**预期行为**：
- 写 8-10 个 pytest 用例
- 每个用例：mock 输入 → 调函数 → assert 输出

**边界条件**（至少 3 个）：
1. **0/负数/极大** 输入（composite_score 权重和=1，但子分可能=0 或=100）
2. **market_level 异常值**（不是 '积极/稳健/谨慎/观望' 四个之一时仓位）
3. **safe_score 装饰器**：包装的函数 raise 时返回 (50, "label:ExceptionName")

**禁区**：
- ❌ 不要测 `get_earnings_score` / `get_capital_flow_score` 等需要真实 akshare 的（用 mock 太复杂，本任务只测纯算法）
- ❌ 不要改函数实现（只测不改）

**完成标准**：
- [ ] `pytest 短线工具箱/tests/test_scorer.py -v` 全过（≥ 8 个用例）
- [ ] 覆盖率：4 个目标函数 100% 行覆盖
- [ ] 提交后跑一次 `python -m pytest 短线工具箱/tests/ -v` 在 README 里截图

---

### 任务 C · CI 脚本每日盘后自动跑 【低优，可后置】

**目标**：写 `短线工具箱/ci_daily_run.sh`（Windows 用 .bat 或 git bash），每个交易日 15:30 自动跑 `python daily.py --backtest --days 30`。

**预期行为**：
- 拉取最新代码（git pull）
- 跑 `python daily.py --backtest --days 30`
- 把当日生成的 6.10短线操作.md / 历史评分.jsonl 复制到 `短线工具箱/历史/YYYYMMDD/`
- 失败时 stderr 写日志 + 退出码 1

**禁区**：
- ❌ 不要装新依赖（cron 工具用 Windows 自带"任务计划程序"或 git bash + at 命令）

**完成标准**：
- [ ] .bat 或 .sh 脚本可手动跑通
- [ ] 写文档 `docs/ci-daily-run.md` 说 Windows 怎么配任务计划

---

## 3. 自我 Review（Codex 提交前自查）

按 AGENTS.md §11 逐项检查：
- [ ] 功能：6 个数据源都改用新 wrapper 了？没漏？
- [ ] 范围：没做 spec 之外的事？（scope creep = 退回重做）
- [ ] 测试：pytest 覆盖 4 维纯算法？至少 8 个用例？
- [ ] 风格：跟现有 v1 风格一致？（type hint / docstring 中文 OK）
- [ ] 文档：每个新文件有 docstring 说明 WHY 不是 WHAT
- [ ] 性能：没引入 N² 或同步阻塞 IO？
- [ ] 可运行：本地跑通 daily.py 不崩？
- [ ] 可回滚：commit 粒度合理，按 §3.4 写 handoff note？

## 4. 写完回报（按 §3 Codex 回报模板）

回报必须含：
- diff 摘要（哪些文件 / 多少行）
- 测试结果（passed/failed + 数字）
- **任何 spec 偏离都要说** + 理由（"我改成 Z 因为 spec 漏了一种情况"）
- handoff note 写进 commit body（§3.4 格式）

## 5. 给 Claude 的接力信号

完成后说：**"v1.2 接力完成，6 个数据源降级重试 + pytest 8 用例，可 review"**

我会按 §3.5 双向 Review 原则**直接动手 review + 改**，不礼让，但保留核心设计。改完合并 → 由你（用户）拍 push。

---

*本 spec 由 Claude 写于 2026-06-09。如有歧义，按 AGENTS.md §3 让用户拍。*
