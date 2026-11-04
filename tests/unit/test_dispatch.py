"""分发层单测：OPEN-QUESTIONS #13 的分组路径缺陷。"""

from __future__ import annotations

import pytest

import riskqa.tools.dispatch as dispatch_mod


@pytest.mark.xfail(
    strict=True,
    reason="OPEN-QUESTIONS #13：FactStore.put 第 4 位置参映射到 segment，"
    "分组路径 TypeError；本任务只固化，不修生产代码",
)
def test_dispatch_grouped_metric_is_broken(semantic, demo_df, facts):
    old = dispatch_mod.SEMANTIC
    try:
        dispatch_mod.SEMANTIC = semantic.metrics
        result = dispatch_mod.dispatch(
            {"name": "query_metric", "args": {"metric": "fpd30_rate", "group_by": "channel"}},
            demo_df,
            facts,
        )
        # 期望行为：每个维度值产出一个 fact_id（当前实现会抛 TypeError）
        assert len(result["fids"]) == 3
    finally:
        dispatch_mod.SEMANTIC = old
