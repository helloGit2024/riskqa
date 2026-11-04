"""治理层：评审升级链（V3 版 tick）+ 慢路人审分级（V2 版 classify_review）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .config import ReviewRule


@dataclass
class ReviewState:
    cid: str
    status: str = "pending_review"  # pending / reminded / overdue / shelved / done
    entered_at: str = "2026-10-01"
    history: list[str] = field(default_factory=list)


def tick(state: ReviewState, now: str, rule: ReviewRule) -> ReviewState:
    """超时推进：提醒 → 升级 → 组织搁置（shelved ≠ rejected：是没人管，不是口径错）"""
    waited_h = (
        datetime.strptime(now, "%Y-%m-%d %H:%M")
        - datetime.strptime(state.entered_at + " 00:00", "%Y-%m-%d %H:%M")
    ).total_seconds() / 3600
    if state.status == "done":
        return state
    if waited_h >= rule.shelve_after_sla * rule.sla_hours:
        state.status = "shelved"
    elif waited_h >= rule.escalate_after_sla * rule.sla_hours:
        state.status = "overdue"
    elif waited_h >= rule.sla_hours:
        state.status = "reminded"
    state.history.append(f"{now} → {state.status}")
    return state


def classify_review(sql: str, role: str) -> str:
    """人审分级——V2 新增。一刀切人审会杀死系统，按风险定级：
    auto   = 只读 + limit + 白名单单表 → 免审（记录留痕）
    sample = 跨表 / 聚合 / 分区全扫   → 抽检（demo 中按概率升级为 must）
    must   = 无 limit / 涉及敏感列 / 导出意图 → 必审（interrupt）
    """
    if not re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
        return "must"
    if re.search(r"\bJOIN\b", sql, re.IGNORECASE):
        return "must"
    if role != "risk_admin":
        return "sample"
    return "auto"
