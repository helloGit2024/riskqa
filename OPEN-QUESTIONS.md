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
| 9 | 内网 pip 源是否可用？ | assumptions A-07 | 按公司内网源写 requirements；装不上先 vendor 到 `third_party/` | 运维 |
| 10 | 回测场景的 OOT 数据从哪来？ | releases V4.3 | V4.0—V4.2 不依赖；V4.3 启动时确认 | 模型团队 |
| 12 | `normalize_missing` 两版实现不同：金融版按列替换 `{"": NaN, "unknown": NaN, "Unknown": NaN}` 并全表替换 `-999`；V2 为 `df.replace(["", "unknown", -999], np.nan)`。金融版处理 `"Unknown"` 但不处理 pandas string 空串，V2 反之。B2 迁移取金融版，故在 pandas string dtype 下空串行为与 V2 原版不同 | legacy 金融版 / V2 的 `normalize_missing`；B2 迁移后的 `src/riskqa/data/snapshot.py` | 保留金融版（行为等价迁移，未修）；默认路径：T-4.0.6 写测试固化预期（`"Unknown"` 归一、`"unknown"` 归一、pandas string 空串按所选版本行为断言）；来源：B2 行为等价迁移时发现 | 你 |
| 13 | 金融版 `dispatch` 与 V2 选型的计算/事实层接口不匹配：非分组同一输入旧值 `0.4`（金融版 `CALC` 对 `y` 求均值）vs 新值 `0.3333`（V2 `fpd30_rate` 按 `is_pass/is_fpd30`）；分组路径在本机 pandas 2.0.3 触发 `include_groups` TypeError，升到 pandas ≥2.2 后仍会因 V2 `compute_metric` 无 `dim` 列与 `FactStore.put` 第 4 位置参映射到 `segment` 报错，影响快路分维度查询（`tools/dispatch.py` 已按原样迁移，未适配） | legacy 金融版 `dispatch` / V2 的 `compute_metric`、`FactStore`；B3 迁移后的 `src/riskqa/tools/dispatch.py` | 原样保留（行为等价迁移，未修）；默认路径：T-4.0.6 写测试固化预期，或在 T-4.0.2 统一计算/事实层接口时一并处理；来源：B3 行为等价迁移时发现 | 你 |
| 14 | `config/governance.yaml` 的 `overrides`（主题域覆盖层）会被 `load_governance` 丢弃：`GovernanceConfig.for_domain(domain, overrides)` 需要调用方另行传入 overrides，而非从配置对象读取 | `config/governance.yaml` 的 `overrides`；`src/riskqa/governance/config.py` | 保留数据层但不消费（外置原样迁移）；默认路径：V4.2 治理三层接入时把 overrides 挂到 `GovernanceConfig` 或改由加载器返回；来源：T-4.0.2 | 你 |
| 15 | 分组问数中某组算出 NaN 时，是否应让整条问数失败？真实场景：① 新渠道当月只有申请、未放款（`is_pass==1` 为空）→ 该组 `fpd30_rate=NaN`；② 小客群只有单一 `y`（全好人或全坏账）→ 该组 `ks/auc=NaN`。T-4.0.3 只在 store 层拒收 NaN，未改编排层，因此当前会让整条问数失败 | `calc/metrics.py` 的四个显式 NaN 分支；`tools/dispatch.py`、`orchestration/graph_qa.py` 的 `facts.put` 调用点；T-4.0.3 的 `store/facts.py` | 保留 store 层拒收（数字纪律优先）；默认路径：T-4.0.6 写测试固化"整组缺失 vs 整问失败"的预期，再决定是否改为 NULL/原因码；来源：T-4.0.3 决策点 2 复核 | 你 |
| 16 | "假数字"：空表 `psi` 返回 `0.0`、`score` 全缺失时 `ks=1.0`/`auc=0.0`——不抛错也不返回 NaN，比 NaN 更难发现 | `calc/metrics.py` 的 `psi/ks/auc` 实现（legacy V2 同源） | 保留 legacy 行为不修（V4.0 明确不改计算逻辑）；默认路径：T-4.0.6 固化边界测试，并在 store 层之外增加样本量/有效值告警；来源：T-4.0.3 决策点 2 复核（实测 pandas 2.0.3） | 你 |
| 17 | `Fact.data_as_of` 在内存版 `Fact` 中存在，但 `docs/data-model.md` §2.2 的 `fact` 表没有该列；T-4.0.3 按文档不落库，由 `SqliteFactStore` 构造器/manifest 提供 | `src/riskqa/facts/store.py`；`src/riskqa/store/facts.py`；`docs/data-model.md` §2.2 | 不落库（以文档为准，避免自创列）；默认路径：T-4.0.4 manifest 实战时确认 data_as_of 的最终归属，再决定是否补列/走 manifest；来源：T-4.0.3 | 你 |

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

---

<!-- AUTO-COLLECT:BEGIN -->
### 🤖 自动汇总（2026-11-04 · 共 0 处）

扫描根目录：`/Users/tj/WorkBuddy/2026-10-10-16-24-17/风控问数系统`

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
