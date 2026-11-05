# 实验：2026-11-05 【V4.0 行为等价基线（T-4.0.1 / T-4.0.10-②）】

> 目的：补齐 V4.0 退出门禁 ②「V2/V3 迁入前后输出逐场景比对一致（golden 输出留档）」。
> 证据全部来自**真跑**：legacy 四个单文件中的 V2 / V3 两个可直接执行文件原样运行，
> 包化实现按其 `tests/scenario/` 断言逐条复跑；未手抄、未推断、未修改任何实现与测试。

## 一、环境指纹

| 项 | 值 |
|---|---|
| 日期 | 2026-11-05 |
| 解释器 | `/Users/tj/Documents/trae_projects/风控问数系统/.venv/bin/python` |
| Python | 3.13.12 (main, Feb 4 2026, 00:05:32) [Clang 21.1.4] |
| pandas | 2.2.3 |
| numpy | 2.2.6 |
| langgraph | 1.2.19 |
| PyYAML | 6.0.3 |
| pytest | 8.4.2 |

## 二、运行命令（可复现）

```bash
cd /Users/tj/Documents/trae_projects/风控问数系统

# legacy V2（只读运行，不改文件）
.venv/bin/python legacy/问数Agent_企业版V2.py \
  > docs/experiments/2026-11-05-v40-legacy-v2.stdout.txt 2> /tmp/legacy_v2.err

# legacy V3（只读运行，不改文件）
.venv/bin/python legacy/问数Agent_持续运营V3.py \
  > docs/experiments/2026-11-05-v40-legacy-v3.stdout.txt 2> /tmp/legacy_v3.err

# 包化 17 场景（复用 tests/conftest.py 的 demo_df / _gen_logs，不复制造数逻辑）
.venv/bin/python docs/experiments/2026-11-05-v40-packaged-probe.py \
  > docs/experiments/2026-11-05-v40-packaged.stdout.txt 2> /tmp/packaged.err

# 交叉确认包化场景测试本身全绿
.venv/bin/python -m pytest tests/scenario -q
```

两个 legacy 进程 `stderr` 均为 **0 字节**；包化探针 `stderr` 也为 **0 字节**。
legacy 退出码 `0`（末尾断言全过），包化探针退出码 `0`（17 场景断言全过）。
`pytest tests/scenario`：`17 passed in 0.47s`。

## 三、判定口径（先定义，再判定）

- **A · 逐字节相同**：把两侧输出拆成可比字段（数值、fid、SQL、状态、计数、错误码、文案），
  每个字段的字符串表示逐字节一致（含浮点打印位数）。
- **B · 语义相同、字面不同**：字段值的集合/数值一致，但枚举顺序、异常类型或包装文案不同。
- **C · 真实差异**：数值、判定结论或异常契约发生变化。

> 说明：legacy 的 `main()` 与包化探针是两套输出外壳（banner、`key=value` vs `key：value`），
> 行级字节比对无意义；因此按上述**字段级**口径判定。原始两版输出全文已一并入库，可复核。

## 四、17 场景对照表

| 编号 | 场景 | legacy 关键输出 | 包化关键输出 | 判定 | 差异说明 |
|---|---|---|---|---|---|
| V2-1 | 快路问数 | `route=fast`；`fid=F0001`；`value=0.2859042553191489`；`PASS` | 同 | A | 无 |
| V2-2 | 慢路 + 行级权限 | 注入后 SQL `... WHERE (channel = 'A') AND is_pass = 1 ...`；`[('channel=A', 0.2239)]`；`PASS` | 同 | A | 无 |
| V2-3 | must 级人审 | `pending=True`；`review_level=must`；trace 8 节点；`accept/must`；`FALLBACK` + `fabricated_ref F0001` | 同 | A | 恢复后均判失败且失败码一致 |
| V2-4 | 失败复现 | `缺少 LIMIT`；`failures=[('step_limit', 6)]`；失败叙事 | 同 | A | 无 |
| V2-5 | 交叉验证 | `0.223919 vs 0.146179 不一致`；修正后 `0.223919 == 0.223919` | 同 | A | 无 |
| V2-6 | 监控归因 | event `0.2859042553191489 / 0.25 / overall`；确认 1、排除 1；`needs_human_confirm=True` | 同 | A | 无 |
| V2-7 | 回测 | `ks 0.159452 / 0.086003`；`auc 0.411955 / 0.514925`；`as_of 2026-09-30`；叙事同 | 同 | A | 无 |
| V2-8 | 内联黄金题（3 题） | `3/3 PASS`；`0.285904 / 0.223919 / 0.626667` | 同 | A | 这是 legacy 内联 3 题，不是 `evals/golden_set.yaml` 的 20 题（T-4.1.8） |
| V2-9 | 降级 + 编造引用 | `TimeoutError` 降级文案；`fabricated_ref F9999` + `render_mismatch F0001 0.28 vs 0.285904…` | 同 | A | 无 |
| V3-1 | 治理护栏 | `min_users 3 → 2`；`window=30`；`retention=365`；`domain=5`；护栏拦截文案同 | 同 | A | 无 |
| V3-2 | 签名归并 | `199 → 6`；`33.2×`；`[92,47,30,16,12,2]`；变体 `[6,5,1,2,1,1]` | 同 | A | 无 |
| V3-3 | 热度 / 防失真 | 提名 4、拦截 2；hot `(30,6,28)`、单人 `83%`；batch `2 天` | 集合与数值同；**列表顺序不同** | B | legacy 按 log 数降序打印，包化按签名 dict 插入序枚举；非缺陷 |
| V3-4 | 口径冲突 | `fpd30_rate` 93 次；`77 : 16` 两种指纹 | 同 | A | 无 |
| V3-5 | 评审材料 | 首两行同（`93 次 / 10 用户 / 28 天 / 8 问法 / 3 签名 / 2 口径`）；`⚠️=1`；QID 行在 | 同 | A | 无 |
| V3-6 | 晋升三件套 | `owner=风控策略组·王五`；`dims=['product']`；`aliases=6`；`n_queries=92 / n_users=9`；拒算后注册 = `596.0` | 数值同；**拒算异常类型不同** | C | legacy V3 抛 `ValueError`，包化抛 `UnregisteredMetricError`（详见 §五-1） |
| V3-7 | 升级链 | `pending_review → reminded → overdue → shelved` | 同 | A | 无 |
| V3-8 | alias 回填 | 三个口语问法均命中 `loan_amt` | 同 | A | 无 |

### 附加：V2 运行汇总（不属 17 场景，但同源可核）

| 项 | legacy | 包化 | 判定 |
|---|---|---|---|
| trace 节点数 | 47 | 47 | A |
| 审计条数 | 2 | 2 | A |
| 语义层版本 / 指标枚举 | `2.0` / `['auc','fpd30_rate','ks','pass_rate','psi']` | 同 | A |
| AI 标识样例 | 完全一致 | 完全一致 | A |
| 估算 token 成本 | 5394 | 5498（+104，+1.9%） | **C** |

## 五、分类统计与真实差异

### 分类统计（17 场景）

| 判定 | 条数 |
|---|---|
| A · 逐字节相同 | **15** |
| B · 语义相同、字面不同 | **1**（V3-3） |
| C · 真实差异 | **1**（V3-6） |

另有 1 条**附加观测差异**（V2 汇总的估算 token 成本），不计入 17 场景统计。

### 真实差异清单

1. **V3-6 · 未登记指标的异常类型变更**
   - legacy：`legacy/问数Agent_持续运营V3.py` L118—L120，`compute_metric` 抛 `ValueError`；
     且同一文件 L678—L683 用 `except ValueError` 捕获后打印「快路尚不可用」。
   - 包化：`src/riskqa/calc/metrics.py` L64—L67 抛 `UnregisteredMetricError`
     （定义于 `src/riskqa/semantic/layer.py` L10），**不是** `ValueError` 子类。
   - 影响：拒算结论与后续 `596.0` 完全一致；但任何沿用 `except ValueError` 的调用方不再捕获。
     已在 `tests/scenario/test_v3_scenarios.py` L174 注释中承认，但未进 `OPEN-QUESTIONS`——
     本次新增 **#26**。
2. **附加 · V2 估算 token 成本 5394 → 5498**
   - 原因：慢路 prompt 内嵌 `fpd30_rate` 的 `desc`。legacy V2 为
     「首期逾期率：放款客户中首期 DPD30+ 的占比」，包化读 `config/semantic_view.yaml`
     为「…（分母=放款户，宽限期 3 天）」，每次慢路调用多 16 字符（`len//4` 口径）。
   - 影响：只影响成本估算与 prompt 文本，17 个场景的数值/判定均不变。已新增 **#27**。

### 已知偏差（本次未覆盖，非本次产生的差异）

| 偏差 | 对应 OPEN-QUESTIONS | 说明 |
|---|---|---|
| 无 Parquet 加载 | #18 | 本次只跑 demo DataFrame 与 CSV 往返，未触发 Parquet 路径 |
| 无数仓真实导出 | #2 | T-4.0.4 未完成，本次不涉及 |
| `tables.columns` 缺 `y / score_v2 / score_v3` | #23 | 慢路 prompt 的列清单仍为 8 列（与 legacy V2 一致），不影响这 17 场景 |
| 20 题评估 runner 未实现 | #21 / T-4.1.8 | V2-8 只是 legacy 内联 3 题，不是 `evals/golden_set.yaml` |
| `seed.sql` 无 sha256 | #22 | 本次未使用 `evals/seed.sql` |

## 六、原始输出保存位置

| 文件 | 内容 | 大小 |
|---|---|---|
| `docs/experiments/2026-11-05-v40-legacy-v2.stdout.txt` | legacy V2 `main()` 完整 stdout（80 行） | 5580 B |
| `docs/experiments/2026-11-05-v40-legacy-v3.stdout.txt` | legacy V3 `main()` 完整 stdout（85 行） | 5196 B |
| `docs/experiments/2026-11-05-v40-packaged.stdout.txt` | 包化 17 场景探针完整 stdout（23 行） | 4478 B |
| `docs/experiments/2026-11-05-v40-packaged-probe.py` | 包化探针源码（复用 `tests/conftest.py` 造数） | — |

未截断、未改写；`stderr` 三方均为 0 字节，未入库。

## 七、结论

- 17 场景中 **15 条字段级逐字节一致**，1 条仅枚举顺序不同，1 条异常类型变化；
  **无任何指标数值、业务判定、状态机或失败码发生变化**。
- V4.0 退出门禁 ② 的「golden 输出留档」由本文件 + 三份 stdout 满足。
- `docs/tasks.md` T-4.0.1 据此标 ✅（2026-11-05）；T-4.0.10 的 ② 项同样补齐，
  但 T-4.0.10 仍缺「用户签字」，故不标完成。

**审计时点（2026-11-05 补记）**：`config/semantic_view.yaml` 于 2026-11-05 完成 Owner 口径签字（S-01—S-08、S-09=A），`ks/auc/psi` 的 `desc` 有文字修订、`tables.columns` 补列；**上述变更不改变任何指标数值，本文件全部结论仍然有效**。本文件记录的 config sha256 与慢路估算 token 数（5498）对应签字前的版本，已随 desc 变化失效；成本变化口径见 OPEN-QUESTIONS #27。
