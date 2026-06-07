# 双 Agent 协作规范 · Claude Code + Codex

> 🎯 **最终目标**：4 维评分体系胜率 ≥ 70%（当前 ~50%，回测待验证）
> **次目标**：可维护性、可测试性、回测可解释性同步提升
> 适用项目：短线操作 v1（A 股 4 维评分短线筛选器）
> 目的：让两个 AI 各专所长，1+1 > 2
> 版本：v2 · 2026-06-07（v1 → v2: 加质量/Review/工具/目标/Spec维护）

---

## 0. 核心原则（一句话能讲清）

**Claude Code = 架构师 + 对话伙伴**
理解需求、设计方案、review 代码、调试疑难、解释为什么。

**Codex = 程序员 + 重复任务工人**
按 spec 写代码、批量生成测试、写样板、跑长时间任务。

**任何时刻只让一个 agent 改文件。** 同时编辑 = 必然冲突。

---

## 1. 任务路由表（看到任务先查这个）

| 任务类型 | 派给 | 原因 |
|---------|------|------|
| 聊需求、澄清意图 | **Claude** | 需要中文理解 + 反问 |
| 写新功能 + 详细 spec | **Codex** | 按 spec 写就行 |
| 写 pytest 单测（≥5 个） | **Codex** | 批量生成是它强项 |
| 改一个 bug、修一行 | **Claude** | 改动小、上下文重 |
| 性能优化（先 profile 再改） | **Claude** | 需要理解权衡 |
| 重命名 / 改格式 / 跑 linter | **Codex** | 重复劳动 |
| 解释某段代码在干嘛 | **Claude** | 需要语境 |
| 写 README / 用户文档 | **Codex** | 模板化写作 |
| 跑全市场扫描（数据密集） | **Codex** | 长时任务，fire-and-forget |
| 调权重 / 调阈值（业务参数） | **Claude** | 业务判断 |

**模糊地带**：先问用户，不要猜。

---

## 2. 协作工作流（三个常用模板）

### 工作流 A：加新功能
```
1. Claude   跟用户聊需求，出设计方案 + 写 spec 文档
2. Codex    按 spec 实现 + 写自测
3. Claude   review 改动（git diff） + 提改进
4. Claude   合并 + 写 commit message
```

### 工作流 B：修 bug
```
1. Claude   复现 + 定位根因
2. Claude   写最小修复 + regression test
3. Codex    跑完整 pipeline 确认无回归
4. Claude   提交
```

### 工作流 C：性能优化
```
1. Claude   profile + 列方案 + 评估 trade-off
2. Codex    实现具体优化（多写几个版本备选）
3. Claude   跑 benchmark 对比 + 选最优
4. Claude   提交
```

---

## 3. 交接协议（这是关键的，别省）

### Codex 起步必做
```bash
cd "C:\Users\yan\Desktop\短线操作"
git pull                   # 拿最新
git log --oneline -10      # 看最近 10 个 commit
git diff HEAD~1            # 看上一个 commit 是谁改的、为啥
```

### Claude 给 Codex 的 spec 必含
- **目标**：要改的文件 + 函数名（精确到行号）
- **预期行为**：输入 → 输出（举 1-2 个例子）
- **边界条件**：至少 3 个（空值、极端值、异常）
- **明确禁区**：不要改 X、不要碰 Y
- **完成标准**：怎么算"做完了"

### Codex 给 Claude 的回报必含
- diff 摘要（哪些文件 / 多少行）
- 测试结果（passed/failed + 数字）
- **任何 spec 偏离都要说** + 理由（"我改成了 Z 因为 spec 漏了一种情况"）

### 3.4 Handoff Note（写在 commit message body）

下游 agent 拿到 commit 后，看 commit body 就懂上下文，不用追问。

```
## Handoff: <任务名>
- 改了: <filename>（行号范围）
- 为什么: <1-2 句背景>
- 已知问题: <遗留 bug / TODO>
- 下一步: <建议的下个 commit>
- 测试: pytest 通过 12 / 失败 0；扫描跑通 47s
```

下游 agent 接着干前，必读上游的 handoff note。

---

## 4. 冲突解决（两个人意见不同怎么办）

按这个优先级听：
1. **实测数据**：哪个胜率更高、跑得更快 → 听数据
2. **更简单的**：代码更少、改动更小 → KISS
3. **更贴用户原意的**：去问用户

**绝对不要让两个 agent 在 chat 里来回对话辩论** —— 用户是唯一裁判。拍板永远在用户这边。

---

## 5. 禁止事项（违反就要重做）

- ❌ 同时让两个 agent 编辑同一文件
- ❌ 让 Codex 做大架构决策（选库、定模式、设权重）
- ❌ 让 Claude 写 ≥ 20 个测试用例的批量生成
- ❌ 不 commit 就交接（断了就找不回，git 是唯一安全网）
- ❌ 假设 agent 知道对方最近在想什么（必须靠 git diff / spec 传话）

---

## 6. 这个项目的具体分工

### Claude 专攻
- 4 维评分体系的设计、权重调优
- 评分函数逻辑（`get_earnings_score` / `get_capital_flow_score` / `get_news_catalyst_score` / `get_sector_rotation_score`）
- 回测归因（`backtest_score_history` / `backtest_dimension_attribution`）
- 报告版式（HTML / Markdown）
- 跟用户对话澄清需求

### Codex 专攻
- pytest 单测（覆盖所有 `@safe_score` 函数和 `dynamic_position_pct`）
- `.gitignore` / 配置文件
- 长时数据下载脚本（备份全市场 K 线到本地）
- 文档翻译（QUICKSTART.md → 用户友好的话术）
- CI 脚本（每天盘后自动跑 `daily.py --backtest`）

---

## 7. 为什么不"两个一起干"更快

看着像人多了活干得快，其实：
- **冲突成本 > 分工收益**：两份 diff 手动 merge 半小时没了
- **上下文切换**：一个 agent 不知道另一个在干嘛，要么重复劳动要么做错
- **决策权混乱**：两个 agent 给两个方案，用户还是要选 → 反而比一个 agent 慢

分工的本质：**让每个 agent 在自己熟悉的"模式"里工作，模式切换成本 = 0。**

---

## 8. 一句话总结

> **Claude 想，Codex 做。**
> 任何时候只让一个 agent 改文件。
> 谁有疑问，问用户。
> 每次交接前 commit。

---

## 9. Git & GitHub 工作流

> 原则：单人 + AI 协作 = 简化版"团队"规则，但核心纪律不变

### 9.1 核心原则（4 条，死命令）
1. **main 永远可跑**。任何 commit 前先想"如果回滚到我这个 commit，能跑吗？"
2. **不直推 main**。所有改动走 feature/fix/exp 分支，PR 合入。
3. **push 必过目**。AI agent 不擅自 push，最后一步必须用户在 chat 里点头。
4. **机密不出本地**。API key、env、预测结果（涉及具体股票代码）、cache —— 一律在 .gitignore 里。

### 9.2 分支模型

| 分支类型 | 命名 | 用途 | 生命周期 |
|---------|------|------|---------|
| 主分支 | `main` | 稳定可跑版 | 永久 |
| 新功能 | `feature/<name>` | 加新功能 | 合入后删 |
| 修 bug | `fix/<name>` | 修问题 | 合入后删 |
| 实验 | `exp/<name>` | 试错，可乱来 | 失败可保留作纪念 |

例：`feature/sector-dim`、`fix/rsi-overshoot`、`exp/llm-scorer`

### 9.3 Commit 规范

格式：`<type>(<scope>): <subject>`

- type：`feat` / `fix` / `docs` / `refactor` / `test` / `perf` / `chore`
- scope 可选：模块名（scorer / html / config）
- subject：≤ 50 字，中文 OK，但**动词开头**

例：
```
feat(scorer): 加板块联动维度（5 → 6 维）
fix(dedup): 5d涨幅>5% 改成 >8% 减少误杀
docs(agile): 更新 AGENTS.md 加 git 工作流
chore: 删 v8 备份
```

### 9.4 不进 git 的（执行项）
详见 `.gitignore`，分类：

| 类别 | 例 |
|------|-----|
| 生成结果 | `短线操作md文档/*.md`（整个文件夹）、`短线工具箱/今日报告.html` |
| 历史 | `短线工具箱/历史评分.jsonl`、`筛选结果.csv` |
| 敏感 | `.env`、`*api_key*`、`*token*` |
| 缓存 | `__pycache__/`、`.pytest_cache/`、`venv/` |
| IDE | `.vscode/`、`.idea/`、`*.swp` |
| 备份 | `*_backup_*.py` |

### 9.5 Push 协议（每次必走）
```
1. AI 改完代码，本地 commit
2. git diff HEAD~1 给用户看
3. 用户在 chat 里过目
4. 用户说"OK push"或"先改 X"或"撤回"
5. AI 才执行 git push
```

**绝不允许**：AI 改完直接 `git commit && git push` 一气呵成。

### 9.6 版本号（可选，建议）

| 改动类型 | 版本号变化 | 操作 |
|---------|----------|------|
| 评分体系大改 | `v1.0` → `v2.0` | 打 tag + GitHub Release |
| 加新维度 | `v1.0` → `v1.1` | 打 tag |
| bug 修复 | `v1.1.0` → `v1.1.1` | commit 即可 |
| 文案/注释 | 不变 | commit 即可 |

格式：`v<主版本>.<次版本>.<修订号>`

### 9.7 紧急回滚

```bash
# 撤销最近一次 commit（保留改动到工作区）
git reset --soft HEAD~1

# 撤销最近一次 commit（彻底丢弃）
git reset --hard HEAD~1

# 回到某个 tag
git checkout v1.0
```

main 分支坏了 → 5 分钟内回滚到上一个 tag。

---

## 10. 质量标准（让两个 agent 产出一致）

### 10.1 代码风格
- Python 3.10+；可读性 > 聪明
- 函数 ≤ 50 行；单文件 ≤ 2000 行（v1 已 1847，逼近上限）
- 关键函数（评分/回测/仓位/缓存）必加 docstring
- 类型提示：参数/返回值必加；中间变量不强求
- 中文注释 OK，但**只解释 WHY 不解释 WHAT**

### 10.2 测试
- 评分函数、仓位计算、回测逻辑必须有 pytest
- **默认分工**：Codex 写测试，Claude 写实现
- 覆盖率目标：核心逻辑 ≥ 70%
- 用例类型：正常 + 边界（空值/0/负数/极大）+ 异常

### 10.3 Definition of Done（按任务类型）

| 任务类型 | Done 标准 |
|---------|---------|
| Bug 修 | 复现 → 修复 → 加 regression test → 跑通 |
| 新功能 | spec → 实现 → 单测 → 文档 |
| 重构 | 行为不变 + 测试全过 + 行数 ↓ |
| 性能优化 | benchmark 对比 + 可读性不降 |
| 文档更新 | 渲染 OK + 示例可运行 |
| Spec 修改 | commit + 版本号 bump + 顶部 changelog |

---

## 11. Review Checklist（互审用）

收到对方交付，逐项检查：

- [ ] **功能**：spec 都实现了？没漏没多？
- [ ] **范围**：没做 spec 之外的事？scope creep = 退回重做
- [ ] **测试**：单测覆盖关键路径？边界条件？
- [ ] **风格**：跟现有代码一致？没引入新依赖除非必要？
- [ ] **文档**：docstring 写齐？AGENTS.md 规则没违反？
- [ ] **性能**：没引入 N² 或重复 IO？
- [ ] **可运行**：本地跑通 / 测试过？
- [ ] **可回滚**：commit 粒度合理，必要时 `git revert` 即可？

Codex 给 Claude 的活，Claude review；反之亦然。**两人都要过这一关再交给用户。**

---

## 12. 工具链（每个 agent 起步必跑）

```bash
# 改完代码（Claude 跑）
python -m py_compile 筛选明日股票_v1.py
python 筛选明日股票_v1.py --help

# 写完测试（Codex 跑）
pytest -x 短线工具箱/tests/

# 共同
du -sh 短线工具箱/  # 确认历史文件没爆
git status           # 确认 working tree 干净
```

**禁止**：
- ❌ 不告诉用户就 `pip install <新包>`
- ❌ 不写理由就改 `requirements.txt`
- ❌ 任何时候 `git push --force` 到 main
- ❌ 跳过 `--help` 自检直接说"改好了"

---

## 13. 共同目标（防止两个 agent 跑偏）

**最终目的**：4 维评分体系达到 70%+ 胜率

**KPI 监控**：
- 胜率（7 日移动平均，daily backtest）
- 平均收益 / 最大回撤
- 信号稳定性（同票多次推荐的 composite 波动）

**不是目的**（避免误优化）：
- 代码行数最少
- 维度数量最多
- 用最炫的技术栈

**优先级冲突时**（强制排序）：
1. 预测准确 > 代码优雅
2. 简单可测 > 复杂完备
3. 跑得通 > 跑得快
4. 少报错 > 多功能

---

## 14. Spec 维护（规范本身要进化）

- AGENTS.md 有版本号（顶部 `> 版本：v2`）
- 改 spec 本身要 commit，type 用 `docs(agile)`
- 旧规则**标记 deprecated 不删**（保留 6 个月供回溯）
- 新 agent 启动时必读 AGENTS.md
- **版本演进日志**（在 commit 里 + 这里都留一份）：

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 | 2026-06-07 | 初版：双 agent 任务路由 + 交接协议 |
| v2 | 2026-06-07 | 加 §10 质量/§11 Review/§12 工具/§13 目标/§14 Spec 维护/§3.4 Handoff |
| v3 计划 | - | pytest 流程、5 维评分模板、回测 KPI 自动化 |

---

## 15. 什么时候不要分工（直接干，别协作）

**判断标准**：改动 ≤ 5 行 / 1 分钟内能改完 → 不协作，直接做。

例如：
- 改一个变量名
- 改一行 typo
- 删一个空文件
- 加一个 print 日志
- 改一行阈值常量

**反例**（这些要协作）：
- 加新维度（要 spec + 实现 + 测试 + 调权重）
- 重构 ≥ 50 行的函数
- 性能优化（要 profile + 改 + benchmark）

判断不准时 → 走 §1 路由表。

---

## 附录 A · 第一次合作的执行清单

```bash
# 1. 项目已配好 .gitignore（见 .gitignore 文件）
cd "C:\Users\yan\Desktop\短线操作"
ls -la .gitignore AGENTS.md   # 确认两个文件都在

# 2. 初始化 git 仓库 + 第一次 commit（执行前先给用户看 git status）
#    ⚠️ 等用户给完整 git 规范再做

# 3. 安装 Codex CLI（如未装）
npm install -g @openai/codex

# 4. Codex 同步本规范
cd "C:\Users\yan\Desktop\短线操作"
codex  # 进入后说："读 AGENTS.md，按里面的分工干活"
```

---

*这份规范本身也欢迎改。规则定下来就要遵守，规则有问题就要改。*
