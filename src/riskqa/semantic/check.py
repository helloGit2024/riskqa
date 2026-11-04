"""语义层 YAML 校验 CLI：make semantic-check 的入口。

用法：python -m riskqa.semantic.check config/semantic_view.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..calc.metrics import METRIC_FUNCS
from .layer import SemanticLayer, load_semantic


def _check(sem: SemanticLayer) -> list[str]:
    errs: list[str] = []
    if len(sem.metrics) < 5:
        errs.append(f"指标数 {len(sem.metrics)} < 5")
    seen_aliases: dict[str, str] = {}
    for name, m in sem.metrics.items():
        for field in ("owner", "signed_at", "changelog"):
            if field not in m or not m[field]:
                if field == "changelog" and m.get(field) == []:
                    continue
                errs.append(f"指标 {name} 缺 {field}")
        if not m.get("dims"):
            errs.append(f"指标 {name} dims 为空")
        calc = m.get("calc")
        if calc not in METRIC_FUNCS:
            errs.append(f"指标 {name} 的 calc={calc!r} 未注册纯函数")
        for alias in m.get("aliases", []) or []:
            key = str(alias).lower()
            if key in seen_aliases and seen_aliases[key] != name:
                errs.append(f"alias {alias!r} 同时指向 {seen_aliases[key]} 与 {name}")
            seen_aliases[key] = name
    for role, policy in sem.row_policies.items():
        if not isinstance(policy, dict):
            errs.append(f"row_policies[{role}] 必须是 {{表: 条件}} 两层结构")
    for tname, table in sem.tables.items():
        if not table.get("columns"):
            errs.append(f"表 {tname} 缺 columns")
    return errs


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法：python -m riskqa.semantic.check <semantic_view.yaml>", file=sys.stderr)
        return 2
    try:
        sem = load_semantic(Path(argv[1]))
        errs = _check(sem)
    except Exception as e:  # noqa: BLE001  # CLI 边界：统一打印错误并返回 1
        print(f"semantic-check 失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if errs:
        print("semantic-check 失败：" + "；".join(errs), file=sys.stderr)
        return 1
    print(
        f"semantic-check: OK（{len(sem.metrics)} 指标 / "
        f"{len(sem.dim_enum)} 维度 / {len(sem.tables)} 表）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
