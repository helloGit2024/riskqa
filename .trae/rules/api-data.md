---
description: 接口层与数据层（FastAPI/SQLite/快照/MCP）的硬要求。改 api/mcp/store/data 任何模块前必读。
globs: src/riskqa/api/**, src/riskqa/mcp/**, src/riskqa/store/**, src/riskqa/data/**, docs/openapi.yaml, docs/data-model.md
alwaysApply: false
---

# API 与数据层规则（api-data）

> 按需加载。冲突时以 `AGENTS.md` 与 `docs/openapi.yaml` 为准。

## 1 · 接口契约纪律

- `docs/openapi.yaml` 是字段名的唯一事实来源；改字段 = 改 yaml 先行，代码后随。
- 错误码是字符串常量（`E_UNREGISTERED_METRIC` 式），不用数字码；新错误码先进 api-contract §3.3 全集表。
- 身份只来自 `X-RiskQA-Token`（P-10）；任何端点不接受 body 自报身份。
- MCP 工具 schema 从 openapi.yaml 的 components 生成，**不手写第二份**（防双出口漂移，ADR-0005）。

## 2 · SQLite 纪律

- 表结构唯一来源 `docs/data-model.md`；schema 变更 = 先改文档 + ADR，再改 `store/schema.sql`。
- `query_log` 只 INSERT（P-12）；`fact` 落库后不可变；`audit_entry` 旁路写入（业务异常路径也要留痕）。
- 保留期清理（`ts < now-365d`）是唯一 DELETE 路径，走定时任务并记审计。
- 连接：`sqlite3.connect(path, timeout=10)`；写操作单事务；**运营数据写不进语义层相关表**（口径只在 YAML，P-15）。

## 3 · 快照纪律（ADR-0006）

- 加载即归一（`''` / `'unknown'` / `-999` → NaN，只此一次）+ manifest（source/locator/data_as_of/sha256）。
- 正式数字必须带 `snapshot_digest`；直连库只允许探索性看数，且结果须标注 `live-read`。
- 快照文件只进 `data/snapshots/`，gitignore；manifest 进版本库。

## 4 · 行级权限（最容易写错的一处）

- 权限条件在 SQL 执行前注入（WHERE），**禁止应用层过滤**——聚合后再过滤 = 分母含越权数据。
- 越权返回空结果（非报错）——报错泄露"记录存在"。
- 外壳传身份，引擎判可见；外壳永远拿不到越权数据（spec US-07）。

## 5 · Reject List

- ❌ 为了"方便联调"临时关掉认证或权限注入
- ❌ 在响应体里回传全量查询结果（digest + fid 即可）
- ❌ 手写 MCP 工具参数 schema
- ❌ 用 JSONL/CSV 替代 SQLite 存运营数据（热度统计要靠 SQL）
