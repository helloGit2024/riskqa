"""计算层：独立重算与快慢路交叉验证。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import METRIC_FUNCS


def recompute_all(spec: dict, df: pd.DataFrame) -> dict:
    """校验闸第三重的武器：不经 LLM、不经流水线，Python 独立重算"""
    return {
        m["name"]: METRIC_FUNCS[m["calc"]](df) for m in spec["metrics"] if m["calc"] in METRIC_FUNCS
    }


def cross_check(
    metric: str, fast_value: float, slow_value: float, rtol: float = 1e-6
) -> tuple[bool, str]:
    """V2 新增：快慢路两套实现对同一个指标的结果比对——防口径悄悄漂移"""
    if pd.isna(fast_value) or pd.isna(slow_value):
        return False, f"{metric}: 快路 {fast_value} vs 慢路 {slow_value}（含 NaN，拒绝采信）"
    if np.isclose(fast_value, slow_value, rtol=rtol):
        return True, f"{metric}: {fast_value:.6f} == {slow_value:.6f} ✓"
    return False, (
        f"{metric}: 快路 {fast_value:.6f} vs 慢路 {slow_value:.6f} "
        f"不一致（rtol={rtol}）——两条路有一条口径错了，禁止交付"
    )
