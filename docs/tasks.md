# 任务清单（tasks.md）
<!-- budget-exempt: 34 个任务的完整台账（做什么/验收/依赖/涉及文件/难度），是"让 AI 干活"的唯一入口，拆分即失效 -->

> **这是"让 AI 干活"的入口。** 每个任务独立完成、独立验收。
> 编号 `T-4.x.y` 连续，**不许断号**；已完成的不删除（标 ✅ + 日期）。
> 验收标准编号对应 `docs/spec.md` 第三节与 `docs/quality-gates.md` 的 QG-xx。

---

## 一、V4.0 底座重构（4 周）

### 1.1 工程化地基

#### T-4.0.1 · src/riskqa 包化迁移 ✅（2026-11-05）
- **做什么**：把 legacy 四个单文件（V1 最小闭环/金融落地/V2 企业版/V3 持续运营）的代码按 M1–M7 + V3 治理 + llm 拆入 `src/riskqa/` 十个子包；**只搬运拆包，不改任何逻辑**。
- **对应验收标准**：releases V4.0 ①；spec §3.1
- **依赖**：无（第一个任务）
- **涉及文件**：`src/riskqa/**`、`legacy/`
- **验收怎么验**：`make test` 全绿（T-4.0.6 建成后）；逐场景输出与 legacy 原版逐字节比对留档
- **收尾核对（2026-11-05）**：包化已完成；6 个纯函数 AST 与 legacy V2 完全一致；17 场景实跑对照留档见 `docs/experiments/2026-11-05-v40-equivalence.md`（A 15 / B 1 / C 1，数值与判定无变化）及三份原始 stdout。
- **难度**：⭐⭐⭐

#### T-4.0.2 · 语义层与治理 YAML 外置 ✅（2026-11-05）
- **做什么**：V2/V3 内嵌的 `SEMANTIC_YAML` / `GOVERNANCE_YAML` 字符串落为 `config/semantic_view.yaml` 与 `config/governance.yaml`；`semantic/` 与 `governance/` 模块改为从文件加载；删除代码内所有口径默认值（P-15）。
- **对应验收标准**：releases V4.0 ③；AGENTS P-15
- **依赖**：T-4.0.1
- **涉及文件**：`config/*.yaml`、`src/riskqa/semantic/`、`src/riskqa/governance/`
- **验收怎么验**：`make semantic-check` + `make governance-check` 通过；grep 代码无 YAML 字面量残留
- **难度**：⭐⭐

#### T-4.0.3 · SQLite store 层 + 六表 ✅（2026-11-05）
- **做什么**：实现 `store/schema.sql`（query_log/fact/review_record/promotion/audit_entry/alert）+ DAO；V3 的内存结构（QueryLog/FactStore/ReviewState）落库；保留期清理函数（1 年）。
- **对应验收标准**：releases V4.0 ④；data-model 全表
- **依赖**：T-4.0.1
- **涉及文件**：`src/riskqa/store/`、`data/ops.db`
- **验收怎么验**：raw log 落库→读出往返一致；fact 落库后 UPDATE 路径不存在（代码审查）；清理函数只删 ts<365d
- **难度**：⭐⭐⭐

#### T-4.0.4 · 快照加载与 manifest 实战
- **做什么**：`data/` 模块补齐 CSV/Parquet 双加载 + manifest（sha256/data_as_of）；向数仓要一份**真实导出**试装（验证 A-02）；缺失值归一（''/unknown/-999 → NaN）只此一次。
- **对应验收标准**：ADR-0006；constraints §三
- **依赖**：T-4.0.1；外部：数仓导出（OPEN-QUESTIONS #2）
- **涉及文件**：`src/riskqa/data/`、`data/snapshots/`
- **验收怎么验**：demo 数据 + 真实导出各跑一次 load_snapshot，manifest 字段齐全；归一化前后行数不变
- **收尾核对（2026-11-05）**：**缺** Parquet 加载（OPEN-QUESTIONS #18）与数仓真实导出（#2）；demo CSV 往返已通过，故不标完成。
- **版本归属**：V4.0 辅助任务，**非四项退出门禁**；未完成部分（Parquet 加载、数仓真实宽表）在 V4.1 启动时重新排期，不改变 V4.1 范围。
- **难度**：⭐⭐

#### T-4.0.5 · requirements.txt 与依赖锁定 ✅（2026-11-05）
- **做什么**：按实测版本写 `requirements.txt`（pandas/numpy/pyyaml/langgraph 1.2.x/pytest/ruff/fastapi/mcp）；内网 pip 源验证（A-07）。
- **对应验收标准**：AGENTS 技术栈表
- **依赖**：无
- **涉及文件**：`requirements.txt`
- **验收怎么验**：新建 venv → `pip install -r requirements.txt` → `make env-check` 全 OK
- **难度**：⭐

#### T-4.0.6 · tests/ pytest 化 ✅（2026-11-05）
- **做什么**：V2 九场景 + V3 八场景断言从 `main()` 迁入 `tests/scenario/`；计算层/闸门/签名/指纹/热度单测入 `tests/unit/`；FakeLLM 脚本机制保留（P-17）。
- **对应验收标准**：releases V4.0 ①；spec §3.2（失败场景可复现）
- **依赖**：T-4.0.1
- **涉及文件**：`tests/**`
- **验收怎么验**：`make test` 全绿；场景数 = 17（V2 九 + V3 八）；失败场景全部脚本化（无真模型调用）
- **难度**：⭐⭐⭐

#### T-4.0.7 · Makefile 与 CI 门禁
- **做的事情**：落地 Makefile 的 V4.0 目标（test/lint/semantic-check/governance-check/docs-check）并**当天实跑**；CI 接 QG-01/03/04。实际载体为 GitHub Actions（`.github/workflows/ci.yml`）；原写的「内网 Git 服务 webhook 或 pre-commit」未采用。
- **对应验收标准**：QG-01/03/04
- **依赖**：T-4.0.5/6/2
- **涉及文件**：`Makefile`、CI 配置
- **验收怎么验**：每个 target 当天实跑一次并通过；CI 红一次故意失败的提交验证门禁会拦
- **收尾核对（2026-11-05）**：`make ci` 全过，GitHub Actions 有 success run，本地三项故障注入均被拦截；线上「故意失败提交」的红色 run 按用户决定不做，故本任务保留未完成（不列入 V4.1 待办）。
- **难度**：⭐⭐

#### T-4.0.8 · 仓库初始化与规则入口确认 ✅（2026-11-05）
- **做什么**：`git init` + 首次提交（文档集全量 + 当前代码）；确认 Trae 侧规则入口：导入设置打开"将 AGENTS.md 包含在上下文中"、`.trae/rules/` 5 份在位；`.gitignore` 按 REPO_CONVENTION §四。
- **对应验收标准**：TRAE-启动手册 §三
- **依赖**：无（可与 T-4.0.1 并行）
- **涉及文件**：`.gitignore`（无新建文件——Trae 原生读 AGENTS.md，不需要 CLAUDE.md 指针文件）
- **验收怎么验**：新开 Trae 对话做握手 P1——AI 说出"V4.0 不做：真 LLM/API/MCP/新指标/前端"
- **难度**：⭐

#### T-4.0.9 · 口径考古（真实指标清单）
- **做的事情**：扫团队存量（老脚本/Excel/历史报告），LLM 提取候选口径（带证据链：文件+行号+原文），冲突原样列出，生成 Owner 问题清单；**不签字不入库**（考古产出 = 问题清单，不是 YAML）。
- **对应验收标准**：落地方案 §4.3 四指标（证据率≥90%/冲突清零率100%/考古发现率/人审<2min）
- **依赖**：T-4.0.2；外部：Owner 时间（A-06）
- **涉及文件**：`docs/archaeology-report.md`（新）、`config/semantic_view.yaml`（签字后）
- **验收怎么验**：证据率 ≥90%；每个冲突点变成给 Owner 的具体问题；人审单条 <2 分钟
- **收尾核对（2026-11-05）**：Owner 签字 ✅（S-01—S-08、S-09=A）；外部文档定义 ✅（脱敏存档 `docs/archaeology/s05-landing-plan.md`，原图不入库）；冲突清零率 **100%（6/6 已裁决，C-05 为整体作废、仅作教学反例，见 C-11）**；证据率 100%（阈值 ≥90%；文档原文「趋近 100%」，未改标准）；考古发现率 6 条冲突（C-01—C-06）；人审 2 分钟**未实测（用户决定不做）**；**双方签字仍缺（#30）**。
- **状态**：**有条件完成（降级；非「达标」，不标 ✅）** —— 含 2 项偏离，见下方「验收偏离记录（2026-11-05，用户授权）」。
- **版本归属**：V4.0 辅助任务，**非四项退出门禁**；剩余 2 项偏离均按用户授权处理（人审弃权、双签顺延 V4.1），遗留至 V4.1 启动时复核（见 OPEN-QUESTIONS #30）。
- **难度**：⭐⭐⭐

##### 验收偏离记录（2026-11-05，用户授权）

> 本节只追加偏离记录，**不修改上方「对应验收标准」「验收怎么验」的任何原文数字与表述**（`≥90%`、冲突清零 `100%`、人审 `单条 <2 分钟` 均保持原样）。

**偏离 1 · 人审耗时：弃权**
- **放宽了什么**：原标准要求「人审单条 <2 分钟」，本轮不做实测，本版本该项不计入通过条件。
- **相对原标准**：与「验收怎么验：…人审单条 <2 分钟」直接偏离（该项由实测判定改为弃权）。
- **授权人 / 日期**：用户（Owner）／ 2026-11-05。
- **代价**：该验收指标无实测证据支撑；报告与对外说明中只能写「按设计预期 / 未验证」，不得表述为已验证或达标。
- **回退条件**：若在 V4.1 启动前补做人审耗时实测，则该项恢复按原标准 `<2 分钟` 判定；若永不补齐，本任务完成状态视为**条件性完成**。

**偏离 2 · 双方签字：顺延 V4.1**
- **放宽了什么**：原要求「业务 + 数仓」双方签字，本轮只有 Owner（用户）单方签字；双签顺延至 V4.1，作为 V4.1 入口前置条件。
- **相对原标准**：与落地方案 §4.3 第 4 步「双方（业务 + 数仓）签字」偏离（单方签字替代双方签字）。
- **授权人 / 日期**：用户（Owner）／ 2026-11-05。
- **代价**：口径签字缺少业务与数仓侧确认，当前语义层只代表 Owner 单方意见；双签前不得宣称口径已获双方共识。
- **回退条件**：若在 V4.1 启动前补齐双方签字，则该项恢复按原标准判定；若永不补齐，本任务完成状态视为**条件性完成**。

#### T-4.0.10 · V4.0 退出评审 ✅（2026-11-05）
- **做的事情**：对照 releases V4.0 退出门禁四项逐条过；17 场景输出与 legacy 比对留档；写 V4.0 实验记录（experiments/ 首篇）。
- **对应验收标准**：releases V4.0 ✓
- **依赖**：T-4.0.1—9
- **涉及文件**：`docs/experiments/2026-xx-xx-v40-baseline.md`
- **验收怎么验**：门禁四项全过 + 用户签字（你）
- **收尾核对（2026-11-05）**：四项均有实测证据（② 见 `docs/experiments/2026-11-05-v40-equivalence.md`）；用户签字确认结版；T-4.0.4 / T-4.0.9 为辅助任务，遗留至 V4.1 重新排期；T-4.0.7 的线上红色 run 按用户决定不做（不列入待办）。
- **难度**：⭐⭐

---

## 二、V4.1 问数闭环（4 周）

#### T-4.1.1 · alias 同义词索引
- **做的事情**：`semantic/` 实现 synonyms → 标准指标名索引（FPD30/首期逾期/fpd30 → fpd30_rate）；口语归一走 alias，映射不到进慢路提名。
- **对应验收标准**：spec US-02；黄金题集路由层
- **依赖**：T-4.0.2
- **涉及文件**：`src/riskqa/semantic/alias.py`
- **验收怎么验**：单元测试覆盖全部 synonyms；路由层准确率 ≥95%（黄金题集）
- **收尾核对（2026-11-06）**：`src/riskqa/semantic/alias.py` 新建（build_alias_index / resolve_token / match_question），`layer.py` 三方法改为委托（命中行为原样保持）；`tests/unit/test_alias.py` 8 条单测覆盖全部指标名与 aliases（`make test`：59 passed / 1 xfailed，未改既有断言）。术语以 YAML 的 `aliases` 为准，不新增 YAML 字段（Q1）。路由层准确率 ≥95% 顺延 T-4.1.8 实测（runner 未建，用户授权顺延，Q2，见 OPEN-QUESTIONS #32）。
- **状态**：**有条件完成（不标 ✅）**——单元测试项达标；路由准确率项顺延未实测，不冒充达标。
- **难度**：⭐⭐

#### T-4.1.2 · 快路 ask 链路 ✅（2026-11-06）
- **做的事情**：四元组入参 + enum 收窄 + 前闸（P-04/05/08/09）+ 纯函数计算 + FactStore + 口径返回；无事实禁出报告。
- **对应验收标准**：spec §3.1 问数域；AGENTS P-06/08/09
- **依赖**：T-4.1.1
- **涉及文件**：`src/riskqa/orchestration/fast_path.py`、`src/riskqa/tools/`
- **验收怎么验**：发明指标/乱拆维度/未签字/纯函数未注册四类拒服测试 PASS；快路 P95<2s
- **收尾核对（2026-11-06）**：`src/riskqa/orchestration/fast_path.py` 新建（`AskRequest`/`AskResult` 四元组、`build_ask_metric_schema`、`parse_question`、`pre_tool_gate`、`ask_fast`）；`graph_qa.py` 的 `fast_fc` 改为委托，图结构、慢路节点与既有断言未动。`tests/unit/test_fast_path.py` 15 条：四类拒服（未登记指标含 FakeLLM 覆盖、多维度/越权维度、未签字、纯函数未注册）+ enum 语义层同源 + 解析/过滤/时间窗 + 结果契约（单值与分组）+ 无事实拒出报告 + 空 changelog 仍视为已签字 + P95 断言。P95 实测（`pytest tests/unit/test_fast_path.py -s`）：n=1000，数据 1200 行 demo，单维度 `channel` 分组，中位数 1.31ms、P95 7.40ms，阈值 2000ms；断言在 `make test`/CI 内，未降阈值、未改为只留档。`make test` 74 passed / 1 xfailed；`make lint` 61 files formatted。**行级权限不在本任务验收原文**：快路本轮不做 df 过滤（`role` 仅前闸留痕），缺口登记 OPEN-QUESTIONS #33，由 T-4.1.4 收口。
- **状态**：**✅ 达标（2026-11-06）** —— 验收原文两项（四类拒服 PASS、快路 P95<2s）均有实测证据；快路行级权限缺口见 #33，属 T-4.1.4 范围。
- **难度**：⭐⭐⭐

#### T-4.1.3 · 慢路 LangGraph 固定图
- **做的事情**：schema 链接 → SQL 生成 → 三闸 → 执行 → 修正（≤2 轮）→ 交叉验证 → 人审分级；interrupt 挂人审。
- **对应验收标准**：spec §3.1；架构 §4.2
- **依赖**：T-4.1.2
- **涉及文件**：`src/riskqa/orchestration/slow_graph.py`
- **验收怎么验**：慢路熔断 60s；修正轮数 ≤2；交叉验证不一致返回双侧数字（不平均）
- **难度**：⭐⭐⭐⭐

#### T-4.1.4 · SQL 三闸与行级权限 ✅（2026-11-06）
- **做的事情**：`check_sql`（SELECT 白名单/强制 LIMIT/注入特征）+ `inject_row_filter` 执行前注入 + 越权返回空结果。
- **对应验收标准**：AGENTS P-10；security §三/§七
- **依赖**：T-4.1.3
- **涉及文件**：`src/riskqa/tools/sql_gate.py`
- **验收怎么验**：SG-01 第 3/4 项通过；正反例进单元测试（data-model §三 两例）
- **收尾核对（2026-11-06）**：闸① 强制 SELECT/WITH 开头，PRAGMA/ATTACH/DETACH/VACUUM/EXPLAIN/REPLACE 拒；闸② 强制 LIMIT 保留；闸③ UNION、分号、行/块注释、xp_、INTO OUTFILE、LOAD_FILE 一律拒；慢路 `inject_row_filter` 不变。快路新增 `apply_row_filter`，在 `compute_metric` **之前**按 `sem.row_filter(role, 'fact_application')` 收窄 df（P-10 / data-model §三）。越权或授权范围内无数据 → `AskResult(denied=True)` 空结果 + 审计、不报错；有行但 NaN → 仍抛 `NoFactError`，两分支不合并（R14）。`merge_verify` 改为按可见数据独立重算（否则快路事实会被全量重算判 `render_mismatch`）。实测：analyst 整体 0.22391857506361323（602/1200 行）、risk_admin 全量 0.2859042553191489、analyst 分渠道 1 条 fact、越权 `channel=Z` 返回空结果不报错。`make test` 79 passed / 1 xfailed；`make lint` 61 files formatted。路径偏差：按 D1-A 落在现有 `src/riskqa/tools/gates.py`，未新建 `sql_gate.py`（tasks 原文路径保留不改为宜，此处记录实际落点）。
- **状态**：**✅ 达标（2026-11-06）** —— SG-01 #3/#4 均有实测用例；data-model §三正反例已覆盖；既有 17 场景全绿。
- **已知限制**：`inject_row_filter` 的 `table` 参数未使用、正则可被注释/子查询绕过——按 R15 本轮**不修**；生产需接 SQL AST（如 sqlglot），属后续版本，未引入新依赖。`apply_row_filter` 仅支持等值/IN + AND，其他语法显式抛 `RowFilterParseError`（fail closed）。
- **难度**：⭐⭐⭐

##### 验收相关变更记录（2026-11-06，用户授权）

- **变更断言**：`tests/scenario/test_v2_scenarios.py::test_v2_1_fast_path_returns_fact_and_passes_gates` 的冻结值，原 `0.2859042553191489` → `0.22391857506361323`。
- **为什么变**：P-10 行级权限在快路生效，`analyst_qa` 角色按 `channel='A'` 在聚合前收窄，整体值即 A 渠道值（分母同步收窄，不是应用层过滤）。
- **授权人 / 日期**：用户本人／2026-11-06。
- **性质**：这是**行为变更，不是放宽标准**——阈值、口径、其他断言均未改动；旧全量数值改由新增 `tests/unit/test_fast_path.py::test_admin_sees_full_population` 继续守护。
- **关联**：QG-02 注记（V4.0 的 17/17 等价基线不变，V4.1 场景一按 P-10 变更语义，二者不可直接对比）。


#### T-4.1.5 · REST API v1（8 端点）
- **做的事情**：FastAPI 实现 openapi.yaml 全 8 端点；token 认证 + 角色；错误码全集；只绑 127.0.0.1。
- **对应验收标准**：api-contract §七 冻结清单
- **依赖**：T-4.1.2/3/4
- **涉及文件**：`src/riskqa/api/`
- **验收怎么验**：openapi.yaml 无 ⚙️；8 端点示例全跑通；SG-01 第 1/2 项通过
- **难度**：⭐⭐⭐

#### T-4.1.6 · 校验闸中间件化与回退
- **做的事情**：三重检查（裸数字/编造引用/独立重算）实现为编排层中间件，不过即整份回退规则模板；回退率记审计。
- **对应验收标准**：AGENTS P-06/07；spec §3.2
- **依赖**：T-4.1.2
- **涉及文件**：`src/riskqa/verify/`
- **验收怎么验**：检查 2 用"长得像但不存在"的 F9999 验证（不查格式查存在）；独立重算入口与主流水线代码不共用（审查）
- **难度**：⭐⭐⭐

#### T-4.1.7 · LLM 网关与本地 provider
- **做的事情**：`llm/gateway.py`（OpenAI 兼容协议）+ 本地 provider 接线（Ollama/vLLM，endpoint 待 A-01 确认）+ ModelRouter + DegradedLLM；FakeLLM 保留作测试替身。
- **对应验收标准**：ADR-0004；AGENTS P-02
- **依赖**：T-4.1.3；外部：内网 LLM endpoint（OPEN-QUESTIONS #1）
- **涉及文件**：`src/riskqa/llm/`
- **验收怎么验**：health 的 llm_gateway 三态可观测；kill 本地模型后问数自动降级不中断；云端 provider 无 ADR 时被拒
- **难度**：⭐⭐⭐

#### T-4.1.8 · 黄金题集与 eval runner
- **做的事情**：冻结 20 题（evals/golden_set.yaml：10 正常 + 6 对抗口径 + 4 拒答）；runner 比结果集不比 SQL；指标分层报表。
- **对应验收标准**：spec §3.2（黄金题集≥95%）；eval.md
- **依赖**：T-4.1.2/3
- **涉及文件**：`evals/golden_set.yaml`、`src/riskqa/orchestration/eval_runner.py`
- **验收怎么验**：`make eval` 跑出分层报表；通过率 ≥95%；拒答类 100%（两类结果无容差）
- **难度**：⭐⭐⭐

#### T-4.1.9 · 安全测试与 V4.1 退出评审
- **做的事情**：SG-01 八项全跑；性能采样（快路 P95）；API 契约冻结核对；写实验记录。
- **对应验收标准**：security §七；spec §3.4/§3.5
- **依赖**：T-4.1.1—8
- **涉及文件**：`docs/experiments/`
- **验收怎么验**：八项全过 + 越权 0 通过 + P95<2s + 你签字
- **难度**：⭐⭐

---

## 三、V4.2 持续运营 + MCP 化（4 周）

#### T-4.2.1 · raw log 落库与意图抽取生产版
- **做的事情**：慢路执行后无条件落 query_log（含 sql_edited/confirmed_by）；RuleExtractor 换 LLM 抽取器（接口不变，SQL 锚点）。
- **对应验收标准**：AGENTS P-12；V3 §03/§04
- **依赖**：T-4.1.3/4.0.3
- **涉及文件**：`src/riskqa/governance/extractor.py`
- **验收怎么验**：200 条构造 log 抽取 → 6 签名（压缩比 33× 量级复现）；filters 只记字段不记值
- **难度**：⭐⭐⭐

#### T-4.2.2 · 签名归并与热度三维度
- **做的事情**：normalize_sql（字面值→?）+ cluster_logs + heat（n_users/n_days/top_user_share/concentrated/edited_ratio）+ nominate。
- **对应验收标准**：V3 §06 四类失真拦截
- **依赖**：T-4.2.1
- **涉及文件**：`src/riskqa/governance/cluster.py`
- **验收怎么验**：单人 83% 集群被拦、会议 12 次压 2 天被拦、92 参数变体聚成 1 签名
- **难度**：⭐⭐⭐

#### T-4.2.3 · 口径指纹两级检测
- **做的事情**：caliber_fingerprint（聚合+WHERE，字面值归一）+ 签名内检测 + **跨签名（同 metric）检测** + 冲突清单。
- **对应验收标准**：V3 §07：精确检出 + 零误报
- **依赖**：T-4.2.2
- **涉及文件**：`src/riskqa/governance/conflict.py`
- **验收怎么验**：fpd30 两口径（WHERE is_pass=1 vs 无）精确检出；pass_rate/loan_amt 维度差异无误报（V3 两个开发期 bug 的回归测试）
- **难度**：⭐⭐⭐⭐

#### T-4.2.4 · 评审材料与 Owner 签字流
- **做的事情**：build_review_material（按签名分组、只标异类、证据链 QID 可点开）+ review_record 状态机 + decision API（approve 同事务三件事，P-13）。
- **对应验收标准**：V3 §08/§09；spec US-03
- **依赖**：T-4.2.3
- **涉及文件**：`src/riskqa/governance/material.py`
- **验收怎么验**：材料生成 <10s；Owner 侧单条评审 <10 分钟（试运行）；approve 任一步失败整体回滚（构造故障验证）
- **难度**：⭐⭐⭐⭐

#### T-4.2.5 · 晋升三件套与 alias 回填
- **做的事情**：promote（YAML + evidence 快照 + aliases 回填 + calc_registered 硬纪律）；快路对 calc_registered=0 拒服。
- **对应验收标准**：AGENTS P-09/P-13；V3 §09.3
- **依赖**：T-4.2.4
- **涉及文件**：`src/riskqa/governance/promote.py`
- **验收怎么验**：复现 V3 场景六——未注册纯函数时快路拒服，注册后算出 596.0；历史问法全部命中快路
- **难度**：⭐⭐⭐

#### T-4.2.6 · MCP Server 5 工具
- **做的事情**：ask_metric/explore/submit_review/get_evidence/list_governance；stdio + SSE；工具 schema 从 openapi components 生成；Trae 与 Chat2DB 实调联调。
- **对应验收标准**：ADR-0005；spec US-07
- **依赖**：T-4.1.5（API 冻结）
- **涉及文件**：`src/riskqa/mcp/`
- **验收怎么验**：Trae 里自然语言问数成功；外壳传错身份被工具内权限注入拒绝；Chat2DB 连上
- **难度**：⭐⭐⭐⭐

#### T-4.2.7 · 升级链与 IM 告警
- **做的事情**：tick 状态机（pending→reminded 72h→overdue 144h→shelved 504h）+ 告警落 alert 表 + 企微/飞书 webhook（A-04）；队列健康指标报表。
- **对应验收标准**：V3 §10；spec US-05
- **依赖**：T-4.2.4；外部：webhook（OPEN-QUESTIONS #3）
- **涉及文件**：`src/riskqa/governance/escalation.py`
- **验收怎么验**：V3 场景七状态机全转换；一条告警从发送到认领闭环；shelved≠rejected 分开可查
- **难度**：⭐⭐⭐

#### T-4.2.8 · 治理配置护栏与 V4.2 退出评审
- **做的事情**：三层配置加载 + 四条护栏（失败保持旧配置）+ 200 条 log 端到端 + 误晋升率 0 验证（构造 3 陷阱集群）。
- **对应验收标准**：releases V4.2 ✓；AGENTS P-14
- **依赖**：T-4.2.1—7
- **涉及文件**：`src/riskqa/governance/config.py`
- **验收怎么验**：window=400>retention=365 被护栏拒绝且旧配置仍生效；端到端断言全绿 + 你签字
- **难度**：⭐⭐⭐

---

## 四、V4.3 全场景 + 运维（4—6 周）

#### T-4.3.1 · 报告场景 spec 与 renderer 注册表
- **做的事情**：spec YAML → renderer 注册表逐 sheet 渲染；未注册 module 抛错（P-18）；FactStore 供数。
- **对应验收标准**：spec US-04；AGENTS P-18
- **依赖**：T-4.1.6
- **涉及文件**：`src/riskqa/orchestration/report/`
- **验收怎么验**：加一个 sheet 不注册 → 明确报错（非静默跳过）；10 指标报告 <5min
- **难度**：⭐⭐⭐

#### T-4.3.2 · 叙事层与三重闸交付
- **做的事情**：叙事生成（LLM 只写叙事引用 fid）→ 三重闸 → 不过整份回退模板 → 交付带 data_as_of + AI 显著标识（P-16）。
- **对应验收标准**：AGENTS P-06/07/16；spec §3.1
- **依赖**：T-4.3.1
- **涉及文件**：`src/riskqa/orchestration/report/narrative.py`
- **验收怎么验**：8 类失败场景全 PASS；回退率记入审计可查
- **难度**：⭐⭐⭐

#### T-4.3.3 · 监控归因场景
- **做的事情**：规则检测（阈值可配）+ 维度下钻（归因假设探索）+ 告警 + "待人工确认"状态纪律（P-11）。
- **对应验收标准**：spec US-05；落地方案 §7.4
- **依赖**：T-4.2.7
- **涉及文件**：`src/riskqa/orchestration/monitor/`
- **验收怎么验**：超阈值告警自动发、归因结论状态永远"待人工确认"；归因收敛率开始建基线
- **难度**：⭐⭐⭐⭐

#### T-4.3.4 · 回测场景
- **做的事情**：多策略对比 + 回测口径与生产可复现比对（同签名同快照重算）；候选清单输出。
- **对应验收标准**：spec §3.1 回测域；releases V4.3 ④
- **依赖**：T-4.3.1
- **涉及文件**：`src/riskqa/orchestration/backtest/`
- **验收怎么验**：回测数字与生产口径复现比对通过（差异须能解释）
- **难度**：⭐⭐⭐⭐

#### T-4.3.5 · 评测扩容与归因体系
- **做的事情**：黄金集 20→50（含 20 对抗口径题，如"未放款户算不算分母"）；attribution.md 落地；judge-prompt 用于叙事类且 10% 人工校准。
- **对应验收标准**：spec §3.2；eval.md §4
- **依赖**：T-4.1.8
- **涉及文件**：`evals/*`
- **验收怎么验**：50 题通过率 ≥95%；judge 与人工分歧 <20%
- **难度**：⭐⭐⭐

#### T-4.3.6 · 运维实战校准
- **做的事情**：ops-runbook 每条告警一次真实演练；备份恢复演练一次；首篇实验记录（experiments/）。
- **对应验收标准**：releases V4.3 ⑤
- **依赖**：T-4.2.7
- **涉及文件**：`docs/ops-runbook.md`、`docs/experiments/`
- **验收怎么验**：演练记录留档（含"谁被叫醒、能不能处理"）
- **难度**：⭐⭐

#### T-4.3.7 · （可选）deepagents 归因探针 PoC
- **做的事情**：子 agent 并行探针（渠道/产品/时间各一，独立权限 MCP 客户端）验证收益；产出结论：进生产或放弃。
- **对应验收标准**：ADR-0002 复核条件
- **依赖**：T-4.2.6
- **涉及文件**：`experiments/` 或放弃（记 ADR 复核）
- **验收怎么验**：PoC 报告 + 明确决策记录
- **难度**：⭐⭐⭐⭐

---

## 五、验收难度统计

| 难度 | 任务数 | 任务 |
|---|---|---|
| ⭐ | 2 | T-4.0.5、T-4.0.8 |
| ⭐⭐ | 8 | T-4.0.2/4/9/10、T-4.1.1/9、T-4.2.7/8、T-4.3.2/6 |
| ⭐⭐⭐ | 15 | 见各任务标注 |
| ⭐⭐⭐⭐ | 6 | T-4.1.3、T-4.2.3/4/6、T-4.3.3/4/7 |

> 四星任务全部集中在"校验与治理的正确性"——这正是本项目宁可慢、不可错的地方。

## 六、顺序风险提示（动工前读一遍）

1. **T-4.0.9（口径考古）是最容易低估的**：它依赖 Owner 时间，且产出可能颠覆你对团队口径一致性的认知——排期时给它单独 buffer，不要和开发任务抢同一周。
2. **T-4.1.3（慢路图）是 V4.1 的关键路径**：API（T-4.1.5）与评测（T-4.1.8）都等它；LLM endpoint（OPEN-QUESTIONS #1）不确认也要先按默认开发，联调前替换。
3. **T-4.2.6（MCP）不要提前**：它依赖 API 契约冻结（T-4.1.5）；提前做会两边返工。
4. **T-4.2.3（口径指纹）有已知回归风险**：V3 开发期两个 bug（参数当口径、跨签名漏检）的测试必须一起迁入——修过的洞会再开。
5. **每个版本的最后一个任务都是"退出评审 + 实验记录"**：不许省——它是下一次返工的唯一参照。

## 七、并行轨道（C0 声明）

协作档 C0（单人+AI）：**无并行轨道**。唯一可自我并行的是 T-4.0.5/4.0.8（无依赖）可与 T-4.0.1 同时推进。

## 八、进度与预估

| 版本 | 任务数 | 预估人天 | 状态 |
|---|---|---|---|
| V4.0 | 10 | 20 | ⬜ 未开始 |
| V4.1 | 9 | 20 | ⬜ |
| V4.2 | 8 | 20 | ⬜ |
| V4.3 | 7 | 24 | ⬜ |
| **合计** | **34** | **84** | 约 4—5 个月（含评审缓冲） |
