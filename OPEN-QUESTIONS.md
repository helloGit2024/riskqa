# OPEN-QUESTIONS.md · 待确认项清单

> **所有文档里的 `⚙️ 待你确认` 都在这里收敛。** 不要散落在各处。

---

## 一、阻塞项（不定下来就没法开工）

| # | 问题 | 出现在 | 我建议 | 该问谁 | 状态 |
|---|---|---|---|---|---|
| 1 | 内网本地 LLM 的 endpoint 与可用模型名是什么？ | assumptions A-01；architecture LLM 网关 | 先按 Ollama 默认 `http://localhost:11434/v1` + qwen2.5 系列写着，V4.1 联调前换成真实值；**阻塞的只是 T-4.1.7，不是 V4.0** | 运维/你 | ⬜ 未决 |
| 2 | 首份真实指标宽表从哪个数仓表导出？字段名与 demo 的 `fact_application` 是否一致？ | assumptions A-02/A-05 | V4.0 先用 demo 结构开发；T-4.0.9 口径考古时替换 | 数仓 | ⬜ 未决 |

> **实测经验**：十来个待确认项里，真正阻塞的通常只有 2—3 个。上面两条都有"先开发后替换"的默认路径，V4.0 可立即开工。

---

## 二、非阻塞项（有保守默认值，可以先开工）

> 处理原则：**每一条不确定，都往"少答、标注、拒答"倒。**

| # | 问题 | 出现在 | 当前默认值（安全侧） | 该问谁 |
|---|---|---|---|---|
| 3 | 企微/飞书 webhook 是否可用？ | assumptions A-04 | 先走日志+邮件；V4.2 联调时再开 IM | IT |
| 4 | Owner 每周评审时间是否 ≥30 分钟？ | assumptions A-06 | 按 3 位 Owner、每周五评审会排期；队列积压超 2 周触发加急通道规则复盘 | 风控负责人 |
| 5 | raw log 日增量量级？ | assumptions A-08 | 按 <1 万条/日设计；SQLite 单表，超预期加月度归档 | （上线后实测） |
| 6 | "贷中风险"主题域名与指标集是否就是 demo 的 5 个？ | assumptions A-05 | 先用 demo 5 指标；首次考古后按真实清单替换（结构不变） | 你 |
| 7 | 抽检比例定多少？ | spec §5.3 | 默认 10%（V2 实测口径），跑一个月后按误报率调 | 你 |
| 8 | 加急通道的具体触发条件？ | V3 文档 §10.1 | 默认"≥5 独立用户或管理层问过"；首次复盘会校准 | 你 |
| 9 | 内网 pip 源是否可用？ | assumptions A-07 | 本机实测：pypi.org 10s 超时，清华镜像（`pip config` 已指向）可用；公司内网源仍待运维确认。装不上先 vendor 到 `third_party/` | 运维 |
| 10 | 回测场景的 OOT 数据从哪来？ | releases V4.3 | V4.0—V4.2 不依赖；V4.3 启动时确认 | 模型团队 |
| 12 | `normalize_missing` 两版实现不同：金融版按列替换 `{"": NaN, "unknown": NaN, "Unknown": NaN}` 并全表替换 `-999`；V2 为 `df.replace(["", "unknown", -999], np.nan)`。金融版处理 `"Unknown"` 但不处理 pandas string 空串，V2 反之。B2 迁移取金融版，故在 pandas string dtype 下空串行为与 V2 原版不同 | legacy 金融版 / V2 的 `normalize_missing`；B2 迁移后的 `src/riskqa/data/snapshot.py` | 保留金融版（行为等价迁移，未修）；默认路径：T-4.0.6 写测试固化预期（`"Unknown"` 归一、`"unknown"` 归一、pandas string 空串按所选版本行为断言）；来源：B2 行为等价迁移时发现 | 你 |
| 13 | 金融版 `dispatch` 与 V2 选型的计算/事实层接口不匹配：非分组同一输入旧值 `0.4`（金融版 `CALC` 对 `y` 求均值）vs 新值 `0.3333`（V2 `fpd30_rate` 按 `is_pass/is_fpd30`）；分组路径在本机 pandas 2.0.3 触发 `include_groups` TypeError，升到 pandas ≥2.2 后仍会因 V2 `compute_metric` 无 `dim` 列与 `FactStore.put` 第 4 位置参映射到 `segment` 报错，影响快路分维度查询（`tools/dispatch.py` 已按原样迁移，未适配） | legacy 金融版 `dispatch` / V2 的 `compute_metric`、`FactStore`；B3 迁移后的 `src/riskqa/tools/dispatch.py` | 原样保留（行为等价迁移，未修）；默认路径：T-4.0.6 写测试固化预期，或在 T-4.0.2 统一计算/事实层接口时一并处理；来源：B3 行为等价迁移时发现 | 你 |
| 14 | `config/governance.yaml` 的 `overrides`（主题域覆盖层）会被 `load_governance` 丢弃：`GovernanceConfig.for_domain(domain, overrides)` 需要调用方另行传入 overrides，而非从配置对象读取 | `config/governance.yaml` 的 `overrides`；`src/riskqa/governance/config.py` | 保留数据层但不消费（外置原样迁移）；默认路径：V4.2 治理三层接入时把 overrides 挂到 `GovernanceConfig` 或改由加载器返回；来源：T-4.0.2 | 你 |
| 15 | 分组问数中某组算出 NaN 时，是否应让整条问数失败？真实场景：① 新渠道当月只有申请、未放款（`is_pass==1` 为空）→ 该组 `fpd30_rate=NaN`；② 小客群只有单一 `y`（全好人或全坏账）→ 该组 `ks/auc=NaN`。T-4.0.3 只在 store 层拒收 NaN，未改编排层，因此当前会让整条问数失败 | `calc/metrics.py` 的四个显式 NaN 分支；`tools/dispatch.py`、`orchestration/graph_qa.py` 的 `facts.put` 调用点；T-4.0.3 的 `store/facts.py` | 保留 store 层拒收（数字纪律优先）；默认路径：T-4.0.6 写测试固化"整组缺失 vs 整问失败"的预期，再决定是否改为 NULL/原因码；来源：T-4.0.3 决策点 2 复核 | 你 |
| 16 | "假数字"：空表 `psi` 返回 `0.0`、`score` 全缺失时 `ks=1.0`/`auc=0.0`——不抛错也不返回 NaN，比 NaN 更难发现 | `calc/metrics.py` 的 `psi/ks/auc` 实现（legacy V2 同源） | 保留 legacy 行为不修（V4.0 明确不改计算逻辑）；默认路径：T-4.0.6 固化边界测试，并在 store 层之外增加样本量/有效值告警；来源：T-4.0.3 决策点 2 复核（实测 pandas 2.0.3） | 你 |
| 17 | `Fact.data_as_of` 在内存版 `Fact` 中存在，但 `docs/data-model.md` §2.2 的 `fact` 表没有该列；T-4.0.3 按文档不落库，由 `SqliteFactStore` 构造器/manifest 提供 | `src/riskqa/facts/store.py`；`src/riskqa/store/facts.py`；`docs/data-model.md` §2.2 | 不落库（以文档为准，避免自创列）；默认路径：T-4.0.4 manifest 实战时确认 data_as_of 的最终归属，再决定是否补列/走 manifest；来源：T-4.0.3 | 你 |
| 18 | Parquet 快照未实现：本机 `pyarrow`/`fastparquet` 均未安装，`write_snapshot(fmt="parquet")` 与 `load_snapshot_file` 遇到 parquet 会抛 `ParquetEngineMissingError`。C-2 已确认格式为 CSV/Parquet，但 V4.0 本批只交付 CSV | `src/riskqa/data/snapshot.py`；`docs/constraints.md` §三（单文件 ≤500MB、100 万—500 万行） | T-4.0.5 已定：`requirements.txt` 不含 pyarrow（R16 未批准），Parquet 继续显式抛错；待 V4.1 前评估；来源：T-4.0.4 → T-4.0.5 | 运维/你 |
| 20 | GitHub 仓库是否允许保持公开？公开仓库的 Actions 日志与门禁输出是否可对外可见？ | `.github/workflows/ci.yml`；T-4.0.7 A 方案 | 不擅自变更远端可见性；CI 只运行 demo 合成数据、测试与文档校验，确认前不接真实指标、raw log 或密钥；若日志不允许公开，应先转私有仓库再使用 Actions | 你 |
| 21 | `Makefile` 的 `eval` target 守卫失效：守卫只检查 `tests/` 是否存在（该目录一直存在），实际执行会因 `riskqa.orchestration.eval_runner` 不存在抛 `ModuleNotFoundError` | `Makefile` 的 `eval` target；T-4.1.8 | 保持现状不修（V4.0 不做评估 runner）；T-4.1.8 建 runner 时改为检查模块文件是否存在，并补 `PYTHONPATH=src`；来源：T-4.0.7 评估现状分析 | 你 |
| 22 | `evals/seed.sql` 实为 SQLite 3 二进制库（非文本 SQL，122880 字节），且无 sha256 指纹，评估结果不可复现与留档 | `evals/seed.sql`；`evals/golden_set.yaml` 的 `meta.seed_file` | 暂按现有二进制库使用，不在 V4.0 改格式；T-4.1.8 在评估结果中记录 seed 的 sha256，必要时改为文本 dump + manifest；来源：T-4.0.7 评估现状分析 | 你 |
| 26 | V3 迁移后「未登记指标」的异常类型由 `ValueError` 变为 `UnregisteredMetricError`（后者不是 `ValueError` 子类），沿用 `except ValueError` 的调用方不再捕获；拒算结论本身未变 | `legacy/问数Agent_持续运营V3.py`；`src/riskqa/semantic/layer.py`；`src/riskqa/calc/metrics.py`；`docs/experiments/2026-11-05-v40-equivalence.md` V3-6 | 保留 `UnregisteredMetricError`（P-04 要求显式拒服）；V4.1 起统一按新类型捕获；若需兼容旧调用方，先确认再改 | 你 |
| 27 | `fpd30_rate` 的 `desc` 文案在 legacy V2 与 `config/semantic_view.yaml` 中不同（后者多「（分母=放款户，宽限期 3 天）」16 字符），使慢路 prompt 变长、估算 token 成本 5394→5498（+1.9%）；指标数值与判定均未变 | `config/semantic_view.yaml`；`legacy/问数Agent_企业版V2.py`；`docs/experiments/2026-11-05-v40-equivalence.md` §五-2 | 口径描述以 config 为准（信息更完整），成本差异仅为估算值；若要求与 legacy 字面一致，请确认后改 desc | 你 |
| 28 | 默认取数范围（近 30 天 / A 产品）尚未在 config 建模：`semantic_view.yaml` 无字段承载「时间窗 + 产品 + 渠道」的默认取数约定 | `config/semantic_view.yaml`；`docs/archaeology-report.md` 第六节 | 不写进 config，以免引入无消费方的字段；V4.1 决定由调用方传参还是新增字段（需先有慢路/快路消费方）；来源：T-4.0.9 签字 | 你 |
| 29 | `psi` 原描述「期望 vs 实际」与实现不一致；已按 S-09=A 修正描述，实现仍为好坏样本（`y==1` vs `y==0`）分数分布差 | `config/semantic_view.yaml` `psi`；`src/riskqa/calc/metrics.py` L45-52 | 当前只改描述、不改计算，数值未变；若将来要做真正的期望/实际 PSI，属计算逻辑变更，需按 P-03 另走签字并重跑冻结值 | 你 |
| 30 | 口径签字只有 Owner（用户）一方，缺落地方案 §4.3 第 4 步要求的「双方（业务 + 数仓）签字」 | `docs/archaeology/s05-landing-plan.md`；`config/semantic_view.yaml`；`docs/archaeology-report.md` 第六节、7.3 | **顺延 V4.1（2026-11-05 用户决定）**：缺**业务侧与数仓侧**两方签字（当前仅 Owner 单方）；顺延至 V4.1，作为 V4.1 **入口前置条件**；**V4.1 启动时先查本条**并复核是否补齐双签。2026-11-06 V4.1 启动：用户确认双签仍未补齐，按现有记录开工（方案 A），本条继续挂起 | 你（业务 + 数仓） |
| 32 | T-4.1.1 两项处理口径：① 任务书写 `synonyms`，YAML/nl2sql-core 实际字段为 `aliases`，以哪个为准？② 验收「路由层准确率 ≥95%（黄金题集）」在 runner（T-4.1.8）建成前无法实测 | `docs/tasks.md` T-4.1.1；`.trae/rules/nl2sql-core.md`；`config/semantic_view.yaml` | 2026-11-06 用户决定：① 以 YAML 的 `aliases` 为准，`synonyms` 只当概念名，不新增 YAML 字段；② 本任务只交付单元测试，路由准确率顺延 T-4.1.8 实测（Q019 手机号题 `route: fast` 但不命中指标，届时需定义该题在路由层的计分口径）。T-4.1.8 启动时先查本条 | 你 |
| 34 | 快路 `parse_question` 能解析 `time_range`（如 `2026-07`），但 `ask_fast` 计算与校验闸重算都不应用时间窗；`AskResult.scope` 只回传不使用，结果与不带时间窗相同 | `src/riskqa/orchestration/fast_path.py`；`src/riskqa/verify/middleware.py`；T-4.1.6 | 本轮不实现（不扩大 T-4.1.6 范围）：`time_range` 原样回传、不参与 df 收窄；默认路径：T-4.1.5 API 落地前决定是补数据层时间过滤还是从问数链路摘掉该参数；来源：T-4.1.6 执行 | 你 |


---

## 三、已关闭（访谈中已确认，留档）

| # | 问题 | 结论 | 确认日期 |
|---|---|---|---|
| C-1 | 系统边界到哪？ | 无自研前端（引擎+API+MCP+CLI） | 2026-11-01 |
| C-2 | 数据与持久化？ | 文件快照（CSV/Parquet）+ SQLite | 2026-11-01 |
| C-3 | LLM 怎么接？ | 统一网关，本地模型优先，数据不出内网 | 2026-11-01 |
| C-4 | 协作档？ | C0（一个人 + AI 提交） | 2026-11-01 |
| C-5 | 归因/回测是否沉淀 SQL 为语义层指标？ | 否（V3 已确认边界：只做指标问数运营化） | 2026-11-01 |
| C-6 | （原 #11）`row_policies` 扁平字符串导致 `row_filter(role, table)` 抛 `AttributeError`，行级权限不可用 | 随 T-4.0.2 外置 YAML 时规范为 `{role: {table: 条件}}` 两层结构；`semantic-check` 增加结构断言，扁平常量会被拒绝 | 2026-11-04 |
| C-7 | （原 #19）本机 Python 环境版本与早前记录不一致：曾实测 pandas 3.1.0 / numpy 2.5.4，早前迁移记录为 pandas 2.0.3 | T-4.0.5 锁定 `pandas==2.2.3 / numpy==2.2.6`（Python 3.13.12），重建 `.venv` 后快照往返重验通过；`normalize_missing` 保留 `StringDtype` 分支（2.2.3 下不触发）。注意 `hash_pandas_object` 跨大版本不保证一致，已有快照换环境需重跑往返 | 2026-11-04 |
| C-8 | （原 #25）`docs/tasks.md` 与 `docs/releases.md` 对 T-4.0.4 / T-4.0.7 / T-4.0.9 的描述口径不一致 | 已对齐：T-4.0.4 / T-4.0.9 在 tasks 标注为「V4.0 辅助任务、非四项退出门禁」，releases 结版记录同步限定；T-4.0.7 的 CI 载体在 tasks 写明实际为 GitHub Actions，线上红色 run 按用户决定不做、不列入待办。**未改任何验收标准、未改 V4.1/V4.2/V4.3 范围** | 2026-11-05 |
| C-9 | （原 #23）`config/semantic_view.yaml` 的 `fact_application` 只声明 8 列，缺 `y / score_v2 / score_v3`；KS/AUC/PSI 的纯函数依赖 `y`，慢路白名单会拒掉合法 SQL | 已随 S-03 / S-04 签字补列：`columns` 追加 `score_v2, score_v3, y`（原有 8 列与顺序不变）；仅改列清单，未改 `calc/dims`，未改任何数值 | 2026-11-05 |
| C-10 | （原 #24 的定义缺失部分）验收引用的「落地方案 §4.3」不在仓库，四指标精确含义无法核对 | 原文已脱敏存档至 `docs/archaeology/s05-landing-plan.md`（含四指标原文定义与两张截图指纹，原图不入库）；**未整条关闭**：原文要求「双方（业务 + 数仓）签字」，本项目仅 Owner 一方签字，另立 #30 跟踪 | 2026-11-05 |
| C-11 | （原 #31）冲突 C-05 仅「部分裁决」，冲突清零率 5/6=83.3% 未达 100% | 已裁决为**整体作废、仅作教学反例**：V1 的 `avg_score`、金融版其余候选口径一律记为「已作废、不登记进语义层、不参与问数」，只保留作为 Q011 一类反例教学的参照。依据：S-01 已作废金融版 fpd30 分母口径 + AGENTS.md P-04「未登记指标一律拒绝」；属文档层面记录，未改 `config/`、`calc/` 或任何数值。冲突清零率 6/6=100%（仅文档裁决层面，不代表 #30 双方签字与人审实测已完成）<br>**Owner 表态摘要（2026-11-05）**：主体 Owner（用户本人），日期 2026-11-05，渠道本会话确认（选 A）；作废范围 = V1 `avg_score` + 金融版其余候选口径，不登记进语义层、不参与问数、不进入正式报告数字；升格门槛 = 须先推翻本表态，并走 P-05 签字 + P-13 晋升流程，不得直接登记。**本摘要为书面化改写，非逐字引述；逐字原话未留存。** | 2026-11-05 |
| C-12 | （原 #33）快路 `ask_fast` 不做行级权限过滤（P-10）：`role` 仅用于前闸留痕，`filters` 只做等值过滤，未调用 `semantic.row_filter(role, table)`。现象：analyst_qa 角色问 FPD30 返回全量 1200 行的 0.285904，而按 `channel='A'` 的授权条件应只返回 0.223919 | 已随 T-4.1.4 收口：`ask_fast` 在 `compute_metric` **之前**调用 `apply_row_filter(df, sem.row_filter(role, 'fact_application'))`（P-10 / data-model §三）；越权或授权范围内无数据返回 `denied=True` 空结果 + 审计、不报错；NaN 仍抛 `NoFactError`。实测 analyst 整体 = 0.22391857506361323（602/1200 行），risk_admin 全量 = 0.2859042553191489，analyst 分渠道 1 条 fact。**临时约束「不得对 analyst 开放快路整体问数」随之解除**（当前仍无 API 出口）。场景一冻结值按授权变更，见 tasks.md T-4.1.4「验收相关变更记录」 | 2026-11-06 |

---

<!-- AUTO-COLLECT:BEGIN -->
### 🤖 自动汇总（2026-11-06 · 共 0 处）

扫描根目录：`/Users/tj/Documents/trae_projects/风控问数系统`

> **先说结论**：十来个待确认项里，真正阻塞的通常只有两三个。
> 把阻塞项挑出来后可以立刻开工，其余给保守默认值即可 ——
> 保守默认值本身就是安全的那一侧，不需要任何人签字。

#### 一、可能阻塞（0 处）

_没有扫描到带阻塞线索的条目。请人工复核下面的非阻塞清单。_

#### 二、非阻塞（0 处，可先给保守默认值开工）

_无_

> ⚠️ 这是**机械汇总**，只按关键词猜测「阻塞 / 非阻塞」，**必须人工过一遍**。
> 处理完后，把结论填到上面第一节 / 第二节的表里，并删掉这里的对应行。
<!-- AUTO-COLLECT:END -->
