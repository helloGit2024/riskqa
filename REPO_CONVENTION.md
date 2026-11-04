# REPO_CONVENTION.md — 仓库约定

> 目录结构的**唯一来源是本文件**；`AGENTS.md` 与 `architecture.md` 只放指针。

## 一、命名约定

| 对象 | 约定 | 示例 |
|---|---|---|
| 文件 / 目录 | 全小写 + 下划线；文档目录 `docs/`；规则目录 `.trae/rules/` | `semantic_view.yaml`、`nl2sql-core.md` |
| Python 模块 | 包 `src/riskqa/`，子包按层名单字 | `riskqa.semantic`、`riskqa.orchestration` |
| 变量 / 函数 | snake_case；私有前缀单下划线 | `caliber_fingerprint()`、`_load_memory()` |
| 类 | PascalCase；异常类以 Error 结尾 | `SemanticLayer`、`UnregisteredMetricError` |
| 数据库表 | snake_case 单数 | `query_log`、`review_record` |
| fact_id / qid / rid | `F0001` / `Q0001` / `R0001`（4 位起，零填充） | — |
| 分支 | C0 无分支（见下） | — |
| 提交信息 | `<类型>: <一句话>`，类型 ∈ feat/fix/refactor/test/docs/chore | `feat: 快路 ask_metric 接入 alias 索引` |

## 二、分支策略（C0：就我一个人 + AI）

- 直接在 `main` 上小步提交，**不建分支**。单人建分支会攒长期不合并的分支，合并冲突比省下的时间多。
- 提交粒度：一个任务（tasks.md 的 T-x.x）一提交，最大不超过一个文件的独立变更。
- 每天收工前 `git push`（本地仓库 + 定期推内网 Git 服务，双保险）。

## 三、目录结构（实测为准，V4.0 建成后的目标态）

```
风控问数系统/
├── src/riskqa/
│   ├── __init__.py
│   ├── semantic/      # M1：YAML 加载、指标卡、alias 索引、FC enum 生成
│   ├── data/          # M2：快照加载、manifest 血缘、数据源注册
│   ├── calc/          # M3：纯函数指标库 + recompute_all 独立重算
│   ├── facts/         # M4：FactStore
│   ├── tools/         # M5：FC schema、dispatch、pre/post 闸
│   ├── verify/        # M6：三重校验闸、回退模板
│   ├── orchestration/ # M7：快路、慢路图、人审状态机
│   ├── governance/    # V3：签名/热度/指纹/评审材料/晋升/升级链
│   ├── llm/           # 网关、ModelRouter、FakeLLM、DegradedLLM
│   ├── api/           # FastAPI 应用（openapi.yaml 的实现）
│   ├── mcp/           # MCP Server（5 工具）
│   └── store/         # SQLite：schema.sql + 六表 DAO
├── config/
│   ├── semantic_view.yaml   # 口径宪法（P-15 唯一事实源）
│   └── governance.yaml      # 治理参数三层
├── data/
│   ├── snapshots/     # CSV/Parquet + manifest（12 个月滚动）
│   └── ops.db         # SQLite 运营数据（gitignore，只进备份）
├── tests/             # pytest：unit/（计算/闸门）+ scenario/（V2/V3 场景）+ api/
├── evals/             # 黄金题集与评估
├── docs/              # 设计文档（本套）
├── legacy/            # 原四个问数Agent_*.py 只读存档（勿改勿运行）
├── .trae/rules/      # Trae 项目规则
├── Makefile
├── requirements.txt
└── README.md
```

## 四、什么进版本库

| 进 | 不进 |
|---|---|
| 全部 `src/` `config/` `tests/` `evals/` `docs/` `.trae/` `Makefile` `requirements.txt` | `data/ops.db`、`data/snapshots/*.csv`（manifest 进，数据不进）、`.env`、`__pycache__/`、`.venv/` |

## 五、代码风格

- 行宽 100；类型注解全覆盖（`from __future__ import annotations`）；docstring 一句职责。
- 计算层（`calc/`）函数签名统一 `fn(df: pd.DataFrame, group_by: str | None = None) -> pd.DataFrame | float`。
- 禁 `print` 调试（用 `logging`，测试用 `caplog`）；禁裸 `except:`。

## 六、AI 协作固定动作

1. 动手前读 `.trae/rules/project_rules.md` 的场景查表（哪类改动读哪份文档）。
2. 每个任务的验收标准在 `docs/tasks.md`；改完先跑 `make test` 再提交。
3. 发现文档与代码不一致：**先改代码还是先改文档，看 `AGENTS.md` 〇-1**（宪法优先），不许自行其是。
4. 代码注释里出现"待实现/要等 T-x" → 必须在 `tasks.md` 或 `OPEN-QUESTIONS.md` 有对应条目（动词类检查会捞）。

## 七、与用户级规则的关系

用户级规则（~/.workbuddy/ 下的个人偏好）与本项目规则冲突时：**本项目规则优先**（AGENTS.md 〇-3）。特别是：本项目禁裸数字、禁 LLM 算数——用户级规则若有冲突表述，以本套文档为准。
