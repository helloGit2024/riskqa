"""校验层：整段回退规则模板（可用性让位一致性）。"""

from __future__ import annotations

from ..facts.store import FactStore


def fallback_to_template(spec: dict, facts: FactStore, reason: str) -> str:
    """整段回退规则模板：可用性让位一致性，绝不交付没穿盔甲的数字"""
    lines = [f"[规则模板回退] 原因：{reason}"]
    for f in facts.digest():
        lines.append(f"  {f['metric']} = {f['value']}（{f['source']}，口径见语义层）")
    return "\n".join(lines)
