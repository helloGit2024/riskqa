---
description: 问数链路（语义层/快慢路/校验闸/口径指纹）的硬要求。改 semantic/calc/tools/verify/orchestration/governance 任何模块前必读。
globs: src/riskqa/semantic/**, src/riskqa/calc/**, src/riskqa/tools/**, src/riskqa/verify/**, src/riskqa/orchestration/**, src/riskqa/governance/**, config/semantic_view.yaml, config/governance.yaml
alwaysApply: false
---

# 问数链路规则（nl2sql-core）

> 按需加载。本文件是 `AGENTS.md` P-03..P-14 在问数链路的展开；冲突时以 AGENTS.md 为准。

## 1 · 语义层（M1）硬要求

- `config/semantic_view.yaml` 是口径唯一事实源（P-15）。字段：`synonyms / dimensions / metrics{desc,unit,dims,calc,owner,signed_at,changelog} / tables / joins / tests`。
- 指标卡三字段（owner/signed_at/changelog）缺一 → 拒载（P-05）。加载器抛 `UnsignedMetricError`，不许 warning 后放行。
- FC/MCP enum = `sorted(SEMANTIC)` 与维度枚举，**代码里不允许出现第二份指标清单**（P-08）。
- 新增指标流程：Owner 签字 → YAML 合入（Git）→ 注册纯函数 → 才可用。顺序反了 = 快路拒服（P-09）。

## 2 · 快路硬要求

- 入参四元组 `(metric, dims, filters, time_range)`；dims 必须在 `metrics[metric].dims` 内。
- 输出必经 FactStore；回答文本数字一律 `{{fid}}`（P-06）。
- 前闸（`tools/pre_tool_gate`）是代码级硬阻断，不是 prompt 提醒——把 reason 塞进 prompt 让模型自己纠正是错的（模型会选择性失聪）。
- 无事实禁出报告：`finish` 时 FactStore 为空 → 拦截。

## 3 · 慢路硬要求

- 固定图，不许自由循环：schema 链接 → SQL 生成 → 三闸 → 执行 → 修正（≤2 轮）→ 交叉验证 → 人审。
- `check_sql` 三闸缺一不可：SELECT 白名单 / 强制 LIMIT / 注入特征（P-10）。
- 行级权限在**执行前**注入（P-10 + data-model §三）；越权返回空结果。
- 交叉验证不一致 → 返回两侧数字 + 差异说明，**不许取平均、不许挑一个**（V2 实战：0.224 vs 0.146 的教训）。
- 每次慢路执行无条件落 raw log（P-12），含人审编辑后的最终 SQL。

## 4 · 校验闸（M6）硬要求

三重检查，任何一不过整份回退规则模板：
1. 裸数字扫描（叙事层正则）；
2. `{{fid}}` 存在性回表查（P-07）——**不查格式，查存在**；
3. Python 独立重算比对（`calc/recompute_all`，与主流水线分开实现——重算复用主代码 = 校验失去意义）。
回退不是失败，是纪律；回退率是监控指标（见 ops-runbook）。

## 5 · 治理层（V3）硬要求

- 意图签名 `(metric, dims, filters, time_range)`；**filters 只记字段不记值**（参数变体是实例不是需求）。
- SQL 归一化：字面值 → `?`；口径指纹 = 聚合 + WHERE（字面值归一后）；**GROUP BY 差异不算冲突**。
- 冲突检测两级：签名内 + **跨签名（同 metric）**——只在签名内检测会漏掉 `WHERE is_pass=1` vs 无过滤这类真冲突（V3 开发期实测补的洞）。
- 热度三维度：独立用户数 / 时间分布 / 集中度；热度只定优先级，**签字才定晋升**（P-13）。
- 评审材料按签名分组、只标异类；全标红 = Owner 看不出重点（V3 实测修正）。
- 升级链：SLA 72h → 2× 升级 → 7× 搁置；shelved ≠ rejected。
- 治理配置护栏四条（min_queries≥min_users、window≤retention、share∈(0.5,1]、sla≥24h）——护栏失败保持旧配置（P-14）。

## 6 · Reject List（问数链路专属）

- ❌ 让 LLM 裸读 YAML 自己写 SQL（语义层必须藏在工具后）
- ❌ enum 手写复制进工具定义
- ❌ 把维度差异/参数变体报成口径冲突（比没有检测更糟——会训练 Owner 忽略警告）
- ❌ 慢路结果未过人审就进报告或标记"已定位"
- ❌ 晋升时漏注册纯函数
