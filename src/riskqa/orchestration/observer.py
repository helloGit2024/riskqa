"""观测层：trace / 成本 / 审计日志（监管要求全程留痕）。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..llm.fake import FakeLLM


@dataclass
class AuditEntry:
    ts: str
    actor: str  # 谁发起的
    question: str
    route: str
    sql: str
    review_level: str
    human_action: str  # accept / edit / response / auto
    model: str
    ai_disclosed: bool


class Observer:
    """V2 新增：没有度量就无法优化，监管也要求可追溯"""

    def __init__(self):
        self.trace: list[dict] = []
        self.audit: list[AuditEntry] = []
        self.cost_tokens = 0

    def log(self, node: str, **kw):
        self.trace.append({"node": node, "t": round(time.time(), 3), **kw})

    def audit_append(self, **kw):
        self.audit.append(
            AuditEntry(ts=time.strftime("%Y-%m-%d %H:%M:%S"), ai_disclosed=True, **kw)
        )

    def cost(self, llm: FakeLLM):
        self.cost_tokens += llm.tokens_used
