"""生成 demo 快照（合成数据 + 硬标识）。

用法：make demo-snapshot
产物落在 data/snapshots/，已被 .gitignore 忽略；manifest 带 `synthetic: true`、
`data_as_of: DEMO`，非 demo 模式（RISKQA_MODE != demo）加载即拒绝启动。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from demo_data import build_demo_df  # noqa: E402

from riskqa.data.snapshot import DEMO_AS_OF, write_snapshot  # noqa: E402

DEMO_SOURCE = "demo_application"


def main() -> int:
    df = build_demo_df()
    man = write_snapshot(
        df,
        source=DEMO_SOURCE,
        data_as_of=DEMO_AS_OF,
        root=ROOT / "data" / "snapshots",
        synthetic=True,
    )
    print(f"已生成 demo 快照：data/snapshots/{man.locator}")
    print(
        f"  rows={man.rows} data_as_of={man.data_as_of} synthetic={man.synthetic} "
        f"data_hash={man.data_hash} file_hash={man.file_hash}"
    )
    print("  数据文件与 manifest 均被 .gitignore 忽略；加载需 RISKQA_MODE=demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
