# ADR-0005：MCP Server 是引擎对外出口之一（外壳可插拔）

> 状态：已接受（2026-11-01）｜ 影响面：releases V4.2、api-contract、architecture §一

## 一、背景

框架选型文档结论："引擎不动，外壳可换"——把问数引擎做成通用 agent 可调用的上下文层。WrenAI 2026-05 转型（自托管聊天应用 → agent 无关的 context layer + CLI/SDK）从产品侧验证了该方向。需要决定：引擎对外只出 REST API，还是 REST + MCP 双出口。

## 二、备选方案

| 方案 | 优点 | 缺点 |
|---|---|---|
| A. 只出 REST API | 一个契约、好测试 | Trae/Chat2DB 等外壳接不了（要自己写客户端） |
| B. 只出 MCP | 外壳零开发接入 | 脚本/批处理场景不方便；MCP 生态外的人用不了 |
| C. REST + MCP 双出口（本决策） | 外壳即插即用 + 传统集成都能覆盖 | 两套 schema 要同步（同一 OpenAPI 生成，防漂移） |
| D. 什么都不做出（继续 import 包） | 零工作 | 每个外壳都要装 Python 环境；Trae 用不了 |

## 三、决策

选择 **C**：V4.1 先冻 REST API（openapi.yaml）；V4.2 加 MCP Server，5 工具（ask_metric / explore / submit_review / get_evidence / list_governance），stdio + SSE 双通道；两套契约同源生成。

## 四、理由

三个真实外壳需求已明确：Trae（分析师自用）、Chat2DB（数据团队）、未来可能的 Dify（业务壳）——全是 MCP 原生消费者；同时批处理/CI 用 REST 更顺。双出口共享同一引擎与权限层，不增加口径面。

## 五、代价（必填）

- MCP 与 REST 的字段漂移风险（缓解：MCP 工具 schema 从 openapi.yaml 的 schema 块生成，单源）。
- 多一个传输层要测（联调用例进 quality-gates）。
- 行级权限必须在工具内注入——外壳传身份、引擎判可见，这条不成立则整个方案作废（spec US-07）。

## 六、复核条件

① 实际只有一种外壳被使用（可砍另一个出口减维护）；② MCP 协议破坏性变更；③ 组织统一用 Dify 等平台且不允许外部 MCP。

## 七、不懂技术的人只需确认哪一点

**"以后不管用什么 AI 工具（Trae、Chat2DB、别的），问的都是同一个引擎、同一套口径、同一套权限"**——这是否是你要的。

## 八、这个决定被写进哪些地方

`releases.md` V4.2；`api-contract.md` §六；`architecture.md` §一边界；`tasks.md` T-4.2.6；`.trae/rules/api-data.md`。
