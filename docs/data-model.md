# 数据模型（data-model.md）

> 上游：`architecture.md`。**表结构的唯一来源是本文件**；代码里的 DDL 必须与此一致。

## 一、实体关系总览

```
semantic_view.yaml（Git，不在 DB）── 被 ──┐
                                          ↓
query_log 1──n fact（result_digest 引用 fid）
    │
    └─1──n confirmed_by（答案确认，只累加热度，不决定晋升）

review_record 1──1 promotion（签字后产生）
review_record 状态机：pending → reminded → overdue → signed/shelved/rejected

audit_entry（旁路，全链路 Observer 写入，不参与业务关系）
alert（升级链提醒发送记录）
```

**两条设计红线**：
1. **语义层与治理配置不进数据库**——YAML 是唯一事实源（P-15），DB 只存运营数据。DB 里出现指标口径 = 双事实源事故。
2. **raw log 不可变**——只有 INSERT 和保留期满后的 DELETE，没有任何 UPDATE 路径（P-12）。

## 二、核心表设计

### 2.1 query_log（每次慢路执行无条件落库，1 年保留）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| qid | TEXT PK | 否 | — | 唯一 ID（Q+序号） |
| question | TEXT | 否 | — | 原始问题文本，一字不改 |
| sql | TEXT | 否 | — | 最终执行的 SQL（含人审编辑后版本） |
| sql_edited | INTEGER | 否 | 0 | 人审时改过 SQL 吗（改过=权重更高，评审重点看） |
| result_digest | TEXT(JSON) | 否 | — | 摘要：标量值 or top 行 + fact_id，**不存全量** |
| user | TEXT | 否 | — | 提问人 |
| dept | TEXT | 否 | — | 部门（行级权限的归属维度） |
| ts | TEXT | 否 | — | ISO 时间戳（热度时间分布靠它） |
| confirmed_by | TEXT(JSON) | 否 | `[]` | 做过"答案确认"的人列表 |
| signature | TEXT | 是 | — | 意图签名（归并后回填，抽取是异步的） |

**索引**：`idx_ql_ts(ts)`、`idx_ql_user(user)`、`idx_ql_sig(signature)`。
**为什么这样设计**：不存结果全量（隐私+体积，V3 §4.2）；不存上下文快照（归并只需签名，存快照存储翻十倍且无收益）；confirmed_by 是独立列表而非计数——防刷量时要点名。

### 2.2 fact（FactStore 持久化）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| fid | TEXT PK | 否 | — | F0001 起，全文唯一 |
| value | REAL | 否 | — | 数值 |
| unit | TEXT | 否 | — | ratio/amount/count |
| metric | TEXT | 否 | — | 指标名（必须已登记） |
| segment | TEXT | 否 | `""` | 维度定位（如 `channel=渠道A`），**防整体值误配拆解值** |
| source | TEXT | 否 | — | 计算入口（fast/slow/recompute） |
| qid | TEXT | 是 | — | 关联 query_log（快路的为 NULL） |
| created_at | TEXT | 否 | — | ISO 时间戳 |

**索引**：`idx_fact_metric(metric, segment)`。
**为什么**：segment 字段是 V2 开发期真实 bug 的修复（校验闸把整体 FPD30 误配给渠道 A）——落库时不许省略；fid 一旦生成不可变（数字纪律的物理基础）。

### 2.3 review_record（人审记录 + 状态机）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| rid | TEXT PK | 否 | — | R+序号 |
| subject_type | TEXT | 否 | — | query/slow_result/promotion |
| subject_id | TEXT | 否 | — | 关联 qid 或 signature |
| level | TEXT | 否 | — | none/spot/must（三级人审） |
| state | TEXT | 否 | pending | pending→reminded→overdue→signed/shelved/rejected |
| assignee | TEXT | 否 | — | Owner |
| decided_by | TEXT | 是 | — | 签字人（signed 时必填） |
| decision | TEXT | 是 | — | approve/reject/shelve + 理由 |
| decided_at | TEXT | 是 | — | ISO 时间戳 |
| sla_due | TEXT | 否 | — | T+72h |
| material | TEXT | 是 | — | 评审材料快照（JSON，按签名分组版） |

**索引**：`idx_rr_state(state)`、`idx_rr_assignee(assignee)`。
**为什么**：状态机落库才能算队列积压时长（V3 §10.1 健康指标）；decision 带理由——防重复提名（rejected 的理由是下次提名的过滤条件）。

### 2.4 promotion（晋升记录 + evidence 快照）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| pid | TEXT PK | 否 | — | P+序号 |
| metric | TEXT | 否 | — | 晋升的指标名 |
| signature | TEXT | 否 | — | 来源签名 |
| promoted_at | TEXT | 否 | — | ISO 日期 |
| owner | TEXT | 否 | — | 签字 Owner |
| evidence | TEXT(JSON) | 否 | — | **自包含快照**：n_queries/n_users/window/question_variants/sql_selected/variants_digest/review_record |
| aliases_added | TEXT(JSON) | 否 | — | 回填的问法列表 |
| calc_registered | INTEGER | 否 | 0 | 纯函数是否已注册（0=快路拒服） |

**索引**：`idx_promo_metric(metric)`。
**为什么**：evidence 自包含（raw log 一年后删了仍可审计，V3 §9.1）；calc_registered=0 是新指标晋升后的中间态——快路查到这个标志即拒服（P-09）。

### 2.5 audit_entry（审计，旁路全链路）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| aid | INTEGER PK | 否 | 自增 | — |
| ts | TEXT | 否 | — | ISO 时间戳 |
| actor | TEXT | 否 | — | 谁（用户/系统/LLM  provider） |
| action | TEXT | 否 | — | ask/explore/review/promote/config/export |
| target | TEXT | 是 | — | qid/fid/rid/pid/参数名 |
| detail | TEXT(JSON) | 是 | — | 摘要（不含全量敏感数据） |
| prev_hash | TEXT | 否 | — | 哈希链前一环（可选加固） |

**索引**：`idx_audit_ts(ts)`、`idx_audit_actor(actor)`。
**为什么**： Observer 全链路写入（V2 已实现）；detail 只存摘要——审计要能回答"谁在什么时候动了什么"，不需要把客户数据再抄一份。

### 2.6 alert（告警发送记录）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK | 否 | 自增 | — |
| ts | TEXT | 否 | — | 发送时间 |
| channel | TEXT | 否 | — | im/email/log |
| level | TEXT | 否 | — | info/warn/critical |
| subject | TEXT | 否 | — | 告警主题（指标/队列/配置） |
| body | TEXT | 否 | — | 内容（含归因假设 + "待人工确认"） |
| acked_by | TEXT | 是 | — | 认领人（监控告警闭环） |

**为什么**：升级链的提醒要能查"发没发、谁认领"——否则 SLA 升级只是日志里的一行字。

### 2.7 文件快照与 manifest（文件侧，不进 DB）

> 正式交付的数字永远基于带 manifest 的快照（P-12）。本小节是 manifest 结构的唯一事实源，实现见 `src/riskqa/data/snapshot.py`。

**目录与文件名**

- 根目录 `data/snapshots/`；`*.csv` / `*.parquet` 进 `.gitignore`，manifest（`*.manifest.json`）可入库。
- demo 快照例外：`synthetic: true` 的 manifest 与数据文件一样不进库（仓库只留 `.gitkeep`），由 `make demo-snapshot` 现场生成；详见 `ops-runbook.md` §七。
- 数据文件：`<source>__<data_as_of>__<data_hash 前 8 位>.<ext>`；manifest 同名追加 `.manifest.json`，与数据文件同目录。
- 新数据 = 新文件；同名不同内容显式拒绝覆盖；同内容重复写幂等返回已有 manifest。

**manifest 字段（JSON，UTF-8，`sort_keys=True`）**

| 字段 | 类型 | 说明 |
|---|---|---|
| schema_version | INTEGER | manifest 结构版本，当前为 `1` |
| source | TEXT | 数据源名，只允许 `[A-Za-z0-9_.-]` |
| locator | TEXT | 相对快照根的数据文件名；禁止绝对路径与 `..`（读取时校验不逃出 root） |
| format | TEXT | 快照格式，当前只支持 `csv` |
| data_as_of | TEXT | 业务数据日期 `YYYY-MM-DD`，**权威来源**；文件名中的日期只供人读 |
| rows | INTEGER | 归一后的行数 |
| columns | ARRAY\<TEXT\> | 列顺序；读取时按它重排 |
| dtypes | OBJECT | 列名 → dtype 字符串；读取时尝试 `astype` 还原，失败即报错 |
| data_hash | TEXT | 归一后 DataFrame 的 16 位语义 hash（与 legacy `load_snapshot` 同口径，要求 RangeIndex） |
| file_hash | TEXT | 数据文件全量 sha256（64 位十六进制），防篡改/位腐 |
| created_at | TEXT | 落盘时间 `YYYY-MM-DD HH:MM:SS` 本地时间 |
| synthetic | BOOLEAN | 合成数据硬标识；缺省 `false`（旧 manifest 向后兼容）。为 `true` 时 `data_as_of` 必须是 `DEMO`，且仅允许 `RISKQA_MODE=demo` 加载 |

**双 hash 的用途**

- `file_hash`：读文件时先校验字节，证明文件未被改动。
- `data_hash`：按 `columns` 重排、按 `dtypes` 还原、`normalize_missing` 后复算，证明读回语义与写入时一致。
- 任一不符 → `SnapshotIntegrityError`；不降级、不跳过（P-14）。

**写入与读取纪律**

- 写入要求 `RangeIndex`；先 `normalize_missing`；CSV 固定 `index=False, encoding="utf-8", lineterminator="\n"`，不设 `float_format`；临时文件 + `os.replace` 原子落盘；写完回读自校验。
- 读取以 manifest 为唯一入口：缺 manifest/数据文件 → `ManifestNotFoundError`；格式不支持 → `UnsupportedFormatError`；Parquet 无引擎 → `ParquetEngineMissingError`（本批只交付 CSV，见 OPEN-QUESTIONS #18）。
- `data_as_of` 是业务日期（T+1），与 `query_log.ts` / `fact.created_at` 的墙钟时间不同源；报告两者都印，不互相推断。
- 快照含客户级敏感数据（P-02）：只落内网 `data/snapshots/`，不提交 Git；备份按 `ops-runbook.md` 整目录拷贝。
- 合成快照（`synthetic: true`）在非 demo 模式加载 → `SyntheticSnapshotError` 显式拒绝启动，不静默放行（R14 / P-12）。


## 三、★ 权限过滤的正确写法（对照示例）

### ❌ 错误写法：应用层过滤（AI 最容易写出来的版本）

```python
rows = run_sql("SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel")
rows = [r for r in rows if r.channel in user.allowed_channels]  # 错了！
```
**错在哪**：聚合已经在全量数据上算完——用户虽然只"看到"过滤后的行，但**分母里已经含了他不该看的渠道**。风控场景这是越权 + 数字错误双重事故。

### ✅ 正确写法：SQL 层注入（引擎唯一允许的形态）

```python
safe_sql = inject_row_filter(
    sql, table="fact_application",
    condition=user.channel_condition)  # WHERE channel IN ('A','B')
rows = run_sql(safe_sql)                # 先收窄，后聚合
```
**纪律**：行级权限条件由 `orchestration` 在**执行前**注入（V2 `inject_row_filter` 已实现）；外壳传身份，引擎决定可见范围——外壳永远拿不到越权数据（spec US-07）。

## 四、迁移与容量

- **建表**：`store/schema.sql` 一条 `CREATE TABLE IF NOT EXISTS` × 6；无 migration 框架（L3 单机单写，schema 变更走 ADR）。
- **容量**：query_log 按 1 万条/日 → 365 万行/年，SQLite 无压力；`data/ops.db` 按 50MB/年 估；保留期 Delete 走 `ts < now-365d` 的定时任务（ops-runbook A-7）。
- **备份**：`data/` 整目录 + `config/`（Git）即全量；恢复 = 停服务 → 拷回 → 起服务。
