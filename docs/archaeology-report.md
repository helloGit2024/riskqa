# 口径考古报告（archaeology-report.md）

> **T-4.0.9 产出物。这是一份「问题清单」，不是语义层 YAML。**
> 本报告只并列冲突、不裁决口径；任何实质差异都必须由 Owner 签字后才可进 `config/semantic_view.yaml`（AGENTS.md P-05/P-13、P-15）。
> 生成日期：2026-11-05 ｜ 证据环境：`.venv`（Python 3.13.12 + pandas 2.2.3）｜ 数据：`evals/seed.sql`（1200 行）

## 〇、结论摘要

1. **5 个指标的签字口径（config）与 legacy V2 一致**，数值全部可复现；V3 只登记了其中 2 个。
2. **fpd30 存在三种算法**：放款户口径（0.285904，config/V2/V3）、全量口径（0.179167，题库禁列值）、`y` 均值口径（0.175，金融版）。**金融版是历史错误口径**，只存档不入库。
3. **`y` 与 `is_fpd30` 是两个不同标签**（0.175 vs 0.179167）。KS/AUC/PSI 读 `y`，FPD30 读 `is_fpd30`；混用会让 Q005 从 0.254183 变成 0.059781。
4. **语义层漏登记 3 列**（`y / score_v2 / score_v3`），慢路白名单会拒掉合法 SQL。
5. **行权限范围有候选冲突**：config 只给 `analyst_qa` 开放 A 渠道，V3 是 A/B/C；本报告只提出问题，不放开。

---

## 一、扫描范围与文件清单

| 文件 | 行号范围 | 用途 |
|---|---|---|
| [config/semantic_view.yaml](file:///Users/tj/Documents/trae_projects/风控问数系统/config/semantic_view.yaml) | L5-52（5 指标）/ L53-64（表）/ L65-68（行权限） | 当前签字口径（唯一事实源） |
| [legacy/问数Agent_企业版V2.py](file:///Users/tj/Documents/trae_projects/风控问数系统/legacy/问数Agent_企业版V2.py) | L56-103（SEMANTIC_YAML）、L298-301（METRIC_FUNCS） | 候选口径主来源 |
| [legacy/问数Agent_持续运营V3.py](file:///Users/tj/Documents/trae_projects/风控问数系统/legacy/问数Agent_持续运营V3.py) | L39-61（SEMANTIC_YAML） | 候选口径（仅 2 指标） |
| [legacy/问数Agent_金融风控落地.py](file:///Users/tj/Documents/trae_projects/风控问数系统/legacy/问数Agent_金融风控落地.py) | L44-80（SEMANTIC）、L152-155（CALC） | 候选口径（含错误分母口径） |
| [legacy/问数Agent_初学者最小闭环.py](file:///Users/tj/Documents/trae_projects/风控问数系统/legacy/问数Agent_初学者最小闭环.py) | L46-65（SEMANTIC） | 未签字样本（无治理字段） |
| [src/riskqa/calc/metrics.py](file:///Users/tj/Documents/trae_projects/风控问数系统/src/riskqa/calc/metrics.py) | L13-53（纯函数）、L55-62（注册表） | 实际计算实现 |
| [tests/scenario/test_v2_scenarios.py](file:///Users/tj/Documents/trae_projects/风控问数系统/tests/scenario/test_v2_scenarios.py) | L21-22、L224-225、L264-266 | 冻结值 |
| [evals/golden_set.yaml](file:///Users/tj/Documents/trae_projects/风控问数系统/evals/golden_set.yaml) | 全文件（20 题） | 题库期望值 |
| [evals/seed.sql](file:///Users/tj/Documents/trae_projects/风控问数系统/evals/seed.sql) | 全文件（SQLite 二进制） | 计算数据源 |
| [OPEN-QUESTIONS.md](file:///Users/tj/Documents/trae_projects/风控问数系统/OPEN-QUESTIONS.md) | 全文件 | 既有待确认项 |

指纹（sha256，2026-11-05）：

```text
a85c4bf6ff8eecf3bd418fcb213d5b839f2e2e0c7cd6b39f579216a60c28a7d7  config/semantic_view.yaml
24b1b5673109e4d3fc5460358f5ce4435618df7cfeace1e0cdae3697f938a8d9  legacy/问数Agent_企业版V2.py
bcc7efb7a05c77ad6236c965a7a498f6c2673d7b72f270b8518176e526867b1c  legacy/问数Agent_持续运营V3.py
c7abdcd6a6a3f40314d32b110e8e4be42e9c099c3fc1596bfe0a03242a0aa9b8  legacy/问数Agent_金融风控落地.py
90058bd8172ce8bd50a7751e80ab49a8b22c0bef8b3145bca69ee99e29622fab  legacy/问数Agent_初学者最小闭环.py
1098cc326172d1935bc9c5468cc2f4aacb29d49aabfdaf8421da23b3b92cd759  src/riskqa/calc/metrics.py
d973156b7f7078c51eaec4f83832e1d83cce00815ba11afff459ab8d70d1d565  tests/scenario/test_v2_scenarios.py
d3047f032c9201c13a8d1a88520cb3a8b59d169249cbbda3ef0408e5b358159f  evals/golden_set.yaml
749922c1dc716527d73c4e3ab6a1940a2f94a2993c1c7138e339d894113d740b  evals/seed.sql
```

---

## 二、5 指标候选口径表

### 2.1 一览

| 指标 | legacy 候选（文件:行） | config（行） | owner / signed_at | changelog | calc | dims | aliases | 判定 |
|---|---|---|---|---|---|---|---|---|
| fpd30_rate | V2 L59-68；V3 L42-51；金融版 L45-53 | L6-15 | 风控策略组 / 2026-09-30 | v1.0（含宽限期 3 天） | `fpd30_rate`（metrics L13） | channel, product, vintage | fpd30, 首期逾期率, 首期逾期 | **一致**（措辞差异） |
| pass_rate | V2 L69-78；V3 L52-61 | L16-25 | 风控策略组 / 2026-09-30 | v1.0（分母=提交数） | `pass_rate`（L19） | 同上 3 维 | 通过率, pass | **一致**（V2 表述更明确） |
| ks | V2 L79-87；金融版 L54-62 | L26-34 | 模型组 / 2026-09-30 | v1.0（OOT） | `ks`（L23） | vintage | 无 | **一致**；V3 未登记 |
| auc | V2 L88-95；金融版 L63-71 | L35-42 | 模型组 / 2026-09-30 | **空** | `auc`（L34） | vintage | 无 | 一致；changelog 缺口 |
| psi | V2 L96-103；金融版 L72-79 | L43-50 | 模型组 / 2026-09-30 | **空** | `psi`（L45） | vintage | 无 | 一致；changelog 缺口 |

### 2.2 措辞差异（不构成口径变更，记录备查）

| # | 差异 | 证据 | 影响 |
|---|---|---|---|
| W-01 | fpd30 desc：V2 未写「宽限期 3 天」，V3/config 写了；config 的 changelog 采用 V2 的 note 文案 | V2 L60/L68；V3 L43/L51；config L9/L14 | 无（宽限期只影响上游取数，函数不感知） |
| W-02 | pass_rate desc：V3 缺「非通过数」四字 | V3 L53；config L19 | 无（分母语义相同） |
| W-03 | fpd30 aliases 顺序：V3 为 `[fpd30, 首期逾期, 首期逾期率]`，config 为 `[fpd30, 首期逾期率, 首期逾期]` | V3 L49；config L13 | 无（精确匹配）；模糊匹配须最长优先 |
| W-04 | `pass` 别名只有 V2/config 有，V3 没有 | V2 L74；V3 L59；config L24 | 无（config 是超集） |
| W-05 | auc/psi 的 `changelog: []` 被 [check.py L23-24](file:///Users/tj/Documents/trae_projects/风控问数系统/src/riskqa/semantic/check.py#L23-L24) 显式放行 | V2 L95/L103；config L41/L49 | 治理缺口：两个指标无变更轨迹 |

### 2.3 数值证据（2026-11-05 实测，pandas 2.2.3）

| 题号 | 指标/切片 | 实测值 | 题库期望 | 冻结值 | 结论 |
|---|---|---|---|---|---|
| Q001 | fpd30 整体 | 0.285904 | 0.285904 | test L21 `0.2859042553191489` | ✅ 逐位一致 |
| Q002 | fpd30 × 渠道 A/B/C | 0.223919 / 0.424528 / 0.251701 | 同 | test L22 `0.22391857506361323`（A） | ✅ |
| Q004 | 通过率 × 产品 P1/P2 | 0.625337 / 0.628821 | 同 | — | ✅ |
| Q005 | KS 2026-08 | **0.254183**（用 `y`） | 0.254183 | — | ✅；误用 `is_fpd30` 得 **0.059781** |
| Q006 | AUC 整体 | 0.411955 | 0.411955 | test L225 `0.411955` | ✅ |
| Q007 | PSI 整体 | 0.20766 | 0.20766 | — | ✅ |
| Q008 | fpd30 × 渠道 × 产品 | A/P1 0.243902、A/P2 0.190476、B/P1 0.414286、B/P2 0.444444、C/P1 0.24359、C/P2 0.26087 | 同 | — | ✅ |
| Q009 | 渠道申请量 | A 602 / B 358 / C 240（合计 1200） | 同 | — | ✅ |
| Q010 | fpd30 × 月份 | 2026-07 0.249315 / 2026-08 0.320413 | 同 | — | ✅ |
| Q011 | 全量 fpd30（禁列值） | 0.179167 | 禁止出现 | — | ✅ 与禁列值一致 |
| Q012 | 通过率整体 | 0.626667 | 0.626667 | test L266 `0.626667` | ✅ |
| Q013 | KS 整体 | 0.159452（`score == score_v3` 为 True；`score_v2` 为 0.086003） | 0.159452 | test L224 `0.159452` | ✅ |

补充事实：放款户 752 户；vintage 2026-07 577 行 / 2026-08 623 行；产品仅 P1/P2；11 列**零缺失**。

---

## 三、冲突清单（原样并列，不裁决）

### C-01 · fpd30 三种算法

| 候选 | 算法 | 实测值 |
|---|---|---|
| config / V2 / V3 / `calc/metrics.py` L13-17 | `is_fpd30.mean()` 且 `is_pass == 1`（752 户） | 0.285904 |
| 题库 Q011 禁列口径 | `is_fpd30.mean()` 全量 1200 行 | 0.179167 |
| 金融版 L152 | `y.mean()`，无放款户过滤 | 0.175 |

影响：Q001/Q003 依赖第一种；Q011 用第二种作反例；金融版口径若被误采纳，整体 FPD30 会低 0.11 左右。

### C-02 · `analyst_qa` 行权限范围

| 候选 | 条件 | 证据 |
|---|---|---|
| config | `channel = 'A'` | semantic_view L65-68 |
| V2 | `channel = 'A'`（config 来源） | V2 L106-110 |
| V3 | `channel IN ('A','B','C')`（扁平字符串，结构已不可用） | V3 L62-70；OPEN-QUESTIONS C-6 |

影响：若按 V3 放开，Q002 三渠道对 analyst 可见；若按 config，只可见 A。**属权限放宽，必须 Owner 签字。**

### C-03 · `y` 与 `is_fpd30` 标签混用陷阱

| 标签 | 均值 | 用途 | 证据 |
|---|---|---|---|
| `is_fpd30` | 0.179167 | FPD30 的分子 | config L57、calc L13 |
| `y` | 0.175 | KS/AUC/PSI 的好坏标签 | calc L23-53、金融版 L153-155 |

实测：Q005 用 `y` 得 **0.254183**；把 `y` 替换成 `is_fpd30` 得 **0.059781**。两个标签不等价，且语义层未登记 `y`。

### C-04 · `tables.columns` 缺列

| 来源 | 列 | 证据 |
|---|---|---|
| 语义层声明（8 列） | apply_id, customer_id, channel, product, vintage, is_pass, is_fpd30, score | config L57 |
| seed 实际（11 列） | 上述 8 列 + `score_v3`, `score_v2`, `y` | seed 实测 `PRAGMA table_info` |

影响：KS/AUC/PSI 必须读 `y`，而 `y` 不在白名单；Q013 的 `score_v3` 陷阱题也无法通过慢路闸门。`docs/data-model.md` 未定义 `fact_application`，语义层是唯一声明。

### C-05 · 未签字样本（只存档）

| 样本 | 指标 | 缺什么 | 证据 |
|---|---|---|---|
| V1 | `fpd30 / pass_rate / avg_score` | owner、signed_at、changelog 全缺；unit 用 `%`；expr 直接取 `y`/`passed` | V1 L46-65 |
| 金融版 | `fpd30_rate / ks / auc / psi`，无 `pass_rate` | 无 alises；fpd30 用 `y` 均值 | 金融版 L44-80、L152-155 |

### C-06 · auc / psi 无变更记录

`changelog: []`（V2 L95/L103、config L41/L49）虽被加载器放行，但「签字口径无版本轨迹」与 P-05 治理意图不符，属治理缺口而非计算差异。

---

## 四、Owner 问题清单（一题一问，目标单条 <2 分钟）

| # | 问题（请 Owner 只需回答一句） | 状态 | 影响范围 |
|---|---|---|---|
| O-01 | FPD30 的分母确认是「放款户（`is_pass=1`，752 户）」吗？金融版「`y` 均值」口径是否承认为历史错误？ | 待签字 | Q001/Q003、对外报数 |
| O-02 | 分析师角色是否只允许看 A 渠道（当前 config），还是 A/B/C 全开（V3）？ | 待签字 | 行级权限、Q002 可见性 |
| O-03 | `y` 是独立的「坏样本标签」还是 `is_fpd30` 的别名？若独立，请给出取数规则。 | 待签字 | KS/AUC/PSI 全部、Q005/Q013 |
| O-04 | `score / score_v2 / score_v3` 三列中，哪一列是正式评分口径？另外两列是历史版本还是实验列？ | 待签字 | 模型指标、Q013 反例设计 |
| O-05 | 「落地方案 §4.3」的四指标（证据率/冲突清零率/考古发现率/人审时长）精确定义是什么？ | 待签字 | T-4.0.9 验收判定 |

---

## 五、未决项与「不入库」声明

1. **不入库**：本报告不产生任何语义层条目；金融版与 V1 的候选口径只作为考古证据存档，**不写入 config**。
2. **外部文档缺口**：「落地方案 §4.3」不在本仓库（[constraints.md L66](file:///Users/tj/Documents/trae_projects/风控问数系统/docs/constraints.md#L66) 仅将其列为外部设计文档），四指标定义无法核对。本报告暂按「证据率 = 带 `文件:行` 证据的候选数 / 候选总数」自定可判定口径。
3. **未闭环的旧项**：OPEN-QUESTIONS #12（`normalize_missing` 双版本差异）、#13（金融版 dispatch 接口不匹配）、#15（分组 NaN）、#16（假数字）仍开放；本批 seed 零缺失，数值不受影响，但不代表问题消失。
4. **冲突处置边界**：C-01/C-02 属「必须 Owner 签字」；C-03/C-04 属「代码/配置缺陷」，建议在 V4.1 慢路定型前按 P-15 流程修复；C-05 只存档；C-06 属治理补录。
5. **复现方式**：任何数值均可由 `evals/seed.sql` + `src/riskqa/calc/metrics.py` 纯函数复算；报告中的数值一律标注 2026-11-05 实测。

---

## 六、Owner 签字结果（2026-11-05）

> 签字落笔位置：`config/semantic_view.yaml`。本节只记录决定，不复制 YAML 全文；数值未变。

| 编号 | 事项 | 最终决定 | 落笔情况 |
|---|---|---|---|
| S-01 | FPD30 分母与历史口径 | **A**：分母=放款户（`is_pass=1`）；金融版 `y` 均值口径作废 | `fpd30_rate` 追加 changelog v1.1；`signed_at` 保持 2026-09-30；`desc` 未动 |
| S-02 | `analyst_qa` 行权限 | **A**：仅 A 渠道（保持现状） | `row_policies` 未动 |
| S-03 | `y` 标签定义 | **A**：`y` 为独立坏样本标签，不是 `is_fpd30` 别名；具体推导规则未书面化 | `tables.fact_application.columns` 追加 `y` |
| S-04 | 正式评分列 | **A**：`score` 为正式列（与 `score_v3` 同值）；`score_v2` 为历史列 | 同一 `columns` 追加 `score_v2, score_v3` |
| S-05 | 「落地方案 §4.3」四指标定义 | **未决**：外部文档仍缺（OPEN-QUESTIONS #24） | 无 config 改动 |
| S-06 | `pass_rate` 复核 | **确认**：口径与字段无需变更 | 无字段变化 |
| S-07 | `ks` 标签/评分列 | **确认**：坏样本=`y`，评分列=`score` | `desc` 明示；changelog v1.1；`signed_at`=2026-11-05 |
| S-08 | `auc` 历史 changelog | **同意补录** v1.0（2026-09-30，秩比较、平局计 0.5） | 补录 v1.0 + v1.1；`signed_at`=2026-11-05 |
| S-09 | `psi` 描述与实现不一致 | **A**：修正描述为「好坏样本分数分布差」；实现未改 | `desc` 改写；changelog v1.1；`signed_at`=2026-11-05 |

**默认取数范围（用户给定）**：由用户给定取数条件（如产品编号、时间范围）；默认从数仓拉取近 30 天 A 产品数据并计算指标。

> 注意：这是**取数范围约定，不是 `y` 的推导规则**。当前 config 无字段承载该约定，已登记 OPEN-QUESTIONS #28。

---

## 七、冲突裁决账（2026-11-05）

> 核对基准：第二节 C-01—C-06 原文。判定标准：冲突在 `config/semantic_view.yaml` 已有唯一确定取值，且签字单或 changelog 能指认决定来源；“只登记 OPEN-QUESTIONS”或“推迟到 V4.1”不算已裁决。

| 编号 | 一句话描述 | 涉及指标/字段 | 裁决状态 | 裁决结论与依据 | 落地位置 |
|---|---|---|---|---|---|
| C-01 | fpd30 有三种算法：放款户 `is_fpd30`=0.285904 / 全量=0.179167 / 金融版 `y` 均值=0.175 | `fpd30_rate` | **已裁决** | S-01=A：分母=放款户（`is_pass=1`）；金融版 `y` 均值口径作废。全量 0.179167 仅保留为 Q011 禁列反例，不是生产口径 | [`config` L6-15](file:///Users/tj/Documents/trae_projects/风控问数系统/config/semantic_view.yaml#L6-L15)；[`calc/metrics.py` L13-17](file:///Users/tj/Documents/trae_projects/风控问数系统/src/riskqa/calc/metrics.py#L13-L17) |
| C-02 | `analyst_qa` 行权限是仅 A（config/V2），还是 A/B/C 全开（V3） | `row_policies.analyst_qa.fact_application` | **已裁决** | S-02=A：仅 A 渠道，保持现状 | [`config` L69-73](file:///Users/tj/Documents/trae_projects/风控问数系统/config/semantic_view.yaml#L69-L73) |
| C-03 | `y` 与 `is_fpd30` 标签混用：语义层未登记 `y` | `y`、`is_fpd30`；KS/AUC/PSI | **已裁决** | S-03=A：`y` 是独立坏样本标签，不是 `is_fpd30` 别名；KS/AUC/PSI 用 `y`，FPD30 用 `is_fpd30` | [`config` L62](file:///Users/tj/Documents/trae_projects/风控问数系统/config/semantic_view.yaml#L62)、L27-55；[`calc/metrics.py` L23-52](file:///Users/tj/Documents/trae_projects/风控问数系统/src/riskqa/calc/metrics.py#L23-L52) |
| C-04 | `tables.columns` 声明 8 列，seed 实际 11 列，缺 `y/score_v2/score_v3` | `tables.fact_application.columns` | **已裁决** | S-03/S-04 签字补列，OPEN-QUESTIONS #23 → C-9 | [`config` L62](file:///Users/tj/Documents/trae_projects/风控问数系统/config/semantic_view.yaml#L62) |
| C-05 | 未签字样本：V1 三个指标、金融版四个指标缺 owner/signed_at/changelog 或口径不同 | V1 `fpd30/pass_rate/avg_score`；金融版 `fpd30_rate/ks/auc/psi` | **已裁决**（2026-11-05） | 裁决结论：**整体作废、仅作教学反例**——V1 的 `avg_score`、金融版其余候选口径一律记为「已作废、不登记进语义层、不参与问数」，只保留作为 Q011 一类反例教学的参照。依据：S-01 已作废金融版 fpd30 分母口径 + AGENTS.md P-04「未登记指标一律拒绝」。**属文档层面记录，不改变任何取值与行为** | 本节第七节；[`OPEN-QUESTIONS.md` C-11](file:///Users/tj/Documents/trae_projects/风控问数系统/OPEN-QUESTIONS.md) |
| C-06 | `auc` / `psi` 的 `changelog: []`，签字口径无版本轨迹 | `auc`、`psi` 的 changelog | **已裁决** | S-08 补录 `auc` v1.0（秩比较、平局 0.5）+ v1.1；S-09=A 为 `psi` 追加 v1.1（描述修正） | [`config` L37-55](file:///Users/tj/Documents/trae_projects/风控问数系统/config/semantic_view.yaml#L37-L55) |

**Owner 表态（C-05，2026-11-05）**

- **表态主体 / 日期 / 渠道**：Owner（用户本人）／ 2026-11-05 ／ 本会话确认（选 A）。
- **表态内容（书面化表述）**：
  - V1 的 `avg_score` 与金融版其余候选口径**整体作废**；
  - **不登记进语义层**、**不参与问数**、**不进入任何正式报告数字**；
  - 仅保留为教学 / 反例参照（如 Q011 一类）；
  - 若将来有人主张把其中任一候选升格为正式指标，**必须先推翻本表态**，并走 **P-05 签字 + P-13 晋升流程**，不得直接登记。
- **声明**：本段为书面化改写，非逐字引述；逐字原话未留存。
- **影响边界**：本表态仅影响治理记录，**不改变任何已签字指标的取值与计算行为**；不构成「双方（业务 + 数仓）签字」，也不代表口径已获双方共识。

### 7.1 冲突清零率

- 总冲突：6（C-01—C-06）
- 已裁决：6（C-01、C-02、C-03、C-04、C-05、C-06）
- **冲突清零率 = 6 / 6 = 100%**（目标 100%，**达标**）

C-05 的裁决方式为**整体作废、仅作教学反例**：V1 的 `avg_score`、金融版其余候选口径一律记为「已作废、不登记进语义层、不参与问数」，只保留作为 Q011 一类反例教学的参照（依据：S-01 + P-04）。这是**文档层面的裁决**，未改动 `config/`、`calc/` 或任何数值。

> 口径说明：本项清零率仅为**文档裁决层面**的完成度，不代表「双方（业务 + 数仓）签字」与「人审 2 分钟实测」已完成（后者两项见 OPEN-QUESTIONS #30 与第七节 7.2）。

### 7.2 其余验收指标现状

| 指标 | 现状 | 判定 |
|---|---|---|
| 证据率 | **100%（5 / 5 指标均有 `文件:行` 证据，共 79 处）** | ≥90% 达标 |
| 考古发现率 | **6 条冲突（C-01—C-06）**；另有 5 条措辞差异（W-01—W-05）不计入 | 报告型计数，原文无阈值 |
| 人审耗时 | **未实测**（用户决定不做实测） | 文档要求单条 <2 分钟；无实测数据，无法判定 |

**阈值备注**：外部文档原文要求证据率「趋近 100%」；本项目验收沿用 `docs/tasks.md` 的 `≥90%`（**不改标准**），实测 100%。两者字面不同但本批实测满足更严的一方。

**外部文档缺口已关闭**：第五节第 2 条所述「落地方案 §4.3 不在仓库」已由 [`docs/archaeology/s05-landing-plan.md`](file:///Users/tj/Documents/trae_projects/风控问数系统/docs/archaeology/s05-landing-plan.md) 的脱敏存档解决；原缺口记录保留为历史。

### 7.3 验收偏离记录（2026-11-05，用户授权）

四项指标的实际状态：

| 指标 | 原标准 | 实际状态 | 是否达标 |
|---|---|---|---|
| 证据率 | ≥90%（文档原文「趋近 100%」） | 100%（5/5 指标，79 处 `文件:行`） | 达标 |
| 冲突清零率 | 100% | 6/6 = 100%（文档裁决层面，C-05 整体作废） | 达标 |
| 考古发现率 | 原文无阈值 | 6 条冲突（C-01—C-06） | 报告型计数，无阈值可判 |
| 人审耗时 | 单条 <2 分钟 | **弃权**，未实测 | **未验证** |

**偏离 1 · 人审耗时：弃权**
- 放宽了什么：原标准「人审单条 <2 分钟」本轮不做实测，本版本该项不计入通过条件。
- 相对哪条原标准：`docs/tasks.md` T-4.0.9「验收怎么验：…人审单条 <2 分钟」。
- 授权人 / 日期：用户（Owner）／ 2026-11-05。
- 代价：该验收指标无实测证据支撑，只能写「按设计预期 / 未验证」，不得写成已验证或达标。
- 回退条件：若 V4.1 启动前补做实测，该项恢复按原标准判定；若永不补齐，本任务完成状态视为**条件性完成**。

**偏离 2 · 双方签字：顺延 V4.1**
- 放宽了什么：原要求「业务 + 数仓」双方签字，当前只有 Owner（用户）单方签字；双签顺延至 V4.1，作为 V4.1 入口前置条件。
- 相对哪条原标准：落地方案 §4.3 第 4 步「双方（业务 + 数仓）签字」（见 [`s05-landing-plan.md`](file:///Users/tj/Documents/trae_projects/风控问数系统/docs/archaeology/s05-landing-plan.md)）。
- 授权人 / 日期：用户（Owner）／ 2026-11-05。
- 代价：口径签字缺业务与数仓侧确认，当前语义层只代表 Owner 单方意见；双签前不得宣称口径已获双方共识。
- 回退条件：若 V4.1 启动前补齐双签，该项恢复按原标准判定；若永不补齐，本任务完成状态视为**条件性完成**。

> **结论**：本报告的「完成」是**条件性完成**，不构成四项指标全部达成的证明。上表只有证据率与冲突清零率达标；人审耗时为弃权、未验证，双方签字缺失并顺延 V4.1。
