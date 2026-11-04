# -*- coding: utf-8 -*-
"""LLM 层：FakeLLM 脚本驱动 + DegradedLLM 降级链（V2 版）。"""

from __future__ import annotations

from typing import Callable


class FakeLLM:
    """按脚本返回动作。测编排层和闸门，不花 token、不受网络影响、可复现"""

    def __init__(self, script: list[dict], model: str = "fake-mid"):
        self._script = list(script)
        self.model = model
        self.calls: list[dict] = []
        self.tokens_used = 0

    def chat(self, task: str, prompt: str, **kw) -> dict:
        self.calls.append({"task": task, "prompt": prompt})
        self.tokens_used += len(prompt) // 4 + 50      # 估算成本
        return self._script.pop(0) if self._script else {"type": "finish"}


class DegradedLLM:
    """V2 新增韧性：LLM 调用失败时按降级链走，任何一级不静默"""

    def __init__(self, primary: FakeLLM, fallback: Callable[[str], dict]):
        self.primary = primary
        self.fallback = fallback
        self.degraded = False

    def chat(self, task: str, prompt: str, **kw) -> dict:
        try:
            return self.primary.chat(task, prompt, **kw)
        except Exception as e:                           # 超时/限流/返回异常
            self.degraded = True
            out = self.fallback(prompt)
            out["_degraded"] = f"LLM 不可用（{type(e).__name__}），已降级：{out.get('_degraded_reason', '规则兜底')}"
            return out
