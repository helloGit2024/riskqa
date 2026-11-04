---
description: 部署与运维专项规则：内网单机部署、备份恢复、保留期清理、告警通道。改部署/配置/ops-runbook 时自动生效。
globs: Makefile, requirements.txt, docs/ops-runbook.md, src/riskqa/api/**, .env.example
alwaysApply: false
---

# 部署与运维规则（ops）

> 按需加载。冲突时以 `AGENTS.md` 为准。

## 1 · 部署形态（锁定）

- **内网单机**：不上 K8s、不上容器编排（constraints §五：用户不懂 DBA/运维）。
- 进程管理：`systemd --user` 或 `nohup` + 日志文件；API 端口只听 `127.0.0.1`（不绑 0.0.0.0——无公网暴露，P-02）。
- 三份配置：`.env`（密钥，gitignore）、`config/*.yaml`（口径/治理，Git）、`data/`（快照/ops.db，备份）。

## 2 · 备份与恢复（RPO 24h 可接受）

- 每日一次：`data/` 整目录拷到内网备份位置 + `config/` 已进 Git（无需额外备份）。
- 恢复 = 停服务 → 拷回 `data/` → 起服务 → `make health` 验证三态。
- **ops.db 损坏不影响已交付数字**——数字的出生证明在 Git 管的 YAML + 快照 manifest（ADR-0003 代价节）。

## 3 · 保留期清理（唯一 DELETE 路径）

- `query_log` 中 `ts < now - 365d` 的记录，每月 1 日定时清理，清理动作记审计（P-12/P-14）。
- 清理前检查：热度窗口（30 天）远小于保留期（365 天）——窗口内数据永远够用；护栏会拒绝 `window > retention` 的配置。

## 4 · 告警通道与升级链

- 通道优先级：IM（企微/飞书 webhook）→ 邮件 → 日志；webhook 地址进 `.env`，不进代码（P-01）。
- 告警分三类：① 指标超阈值（监控归因场景，带"待人工确认"状态）；② 评审队列积压（>SLA 2×）；③ 系统态异常（DB/快照/LLM 网关，health 三态）。
- 每条告警必须可认领（`alert.acked_by`）——发出去没人认领 = 没发。

## 5 · 故障处置总原则

1. LLM 网关挂了 → 自动降级 DegradedLLM（能拒答不编造），问数服务不中断；
2. 快照缺失/损坏 → 问数服务拒服并告警（不许静默用旧快照糊弄）；
3. ops.db 锁/损坏 → 停写保读，恢复备份；
4. **任何故障都不允许"临时关掉校验闸保交付"**——闸门不可配置关闭（security §七-8）。

## 6 · Reject List

- ❌ 绑定 0.0.0.0 或开防火墙端口对外
- ❌ 在服务器上手改 `config/*.yaml` 不走 Git（口径变更必须留痕，P-14/P-15）
- ❌ 为清理"省空间"删保留期内 raw log
- ❌ 告警只写日志不发通道
