"""治理配置校验 CLI：make governance-check 的入口。

用法：python -m riskqa.governance.check config/governance.yaml
"""

from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

from .config import GovernanceError, load_governance_file


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法：python -m riskqa.governance.check <governance.yaml>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        base = load_governance_file(path, "2026-12-01")  # 临时调整已过期
        active = load_governance_file(path, "2026-10-30")  # 临时调整生效
    except GovernanceError as e:
        print(f"governance-check 失败：{e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001  # CLI 边界：统一打印错误并返回 1
        print(f"governance-check 失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    errs: list[str] = []
    if base.window_days > base.retention_days:
        errs.append(f"window_days={base.window_days} > retention_days={base.retention_days}")
    for obj, label in ((base.promotion, "promotion"), (base.review, "review")):
        for f in fields(obj):
            if getattr(obj, f.name) is None:
                errs.append(f"{label}.{f.name} 缺失")
    if active.promotion.min_users >= base.promotion.min_users:
        errs.append("temporary 在 2026-10-30 未生效")
    if errs:
        print("governance-check 失败：" + "；".join(errs), file=sys.stderr)
        return 1
    print(
        f"governance-check: OK（window={base.window_days} / retention={base.retention_days} / "
        f"temporary 生效 {active.promotion.min_users} vs 基线 {base.promotion.min_users}）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
