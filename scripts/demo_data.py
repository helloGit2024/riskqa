"""demo 申请样本构造（唯一来源）。

`tests/conftest.py` 的 `demo_df` 夹具与 `scripts/make_demo_snapshot.py` 共用本函数，
禁止再复制第二份构造逻辑。来源：legacy/问数Agent_企业版V2.py L1069—L1091；
基线 2026-11-04，pandas 2.2.3，seed=42。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_demo_df(n: int = 1200) -> pd.DataFrame:
    """申请样本：固定 seed，列与生产申请事实表一致。"""
    rng = np.random.default_rng(42)
    channels = rng.choice(["A", "B", "C"], n, p=[0.5, 0.3, 0.2])
    products = rng.choice(["P1", "P2"], n, p=[0.6, 0.4])
    vintage = rng.choice(["2026-07", "2026-08"], n)
    is_pass = (rng.random(n) < 0.62).astype(int)
    score_v3 = np.clip(rng.normal(0.60, 0.15, n), 0.01, 0.99)
    score_v2 = np.clip(rng.normal(0.55, 0.18, n), 0.01, 0.99)
    y = (rng.random(n) < (0.38 - 0.32 * score_v3)).astype(int)
    bad_p = np.where(channels == "B", 0.45, 0.25)
    is_fpd30 = np.where(is_pass == 1, (rng.random(n) < bad_p).astype(int), 0)
    return pd.DataFrame(
        {
            "apply_id": [f"AP{i:05d}" for i in range(n)],
            "customer_id": [f"C{i:05d}" for i in range(n)],
            "channel": channels,
            "product": products,
            "vintage": vintage,
            "is_pass": is_pass,
            "is_fpd30": is_fpd30,
            "score": score_v3.round(4),
            "score_v3": score_v3.round(4),
            "score_v2": score_v2.round(4),
            "y": y,
        }
    )
