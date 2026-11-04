"""校验层：AI 产出显著标识（P-16）。"""

from __future__ import annotations


def ai_disclosure(model: str, as_of: str) -> str:
    """合规：监管要求生成内容显著标识——每份 AI 产出必须带"""
    return (
        f"<!-- AI-GENERATED · 需人工复核 · 模型:{model} · 数据截止:{as_of} · "
        f"本内容由大模型生成，数字经 Python 独立重算校验 -->"
    )
