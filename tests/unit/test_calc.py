"""计算层纯函数单测：分母口径、分组 NaN、已知退化边界。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from riskqa.calc.metrics import (
    auc,
    compute_metric,
    fpd30_rate,
    ks,
    pass_rate,
    psi,
)
from riskqa.semantic.layer import UnregisteredMetricError


def test_fpd30_rate_denominator_is_granted_only():
    """分母是放款户（is_pass=1），未放款户不进分母。"""
    df = pd.DataFrame({"is_pass": [1, 1, 0, 0], "is_fpd30": [1, 0, 1, 1]})
    assert fpd30_rate(df) == pytest.approx(0.5)


def test_fpd30_rate_empty_or_no_granted_is_nan():
    assert np.isnan(fpd30_rate(pd.DataFrame({"is_pass": [], "is_fpd30": []})))
    assert np.isnan(fpd30_rate(pd.DataFrame({"is_pass": [0, 0], "is_fpd30": [1, 0]})))


def test_pass_rate_counts_all_applications():
    assert pass_rate(pd.DataFrame({"is_pass": [1, 0, 1, 0]})) == pytest.approx(0.5)


def test_compute_metric_rejects_unregistered_metric():
    with pytest.raises(UnregisteredMetricError, match="未登记"):
        compute_metric("loan_amt", pd.DataFrame({"loan_amt": [1.0]}))


def test_compute_metric_grouped_keeps_nan_group():
    """OPEN-QUESTIONS #15 现状：某组无放款户 → 该组 NaN 保留。

    是否让整条问数失败由装配层决定；store 层拒收 NaN（见 test_store_smoke）。
    """
    df = pd.DataFrame(
        {
            "product": ["A", "A", "B"],
            "is_pass": [1, 1, 0],
            "is_fpd30": [1, 0, 0],
        }
    )
    result = compute_metric("fpd30_rate", df, group_by="product")
    values = dict(zip(result["product"], result["value"], strict=True))
    assert values["A"] == pytest.approx(0.5)
    assert np.isnan(values["B"])


def test_known_fake_numbers_on_degenerate_input():
    """OPEN-QUESTIONS #16：空表 psi=0.0、score 全缺失时 ks=1.0/auc=0.0。

    这是 legacy 同源的"已知假数字"——本任务只固化现状，不改计算逻辑；
    真实修复需在 store 之外增加样本量/有效值告警。
    """
    empty = pd.DataFrame({"y": pd.Series(dtype=int), "score": pd.Series(dtype=float)})
    assert psi(empty) == 0.0

    all_nan_score = pd.DataFrame({"y": [1, 1, 0, 0], "score": [np.nan] * 4})
    assert ks(all_nan_score) == 1.0
    assert auc(all_nan_score) == 0.0


def test_ks_and_auc_single_class_is_nan():
    one_class = pd.DataFrame({"y": [1, 1, 1], "score": [0.1, 0.2, 0.3]})
    assert np.isnan(ks(one_class))
    assert np.isnan(auc(one_class))
