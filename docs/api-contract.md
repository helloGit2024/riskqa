# 接口契约（api-contract.md）

> 上游：`architecture.md`。机器可读定义在 `openapi.yaml`，**两者冲突时以 openapi.yaml 为准**。

## 一、为什么必须先冻结接口

本项目虽无前端（C0 单开发），但有两拨"调用方"：**你自己**（CLI/测试）与**外壳**（Trae / Chat2DB / MCP 客户端）。字段名不冻结，MCP 工具 schema 与 REST 响应会各写各的，联调时全是错。V4.1 的 API 冻结是 V4.2 MCP 化的前置门（releases §六）。

## 二、契约的三条纪律

1. **`openapi.yaml` 是唯一事实来源**。本文件是它的说明。
2. **字段名一旦冻结不许改**，要改必须出 `/v2/...` 或走弃用流程（响应头加 `Deprecation`）。
3. **字段名写全**，不用"等"省略；错误码是字符串常量，自解释。

## 三、通用约定

### 3.1 路径与命名
`/api/v1/<资源复数>`；资源复数；动词进方法。snake_case 全库统一。

### 3.2 认证
内网 Token：请求头 `X-RiskQA-Token: <token>`，token 与角色绑定（analyst / owner / admin）。角色决定：可用端点 + 行级权限范围（引擎按角色注入，见 data-model §三）。**外壳传身份，引擎判可见**——这是铁律，任何端点都不接受"以 body 参数形式自报身份"。

### 3.3 统一错误格式
```json
{ "error": { "code": "E_STRING_CONST", "message": "给人看的一句话（含拒绝原因）" } }
```

**错误码全集**（openapi.yaml 的 components/responses 逐一定义）：

| code | 含义 | HTTP |
|---|---|---|
| `E_UNAUTHORIZED` | token 缺失/失效/角色不足 | 401 |
| `E_UNREGISTERED_METRIC` | 指标未登记（P-04，不猜不填） | 400 |
| `E_UNSIGNED_METRIC` | 指标未 Owner 签字（P-05） | 400 |
| `E_CALC_NOT_REGISTERED` | 纯函数未注册，快路拒服（P-09） | 400 |
| `E_DIM_NOT_ALLOWED` | 维度不在该指标允许列表 | 400 |
| `E_BARE_NUMBER` | 叙事层出现裸数字（校验闸检查 1） | 422 |
| `E_FABRICATED_REF` | 引用不存在的 fact_id（检查 2） | 422 |
| `E_RECOMPUTE_MISMATCH` | 独立重算不一致（检查 3） | 422 |
| `E_SQL_REJECTED` | SQL 三闸拒绝（白名单/LIMIT/注入特征） | 400 |
| `E_ROW_FILTER_DENIED` | 行级权限注入后无可执行范围 | 403 |
| `E_REVIEW_REQUIRED` | 必审内容，未确认不可引用 | 409 |
| `E_SLA_TIMEOUT` | 慢路熔断（60s） | 504 |
| `E_GOVERNANCE_INVALID` | 治理配置护栏拒绝（P-14） | 400 |

### 3.4 分页约定
`limit`（默认 50，上限 200）+ `offset`；响应带 `total`。列表端点统一。

## 四、接口清单（共 8 个，v1）

| # | 方法 | 路径 | 作用 | 角色 |
|---|---|---|---|---|
| 1 | POST | `/api/v1/ask` | 问数入口：自动路由快慢路，返回数字+fact_id+口径 | analyst+ |
| 2 | POST | `/api/v1/explore` | 强制慢路探查（新签名/不确定时显式使用） | analyst+ |
| 3 | GET | `/api/v1/facts/{fid}` | 取事实详情（值/口径/来源/证据） | analyst+ |
| 4 | GET | `/api/v1/evidence/{qid}` | 取证据快照（SQL+参数+版本+签字链） | analyst+ |
| 5 | POST | `/api/v1/reviews` | 提交人审（慢路结果/归因结论） | analyst+ |
| 6 | POST | `/api/v1/reviews/{rid}/decision` | Owner 裁决（approve/reject/shelve+理由） | owner |
| 7 | GET | `/api/v1/governance/candidates` | 晋升候选列表（热度+冲突标注） | owner+ |
| 8 | GET | `/api/v1/health` | 健康检查（DB/快照/LLM 网关三态） | 无（内网探活） |

> **注**：`/v1/governance/conflicts`（口径冲突清单）在 V4.2 随治理链路上线前不进本契约——接口数以此为唯一来源，其他地方引用"8 个"。

## 五、核心接口详解

### 5.1 POST /api/v1/ask

请求：
```json
{
  "question": "各渠道 FPD30 怎么样",
  "time_range": "all",
  "caller": { "user": "zhangsan", "dept": "risk", "role": "analyst" }
}
```
响应（快路命中，200）：
```json
{
  "route": "fast",
  "metric": "fpd30_rate",
  "signature": "fpd30_rate|channel||all",
  "answer_text": "整体 FPD30 为 {{F0001}}，按渠道拆解见 facts。",
  "facts": [
    { "fid": "F0001", "value": 0.4000, "unit": "ratio", "segment": "" },
    { "fid": "F0002", "value": 0.5000, "unit": "ratio", "segment": "channel=渠道A" }
  ],
  "caliber": { "desc": "首期逾期率：放款客户中首期 DPD30+ 的占比", "owner": "风控策略组", "signed_at": "2026-09-30" },
  "review_level": "none",
  "ai_disclosure": "本回答由 AI 辅助生成，数字来自已签字口径的确定性计算"
}
```
响应（未命中 → 慢路必审，202 + E_REVIEW_REQUIRED 语义）：返回 `review_id` 与 `state: pending`——**结果在 Owner 确认前不可被引用**。
失败：未登记指标 → `E_UNREGISTERED_METRIC` + message 说明"已记录为候选，走慢路提名"。

### 5.2 POST /api/v1/explore

请求：`{ "question": "...", "max_fix_rounds": 2 }`。强制慢路：LLM 生成 SQL → 三闸 → 执行 → 交叉验证 → raw log 落库 → 人审分级。响应含 `sql`、`verdict`（快慢两侧数字 + 差异说明）、`review`。

### 5.3 POST /api/v1/reviews/{rid}/decision（Owner 专属）

请求：`{ "decision": "approve", "reason": "口径确认：分母为放款申请数", "signer": "wangwu" }`。
**硬规则**：approve 一个 promotion 候选时，服务端必须同事务完成三件事（P-13）：写 semantic_view.yaml、固化 evidence 快照、注册纯函数——任何一步失败整体回滚，不许"签了字但没生效"。

## 六、并行开工准备（C1+ 必填，本项目 C0 —— 留空声明）

本项目协作档 C0（单人+AI），无并行轨道。接口冻结仍然有效：它是 V4.1 与 V4.2（MCP）之间的契约，`tasks.md` 中标了依赖点。

## 七、冻结检查清单（V4.1 退出门禁用）

- [ ] openapi.yaml 无 `⚙️` 残留、YAML 可解析、`$ref` 无悬空
- [ ] 错误码全集（§3.3）在 components/responses 逐一定义
- [ ] 8 个端点全部有请求/响应示例
- [ ] 角色 × 端点矩阵在 security.md 与本文一致
- [ ] 字段名全局 snake_case，无同义字段（如 user/username 并存）
