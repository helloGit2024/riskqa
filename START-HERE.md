# START-HERE.md · 10 分钟上手（通用，跨平台不改）

> 平台特有内容（规则文件放哪、首日话术、该平台的坑）在 `TRAE-启动手册.md`。

---

## 一、这是什么

一套**让 AI 能直接开工**的前置文档 + 一套**分四版实现**的风控问数系统工程计划。它把"不能靠 AI 猜"的东西先钉死：做什么/不做什么、技术栈、表结构、接口字段名、硬规则、验收门禁。

档位 **L3**（35 份）· 协作档 **C0**（你一个人 + AI）。

## 二、现在做什么（按顺序）

| 顺序 | 动作 | 花多久 | 通过标准 |
|---|---|---|---|
| 1 | 读 `docs/constraints.md` 与 `docs/spec.md` 第三节 | 15 分钟 | 你能说清"这个版本要做什么、不做什么" |
| 2 | 看 `OPEN-QUESTIONS.md`，处理阻塞项（2 条，都有默认路径） | 10 分钟 | 阻塞项有结论或明确按默认走 |
| 3 | 看 `TRAE-启动手册.md`，确认规则文件位置 | 10 分钟 | `.trae/rules/` 5 份在位 |
| 4 | 做**握手验收**（首日序列 P1） | 5 分钟 | AI 能准确说出"本版本不做什么" |
| 5 | 从 `docs/tasks.md` 的 T-4.0.1 开始干活 | — | 按第五节的循环走 |

## 三、五个交付批次与验收方式（本文档集的生成记录）

| 批次 | 内容 | 验收 |
|---|---|---|
| 批 1 事实基座 | constraints / spec / releases / glossary / assumptions / 00-index / OPEN-QUESTIONS | **读**——逐条确认"做什么/不做什么"，过假设台账 |
| 批 2 技术骨架 | architecture / data-model / api-contract / openapi / adr×6 / security | **读**——确认技术栈、表、字段名 |
| 批 3 让 AI 接管 | AGENTS / REPO_CONVENTION / rules×5 / Makefile / README / 本文件 / 启动手册 | **跑**——握手（唯一能确认 AI 真读懂了的时机） |
| 批 4 干活与验收 | tasks / quality-gates / risk-register / evals×4 | **读 + 四视角对抗评审** |
| 批 5 上线迭代 | ops-runbook / experiments | 读 |

## 四、每天开工收工的标准循环

**开工**（30 秒）：`git pull` → 看 `docs/tasks.md` 当前任务 → 对 AI 说"按 T-x.x 干，先复述计划"。
**收工**（2 分钟）：`make test`（V4.0 后）→ 交代"改了哪些文件/对应哪条验收/有没有放宽标准" → 提交（`<类型>: <一句话>`）→ 有阻塞写进 `OPEN-QUESTIONS.md`。

## 五、遇到问题查哪里

| 症状 | 翻这里 |
|---|---|
| 不知道这事定过没有 | `OPEN-QUESTIONS.md` → `docs/adr/` |
| 数字对不上 | `docs/data-model.md` §三（权限过滤）+ `evals/attribution.md` |
| 模型行为怪异 | `.trae/rules/nl2sql-core.md` → `AGENTS.md` P-03..P-14 |
| 部署/告警出事 | `docs/ops-runbook.md` |
| 文档互相矛盾 | `AGENTS.md` 〇-1：宪法优先，改另一份 |

## 六、这个版本覆盖不了 100%

用几轮之后，回来反馈"哪几个问题问得不对、哪条规则判错"——文档集随项目一起演进（假设台账 V-01..V-04 是第一批待验证项）。
