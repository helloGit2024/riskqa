# ADR-0002：LangGraph 作为编排运行时，不迁移到 deepagents / Claude Agent SDK 运行时

> 状态：已接受（2026-11-01）｜ 影响面：architecture §二、AGENTS P-xx、releases V4.0

## 一、背景

框架选型文档（2026-11-01）的结论：通用 agent harness 覆盖外壳层与部分编排层，不覆盖引擎与治理层。需要决定编排层的运行时：继续 LangGraph，还是迁移到 LangChain 官方的 deepagents（同为 LangGraph 之上），或用 Claude Agent SDK 自建。

## 二、备选方案

| 方案 | 优点 | 缺点 |
|---|---|---|
| A. 继续 LangGraph（V2 实测 1.2.16） | 慢路固定图/interrupt 人审/checkpoint 已实现；零迁移 | 规划/子agent/上下文管理要自己拼 |
| B. 迁移 deepagents | 白拿规划/文件系统/子agent/中间件 | 设计哲学是"长任务自主探索"，与"路径事先画得出来"冲突；迁移=重写编排层 |
| C. Claude Agent SDK 自建 harness | 官方零件全 | 闭源依赖 + 模型走 Anthropic API（合规红线 P-02）；等于重写 |
| D. 无编排，主循环手写（V1 式） | 最简单 | 慢路修正循环/人审中断无处挂 |

## 三、决策

选择 **A**：编排层继续 LangGraph；deepagents 仅作为 V4.3 归因探针的可选外壳（其子agent 模式经 MCP 调用引擎，不进生产主链路）。

## 四、理由

V2 已用 LangGraph 实现慢路图 + interrupt 人审 + InMemorySaver，9 场景实测通过；风控问数的形态是"确定性管线 + 窄点 LLM 决策"，不是"开放式长任务"——deepagents 的优势场景（自主规划、并行研究）在本项目是少数场景（归因探针），不值得为核心链路换轨。

## 五、代价（必填）

- 规划、上下文压缩等能力需自建或放弃（评估后：问数链路短，暂不需要）。
- LangGraph API 升级风险自担（锁 1.2.x 小版本）。

## 六、复核条件

① deepagents 中间件管线成熟到可独立摘取（只借零件不换轨时）；② 归因探针 PoC 证明子agent 模式收益 > 接入成本；③ LangGraph 停止维护或 breaking change 频繁。

## 七、不懂技术的人只需确认哪一点

**引擎不搬进任何"通用 AI 框架"里跑**——数字生产留在自己控制的结构里，框架只当外壳。是否认可。

## 八、这个决定被写进哪些地方

`architecture.md` §二技术栈；`releases.md` V4.3（deepagents PoC 列为可选）；`AGENTS.md` 技术栈锁定；`.trae/rules/project_rules.md` 技术栈节。
