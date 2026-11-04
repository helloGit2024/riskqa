# -*- coding: utf-8 -*-
"""计算层：纯函数指标（数值唯一产出点，P-03）。"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from ..semantic.layer import UnregisteredMetricError


def fpd30_rate(df: pd.DataFrame) -> float:
    """首期逾期率：分母是放款户（is_pass=1），不是全量——未放款户不进分母"""
    granted = df[df["is_pass"] == 1]
    return float(granted["is_fpd30"].mean()) if len(granted) else float("nan")


def pass_rate(df: pd.DataFrame) -> float:
    return float(df["is_pass"].mean())


def ks(df: pd.DataFrame) -> float:
    y, s = df["y"], df["score"]
    if y.nunique() < 2:
        return float("nan")
    order = np.argsort(-s.values)
    yy = y.values[order]
    cum_pos = np.cumsum(yy == 1) / max((yy == 1).sum(), 1)
    cum_neg = np.cumsum(yy == 0) / max((yy == 0).sum(), 1)
    return float(np.max(np.abs(cum_pos - cum_neg)))


def auc(df: pd.DataFrame) -> float:
    y, s = df["y"], df["score"]
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    return float((pos.values[:, None] > neg.values[None, :]).mean()
                 + 0.5 * (pos.values[:, None] == neg.values[None, :]).mean())


def psi(df: pd.DataFrame) -> float:
    y, s = df["y"], df["score"]
    bins = np.linspace(s.min(), s.max(), 11)
    idx = np.clip(np.digitize(s, bins[1:-1]), 0, 9)
    e = np.bincount(idx[y == 1], minlength=10) / max((y == 1).sum(), 1)
    a = np.bincount(idx[y == 0], minlength=10) / max((y == 0).sum(), 1)
    e, a = np.clip(e, 1e-6, None), np.clip(a, 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))


METRIC_FUNCS: dict[str, Callable[[pd.DataFrame], float]] = {
    "fpd30_rate": fpd30_rate, "pass_rate": pass_rate,
    "ks": ks, "auc": auc, "psi": psi,
}


def compute_metric(name: str, df: pd.DataFrame, group_by: str | None = None) -> pd.DataFrame:
    """快路唯一计算入口：只认语义层登记名，未登记直接拒绝"""
    if name not in METRIC_FUNCS:
        raise UnregisteredMetricError(f"指标 {name!r} 未登记，已登记：{sorted(METRIC_FUNCS)}")
    fn = METRIC_FUNCS[name]
    if group_by is None:
        return pd.DataFrame([{"value": fn(df)}])
    return (df.groupby(group_by, observed=True)
              .apply(lambda g: pd.Series({"value": fn(g)}), include_groups=False)
              .reset_index())
