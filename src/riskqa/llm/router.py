"""LLM 层：按任务档位路由模型（V2 版）。"""

from __future__ import annotations

from typing import ClassVar


class ModelRouter:
    """V2 新增：不同任务用不同档位模型——检测不用 LLM、归因用强模型、
    叙事用便宜模型。一刀切一个模型是成本灾难。"""

    ROUTES: ClassVar[dict[str, str]] = {
        "extraction": "mid",
        "drill": "strong",
        "narrative": "cheap",
    }

    def route(self, task: str) -> str:
        return self.ROUTES.get(task, "mid")
