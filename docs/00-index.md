# 文档索引（docs/00-index.md）

> **本文件是"文件清单与依赖关系"的唯一来源。** 其他文档要提文件数量，引用这里，不要各写一遍。

## 一、阅读路线

### 如果你是第一次读（约 40 分钟）
`constraints` → `spec` 第三节（验收标准）→ `releases` 当前版本 → `00-index`（本文件）

### 如果你要开始写代码（约 2 小时）
`architecture` → `data-model` → `api-contract` → `AGENTS.md` → `tasks.md` 的第一批任务

### 如果你是 Owner（只需评审）
`glossary` 第一节 → `spec` §5.2 晋升流程 → V4.2 上线后的评审材料（引擎生成，不需要读任何设计文档）

### 如果你要评估/调优（V4.1 之后）
`evals/README` → `evals/golden_set.yaml` → `evals/attribution.md` → `experiments/README`

### 如果你要部署/运维（V4.1 之后）
`ops-runbook` → `security` → `quality-gates` 的 CI 编排节

## 二、文件清单与依赖关系

```
constraints ──┬─→ spec ──┬─→ releases ──→ tasks
              │          ├─→ glossary
              │          └─→ quality-gates ──→ tasks
              └─→ architecture ──┬─→ data-model ──┐
                                 ├─→ api-contract ┼─→ openapi.yaml
                                 ├─→ adr/*        │
                                 └─→ security     ↓
                            AGENTS.md ──→ .trae/rules/* ──→ Makefile
risk-register ── 依赖：全部（对抗评审落点）
evals/* ── 依赖：spec 验收标准
ops-runbook ── 依赖：architecture + quality-gates
experiments/* ── 依赖：releases
```

### 根目录（7 份）

| 文件 | 回答什么问题 | 档位 |
|---|---|---|
| `README.md` | 这门面解决什么问题、怎么读 | L1+ |
| `AGENTS.md` | **项目宪法**：硬规则 P-xx，冲突时以它为准 | L1+ |
| `REPO_CONVENTION.md` | 目录结构/命名/提交规范（目录树的唯一来源） | L2+ |
| `START-HERE.md` | 10 分钟上手 + 每天开工收工 | L1+ |
| `OPEN-QUESTIONS.md` | 所有待确认项（阻塞/非阻塞） | L1+ |
| `TRAE-启动手册.md` | Trae 平台特有：规则放哪、首日话术 | L1+ |
| `Makefile` | 固定命令入口 | L2+ |

### docs/ + evals/（根 7 + docs 15 + adr 7 + experiments 1 + evals 5）

| 文件 | 回答什么问题 |
|---|---|
| `docs/00-index.md` | 本文件：文件清单与依赖 |
| `docs/constraints.md` | 硬约束：数据/预算/合规/时间作废线 |
| `docs/spec.md` | 做什么/不做什么/验收标准/业务流程 |
| `docs/releases.md` | 版本范围（V4.0—V4.3）与退出门禁 |
| `docs/glossary.md` | 术语唯一含义（防 AI 一词多义） |
| `docs/assumptions.md` | AI 做过的假设 + 验证状态 |
| `docs/architecture.md` | 五层架构、模块映射、核心链路、容量 |
| `docs/data-model.md` | SQLite 六表 + 快照血缘（表结构唯一来源） |
| `docs/api-contract.md` | REST API v1 契约（8 端点） |
| `docs/openapi.yaml` | 接口机器可读定义 |
| `docs/adr/0000-template.md` | 新 ADR 的填写模板 |
| `docs/adr/0001—0006` | 六个关键技术决策及代价 |
| `docs/security.md` | 威胁模型/权限/注入/审计/合规 |
| `docs/quality-gates.md` | 门禁 QG-xx 编号与阈值 |
| `docs/tasks.md` | 分版本任务清单（让 AI 干活的入口） |
| `docs/risk-register.md` | 风险 R-xx（四视角对抗评审落点） |
| `docs/ops-runbook.md` | 监控/告警/处置/回滚/容量 |
| `docs/experiments/README.md` | 实验记录模板与纪律 |
| `evals/README.md` | 评估体系说明 |
| `evals/golden_set.yaml` | 冻结题库（20 题起） |
| `evals/attribution.md` | 归因手册（效果波动怎么查） |
| `evals/judge-prompt.md` | 自动评分提示词 |
| `evals/seed.sql` | 题库种子数据（fact_application 1200 行 + dim_channel，与 golden_set.yaml 同批冻结） |

### .trae/rules/（5 份）

| 文件 | 加载方式 |
|---|---|
| `project_rules.md` | 常驻（每轮注入，≤180 行） |
| `nl2sql-core.md` | 按需（改语义层/问数链路时） |
| `api-data.md` | 按需（改 API/数据层时） |
| `ops.md` | 按需（部署/运维时） |
| `eval.md` | 按需（改评估集时） |

> **裁剪记录**：L3 模板的 `frontend.md`（前端规则）已删除——本期无自研前端（用户确认），保留即多余。

## 三、每份回答什么问题（速查）

| 问题 | 翻这份 |
|---|---|
| 这个版本做什么/不做什么？ | releases.md + AGENTS.md 第五节 |
| 硬规则有哪些？违反会怎样？ | AGENTS.md 第四节（P-xx） |
| 表怎么建？字段什么含义？ | data-model.md |
| 接口长什么样？错误码是什么？ | api-contract.md + openapi.yaml |
| 某个决策为什么这么做？代价是什么？ | adr/ 对应编号 |
| 任务从哪开始？验收标准是什么？ | tasks.md |
| 怎么算做完了？ | quality-gates.md |
| 出问题了找谁/怎么处置？ | ops-runbook.md |
| 指标口径谁定的？ | semantic_view.yaml 的 owner 字段 |

## 四、全局纪律

1. **同一件事只写在一处**（见各文件开头的"唯一事实来源"标注），别处引用不复制。
2. **引用硬规则写编号**（`见 AGENTS.md P-06`），不复制原文。
3. **目录结构以 `REPO_CONVENTION.md` 为准**，本文与其他文档只放指针。
4. **本文件是文件清单的唯一来源**——说"共 35 份"时以本节表格行数合计为准（根 7 + docs 15 + adr 7 + experiments 1 + evals 5，其中 `.trae/rules/` 5 份单列）。
5. **面向读者的只读目录**见根目录 `文档清单.md`——按开发阶段（批 1–批 5）与"我想解决什么问题"双维度归类，是本项目文档的总览视图。

## 五、扫描记录（brownfield，2026-11-01）

**扫了什么**：工作区根目录 `ls`；四个 `问数Agent_*.py` 的 import 与结构（class/def 清单）；三份 HTML 设计文档全文。

**差异表（文档/假设 vs 实测）**：

| # | 条目 | 文档说法 | 实测结果 | 差异类型 | 处置 |
|---|---|---|---|---|---|
| 1 | 工程结构 | M1–M8 模块化设计 | 四个独立单文件，无包结构 | 缺失 | V4.0 包化（tasks T-4.0.1） |
| 2 | 依赖管理 | （未提及） | 无 requirements/Makefile/tests | 缺失 | V4.0 补（T-4.0.5/6/7） |
| 3 | 语义层形态 | "YAML 外置，Git 同库同权" | YAML 字符串内嵌在 .py 里 | 缺失 | V4.0 外置（T-4.0.2） |
| 4 | 运营数据 | raw log/证据/审计需持久化、1 年保留 | 全在内存，进程退出即失 | 缺失 | V4.0 SQLite 六表（T-4.0.3） |
| 5 | 对外接口 | 框架选型文档：MCP 5 工具 | 未实现 | 缺失 | V4.2（T-4.2.6） |
| 6 | LLM | ModelRouter/FakeLLM/DegradedLLM 抽象已就绪 | 已就绪，无真实 provider | 缺失 | V4.1 网关（T-4.1.7） |
| 7 | 测试 | 8+9 场景断言 | 断言内嵌 main()，非 pytest | 缺失 | V4.0 迁移（T-4.0.6） |
| 8 | 文档与代码一致性 | 三份 HTML 描述的行为 | 与代码一致，无矛盾项 | — | 无需裁决 |

**结论**：无"矛盾"项，全部为"缺失"——本项目 = 把已验证的设计落成生产工程，不是修复跑偏的实现。
