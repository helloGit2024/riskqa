# 质量门禁（quality-gates.md）

> **本文件是"门禁编号"的唯一来源。** 编号一旦分配不再复用，删除的编号留空不回填。
> 上游：`docs/spec.md` 第三节（验收标准）、`docs/security.md` 第七节（SG-01）。
> 下游：`docs/tasks.md` 每个任务的"对应验收标准"、`docs/releases.md` 各版本退出门禁。

## 〇、编号总览（先读这一节）

| 编号 | 门禁 | 起效版本 | 门槛级别 |
|---|---|---|---|
| QG-01 | 单元/场景测试全绿 | V4.0 | 硬 |
| QG-02 | 行为等价回归（17 场景 vs legacy） | V4.0 | 硬 |
| QG-03 | 语义层与治理 YAML 校验 | V4.0 | 硬 |
| QG-04 | 密钥与敏感信息扫描 | V4.0 | 硬 |
| QG-05 | 代码风格检查（ruff） | V4.0 | 硬 |
| QG-06 | 文档自检 0 ERROR + 阻塞项 ≤3 | 全程（今天就可跑） | 硬 |
| QG-07 | 黄金题集 ≥95% + 拒答类 100% | V4.1 | 硬 |
| QG-08 | 安全测试 SG-01 八项 + 越权 0 通过 | V4.1 | 硬 |
| QG-09 | 治理链路断言（压缩比/冲突/误晋升） | V4.2 | 硬 |

> 编号分配的既成事实：`releases.md` V4.0 引用"QG-01/02/03 先行"；`tasks.md` T-4.0.7 引用"CI 接 QG-01/03/04"；`TRAE-启动手册.md` 引用"docs-check 0 ERROR（见 QG-06）"。改编号 = 改三处引用，属于高风险动作。

---

## 一、硬门禁（不通过 = 禁止合并到 main）

| # | 门禁 | 怎么跑 | 阈值 | 不过时的含义 |
|---|---|---|---|---|
| QG-01 | 单元/场景测试全绿 | `make test` | 100% 通过，0 skip | 有行为被改坏或新代码没测 |
| QG-02 | 行为等价回归 | `make test`（`tests/scenario/` 17 场景）+ legacy 输出留档比对 | 17/17 一致 | V4.0 迁移改坏了逻辑——本项目最大的返工风险 |
| QG-03 | 语义层与治理 YAML 校验 | `make semantic-check` + `make governance-check` | 5 指标三字段（owner/signed_at/changelog）齐全；护栏四条全过 | 无主口径入库 / 阈值穿底（P-05/P-14） |
| QG-04 | 密钥与敏感信息扫描 | `make secret-scan` | 0 命中 | 违反 P-01，一票否决 |
| QG-05 | 代码风格检查 | `make lint` | 0 error（warning 需在合并说明里解释） | 风格腐烂，AI 生成代码的典型信号 |
| QG-06 | 文档自检 + 待确认项收敛 | `make docs-check` + `make openq` | 0 ERROR；阻塞项 ≤3 | 文档集自身坏了，或需求没谈清楚 |
| QG-07 | 黄金题集回归 | `make eval` | 总通过率 ≥95%；**拒答类 100%（无容差）** | 问数质量不达标（spec §3.2） |
| QG-08 | 安全测试清单 | SG-01 八项（security §七） | 八项全过；**越权 0 通过** | 安全验收不过（spec §3.5） |
| QG-09 | 治理链路断言 | `make test`（`tests/governance/`） | 压缩比 ≥5×；口径冲突精确检出 + 零误报；误晋升率 0；三类失真全拦 | 持续运营机制失效（spec §3.2） |

**三条解释**：

1. **QG-02 为什么单独列**：V4.0 的本质是"搬运 + 拆包，不改逻辑"。行为等价是这个版本唯一的地基本证，所以它不并入 QG-01，而要求逐场景输出留档（T-4.0.1/T-4.0.10）。
2. **QG-07 的拒答类没有容差**：一题该拒未拒 = 编造数字流出，直接违反 P-03/P-06/P-07，与"总体 95%"是两套标准（evals/README §三）。
3. **QG-06 今天就能跑**：`make docs-check` / `make openq` 不依赖任何代码，是文档集交付自带的门禁（TRAE-启动手册 §三）。

---

## 二、软门禁（不通过 = 必须在合并说明里解释）

| # | 门禁 | 阈值 | 不通过时怎么办 |
|---|---|---|---|
| S-01 | 测试覆盖率 | 新增 `calc/` `governance/` 代码行覆盖 ≥80% | 说明为什么这块不测（通常：纯编排胶水代码） |
| S-02 | 性能采样 | spec §3.4 四项：快路 P95<2s（1000 次采样）/ 慢路 <60s / 报告 <5min / 归并 <5min | 记录当前值 + 差距原因；**版本退出评审时升为必查** |
| S-03 | 场景数守恒 | 17 个场景（V2 九 + V3 八）只增不减 | 减少场景必须补 ADR + 用户签字——删测试是头号作弊手法 |

---

## 三、分版本的门禁强度

| 版本 | 必须满足的硬门禁 | 说明 |
|---|---|---|
| V4.0 | QG-01—06 | 行为等价是主戏（QG-02）；治理/评估/安全门禁未到版本 |
| V4.1 | QG-01—08 | QG-07/08 随问数闭环生效；黄金题集初始 20 题 |
| V4.2 | QG-01—09 全量 | QG-09 治理链路断言随持续运营上线 |
| V4.3 | 全量 + 扩容 | 黄金题集 20→50 题仍须 ≥95%；judge 人工校准加码 |

> 每一版本的完整退出条件在 `releases.md`（✅做什么/❌不做什么/✓退出门禁三件套），本表只回答"哪些门禁算数"。

---

## 四、CI 流水线编排

**现实约束**：内网 Git 服务形态未确认（无公网 CI 可用）。落地上分两步，T-4.0.7 当天实跑后生效。

### 4.1 第一步：pre-commit（本地闸，今天就能装）

```yaml
# .pre-commit-config.yaml（T-4.0.7 落地；make target 自带"未建成"守卫，不会静默失败）
repos:
  - repo: local
    hooks:
      - id: docs-check
        name: 文档自检（QG-06）
        entry: make docs-check
        language: system
        pass_filenames: false
      - id: secret-scan
        name: 密钥扫描（QG-04）
        entry: make secret-scan
        language: system
        pass_filenames: false
      - id: semantic-check
        name: 语义层校验（QG-03）
        entry: make semantic-check
        language: system
        pass_filenames: false
```

### 4.2 第二步：内网 Git webhook CI（示意，等服务确认）

```yaml
# .gitlab-ci.yml 或内网等效物（示意——AI 可直接实现）
stages: [check, test]
variables:
  PY: "python3"
docs-check:      # QG-06
  script: ["make docs-check", "make openq"]
secret-scan:     # QG-04
  script: ["make secret-scan"]
lint:            # QG-05
  script: ["make lint"]
test:            # QG-01/02
  script: ["make test"]
semantic-check:  # QG-03
  script: ["make semantic-check", "make governance-check"]
```

> **顺序纪律**：QG-04/05/06 是快闸（秒级），先跑；QG-01/02 慢闸（分钟级）后跑。CI 红一次要**故意用失败提交验证门禁会拦**（T-4.0.7 验收标准）——没拦过的门禁等于没有。

---

## 五、门禁与"完成定义"的关系

**一个任务算"完成"，必须同时满足三件事**：

1. 对应 `spec.md` 第三节的验收标准全部满足（且能演示怎么验证的）；
2. 该版本要求的硬门禁全绿（本文件 §三）；
3. `docs/tasks.md` 里该任务的状态已更新为 ✅ + 日期。

> ⚠️ **绝对禁止**：为了通过门禁而放宽阈值、删测试、改评估题。这条属于永久红线，已写进 `AGENTS.md` 第五节禁止清单与 `evals/README` 第八节。**这条纪律无例外、无"临时"、无"就这一次"。**

---

## 六、当前状态（每次迭代后更新）

| 门禁 | 当前 | 更新日期 |
|---|---|---|
| QG-06 | ✅ 首跑 0 ERROR（2026-11-01，带 pyyaml 的 Python 实跑：2 个 YAML 全部解析通过、阻塞项 0、无 ⚙️ 残留；系统 python3 缺 pyyaml 时会跳过 YAML 检查并报 1 个 WARN，装 requirements 后消失） | 2026-11-01 |
| QG-01/02/03/04/05 | 未首跑（等 T-4.0.7，代码落地当天实跑；守卫已实跑验证：`make test`/`semantic-check`/`secret-scan` 均正确指路任务编号） | 2026-11-01 |
| QG-07/08/09 | 未到版本（V4.1/V4.1/V4.2 生效；`make eval` 守卫已实跑，指路 T-4.1.8） | — |
