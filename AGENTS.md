# AGENTS.md — 项目宪法（风控问数系统）

> **本文件是这套文档体系的最高约束。** 技术栈、硬规则、禁止清单都是**锁定**的。
> 平台为 Trae：关键硬规则已同步进 `.trae/rules/project_rules.md`（alwaysApply 常驻注入）；
> 本文件（AGENTS.md）需在 Trae **设置 > 规则 > 导入设置**里打开"将 AGENTS.md 包含在上下文中"才会进上下文（见 `TRAE-启动手册.md` §三）。

---

## 〇、效力与编号（先读这一节）

**效力规则**（三条，按顺序适用）：

1. **本文件与任何其他文档冲突时，以本文件为准。** 发现冲突不要"两边都改一点"——**改另一份**，并回头检查它有没有被别处引用。
2. 本文件硬规则编号为 **`P-xx`**（P = Policy）。其他文档引用硬规则必须写编号（如"见 `AGENTS.md` P-06`"），**不许复制规则原文**。
3. **改本文件是高风险动作**：改技术栈必须同时补一份 `docs/adr/`；改硬规则必须同时检查所有引用该编号的地方（见第六节对照表）。

---

## 一、这个项目是什么

- **做什么**：语义层驱动的风控指标问数引擎。分析师自然语言问指标 → 系统走已签字口径由纯 Python 计算返回数字；慢路日志经"多人多次确认 + Owner 签字"沉淀为新口径；对外经 REST API 与 MCP Server 两种出口；覆盖问数、模型报告、监控归因、策略回测四个场景。
- **给谁用**：风控策略分析师、指标 Owner、模型团队、值班工程师（内网 10—20 人）。
- **不做什么**（本版本范围的权威表述在 `releases.md`，此处只列永久边界）：**不做自研前端；不做临时快路；不让 LLM 计算或编造任何数字；不接外部客户、不上公网；不做多租户。**

---

## 二、技术栈（锁定，禁止擅自更换）

| 层 | 选型 | 版本 | 为什么 |
|---|---|---|---|
| 语言 | Python | 3.13 | 现有四份代码均为 3.13 |
| 数据处理 | pandas + numpy | 2.x | 计算层全部基于它 |
| 配置 | PyYAML | 6.x | 语义层/治理配置格式 |
| 编排 | LangGraph | 1.2.x | 慢路固定图 + interrupt 人审（ADR-0002） |
| LLM 接入 | 自研网关（OpenAI 兼容协议），本地优先 | — | 数据不出内网（ADR-0004） |
| 存储（运营） | SQLite（内置 sqlite3） | 3.x | 零运维（ADR-0003） |
| 存储（指标） | 文件快照 CSV/Parquet + manifest | — | 可复现（ADR-0006） |
| API / MCP | FastAPI 0.11x / 官方 mcp SDK 1.x | — | 双出口同源（ADR-0005） |
| 测试 | pytest 8.x + FakeLLM | — | 失败场景可复现 |

> **版本号来自开发机实测（2026-11-01），上线以 `requirements.txt` 锁定行为准。更换任何一项必须先改本文件 + 补 ADR。**

---

## 三、目录约定

目录结构的**唯一来源是 `REPO_CONVENTION.md`**，本文件只放指针：

```
src/riskqa/{semantic,data,calc,facts,tools,verify,orchestration,governance,llm,api,mcp,store}/
config/{semantic_view.yaml,governance.yaml}   data/snapshots/   data/ops.db
tests/   evals/   docs/   legacy/（原四个 .py 只读存档）
```

---

## 四、硬规则（每条都可判定是否违反）

| 编号 | 规则 | 违反的后果 |
|---|---|---|
| P-01 | 密钥、token、连接串绝不进代码与版本库，只进环境变量或 `.env`（`.env` 本身进 `.gitignore`） | 安全事件，一票否决 |
| P-02 | 指标数据、raw log、证据快照不出公司内网；LLM 默认路由本地模型；切云端 provider 必须先补 ADR 并经合规审批 | 合规事故，方案作废 |
| P-03 | 计算层禁 LLM：所有指标数值必须由 `calc/` 纯函数产出；LLM 只做意图翻译、路由决策、叙事与材料汇编 | 数字不可信，全线返工 |
| P-04 | 未登记指标一律拒绝（`UnregisteredMetricError`），不猜不填不近似 | 口径失控 |
| P-05 | 未签字指标不进正式语义层：owner / signed_at / changelog 三字段缺一即拒载 | 无主口径流通 |
| P-06 | 叙事层禁裸数字：文本中的数值一律 `{{fact_id}}` 引用，校验闸检查 1 抓裸数字 | 交付回退，事故隐患 |
| P-07 | 引用必须存在：`{{fid}}` 须回 FactStore 查得到，不存在即判失败（查存在性，不查格式） | 编造数字流出 |
| P-08 | FC/MCP 工具的 enum 必须从语义层自动生成，禁止手写复制 | 新指标对模型隐形 |
| P-09 | 快路指标必须同步注册纯函数（`promotion.calc_registered=1`），否则快路拒服 | "能命中不能算"的指标 |
| P-10 | SQL 执行前三闸：只允许 SELECT、强制 LIMIT、注入特征检测；行级权限条件在执行前注入 | 越权/注入/全表扫描 |
| P-11 | 慢路结果与归因结论必须过人审（免审/抽检/必审三级）；未经确认不得标记"已定位" | 未评审结论当事实用 |
| P-12 | raw log 无条件记录、不可变（只 INSERT，保留期 1 年）；正式交付永远基于带 manifest 的快照 | 不可复现、不可审计 |
| P-13 | 晋升必经 Owner 签字；approve 时服务端同事务完成三件事（写 YAML + 固化 evidence 快照 + 注册纯函数），任何一步失败整体回滚 | "签了字没生效" |
| P-14 | 治理配置三层（全局/主题域/临时）变更必须留痕（by + reason + expires）；护栏校验失败时保持旧配置生效，不拒绝服务 | 阈值黑箱、系统带病运行 |
| P-15 | `config/semantic_view.yaml` 与 `config/governance.yaml` 是口径与参数的唯一事实源；代码禁止内嵌默认值；DB 不存口径 | 双事实源 |
| P-16 | 所有出口（API/报告/告警）必须带 AI 显著标识与 data_as_of | 合规缺陷 |
| P-17 | 失败场景一律用 FakeLLM 脚本测试复现，禁止用真模型测失败路径 | 测试 flaky 且烧钱 |
| P-18 | renderer 必须注册后使用，未注册 module 直接抛错，禁止静默跳过（报告少一页是事故） | 静默缺页 |

---

## 五、禁止清单（Reject List · 永久禁止）

- ❌ 在代码里硬编码密钥/连接串/客户明细
- ❌ LLM 生成或修改任何一个指标数字（包括"顺手"重算）
- ❌ 把口径逻辑写进 Dify/nanobot 等外壳（外壳只问数和呈现）
- ❌ 用通用框架的"记忆"替代 evidence 快照
- ❌ 为了让评估通过而改题（`evals/golden_set.yaml` 冻结后）
- ❌ 在用户级规则与本项目规则冲突时按用户级规则执行（以本文件为准）
- ❌ 删 raw log / 改已落库的 fact / 无 ADR 换技术栈

---

## 六、引用本文件的地方（改完随手维护）

| 本文件的哪一条 | 被哪些文档引用 |
|---|---|
| P-01 | security §二/§七；REPO_CONVENTION 密钥节 |
| P-02 | constraints §四；architecture §一/§4.2；adr/0004；security §四 |
| P-03 | architecture §三；spec §5.4；adr/0001；nl2sql-core.md |
| P-04/P-05 | spec §3.1；semantic 模块；api-contract 错误码 |
| P-06/P-07 | spec §3.1；verify 模块；api-contract 错误码；evals |
| P-08/P-09 | tools 模块；releases V4.2 门禁 |
| P-10 | data-model §三；security §三；api-contract |
| P-11 | spec §5.3；orchestration；ops-runbook 告警节 |
| P-12 | data-model §2.1；adr/0006；ops-runbook 保留期清理 |
| P-13 | api-contract §5.3；releases V4.2；glossary（晋升） |
| P-14 | governance 模块；adr/0004；ops-runbook |
| P-15 | REPO_CONVENTION 目录节；data-model 红线 |
| P-16 | api-contract AskResponse；security §六 |
| P-17 | evals/README；quality-gates |
| P-18 | architecture §4.4；tasks T-4.3.2 |
| 技术栈表 | architecture §二；requirements.txt；TRAE-启动手册 |
