# 假设台账（assumptions.md）

> **本文件记录 AI 在生成文档过程中自己做出的假设**（不是 constraints.md 里用户亲手填的约束）。
> 每条假设必须写得出"怎么验证"——写不出的，说明它其实是待确认问题，应挪进 `OPEN-QUESTIONS.md`。
> 批 1 验收时逐条过目；假设会渗进架构/接口/任务三处，不拦就会连改三四份文件。

## 一、未验证的假设（按影响排序）

| # | 假设 | 出现在哪 | 错了会怎样 | 怎么验证 | 状态 |
|---|---|---|---|---|---|
| A-01 | 内网有可用的本地 LLM 服务（Ollama 或 vLLM 任一，OpenAI 兼容 API） | architecture（LLM 网关）、constraints（合规）、api-contract（超时） | 网关默认路由落空，慢路/意图抽取不可用 | 问运维要一个内网 endpoint + model 名，跑通 `curl /v1/chat/completions` | ⚙️ 未验证 |
| A-02 | 指标宽表可按 T+1 导出为 CSV/Parquet 文件快照（≤500MB/份） | data-model（快照）、architecture（数据流）、tasks（T-4.0.4） | 快照链路要改为直连库，M2 模块返工 | 找数仓要一份真实导出试装，测 load_snapshot + manifest | ⚙️ 未验证 |
| A-03 | 使用者 10—20 人、同时在线 3—5，无并发写冲突 | constraints §2、architecture（容量）、SQLite 选型 | 若实际 >50 人或多人同时写运营数据，SQLite 写锁成瓶颈（见 ADR-0003 复核条件） | V4.1 上线后看 Observer 审计的并发会话数 | ⚙️ 未验证 |
| A-04 | 企微/飞书有可用 webhook（告警与评审提醒通道） | releases V4.2、ops-runbook（告警通道） | 告警退化为邮件/日志，升级链提醒失效 | 找 IT 要一个测试 webhook，V4.2 联调时发通一条 | ⚙️ 未验证 |
| A-05 | 初始指标域为"贷中风险"5 个指标（fpd30_rate / pass_rate / ks / auc / psi），与 V2/V3 demo 一致 | spec、golden_set、tasks | 若首个真实主题域指标不同，语义层与题库要替换（结构不变） | 首次口径考古（T-4.0.9）输出真实指标清单 | ⚙️ 未验证 |
| A-06 | Owner 每周可投入 ≥30 分钟做评审（3—5 人） | releases V4.2 门禁、ops-runbook（队列健康） | 评审队列积压 → 机制死亡（V3 文档 §10：死因是组织不是技术） | V4.2 试运行 4 周，看队列积压时长 | ⚙️ 未验证 |
| A-07 | Python 3.13 + pandas/numpy/pyyaml/langgraph 版本与开发机一致，内网可 pip 安装 | AGENTS 技术栈、Makefile | 依赖装不上 → V4.0 第一天卡死 | `pip install -r requirements.txt` 在内网开发机实跑 | ⚙️ 未验证 |
| A-08 | raw log 日增量 < 1 万条（10—20 人团队的慢路查询量） | data-model（容量）、ops-runbook | SQLite 一年 365 万行仍可承受，但归档策略要提前 | V4.1 上线两周后统计实际日增 | ⚙️ 未验证 |

## 二、已验证（生成文档期间已确认的事实）

| # | 事实 | 证据 |
|---|---|---|
| V-01 | 四个 .py 单文件的真实依赖：pandas/numpy/pyyaml/langgraph（仅 V2 用 StateGraph/interrupt/InMemorySaver） | 实测 grep import（扫描于 2026-11-01） |
| V-02 | 用户确认：无自研前端 / 文件快照+SQLite / LLM 网关本地优先 / C0 单人开发 | 访谈记录（2026-11-01，spec.md §七） |
| V-03 | V2 九场景、V3 八场景断言当前全部通过 | 交付前实测记录（2026-10-29/30） |
| V-04 | 开发平台为 Trae（规则落 `.trae/rules/`；AGENTS.md 需在 设置>规则>导入设置 开启） | 用户确认（2026-11-02） |

## 三、已推翻（曾假设但不成立）

| # | 原假设 | 推翻原因 |
|---|---|---|
| X-01 | "用户要的是换框架重写" | 框架选型结论：引擎不动外壳可换；本项目的"企业级"= 同一架构的工程化，不是迁移 |
| X-02 | "需要 PostgreSQL" | 用户确认文件快照+SQLite；无并发写需求，PG 是负债（ADR-0003） |

## 四、三条纪律

1. **假设不许静默转正**——验证通过要改状态并记录证据，不许删行。
2. **错了先改文档再改代码**——假设影响架构/接口/任务三处，按 dependencies 倒序修。
3. **与 OPEN-QUESTIONS 的分工**：本文件管"AI 猜的、可验证的"；OPEN-QUESTIONS 管"用户才知道的、待拍板的"。
