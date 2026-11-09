"""校验层：独立重算入口（检查 3）。

与主流水线分开：本模块只接收"事实描述 + 数据快照"，直接调用 `calc/` 纯函数，
不经过 ask_fast / compute_metric 编排链路，也不调用 LLM（P-03）。
重算入口与主流水线共用同一事实源（calc 纯函数）是保证数字可比的必要条件；
"不共用"指不共用编排链路，避免用同一条路径自证。
"""

from __future__ import annotations

import pandas as pd

from ..calc.metrics import METRIC_FUNCS


class MetricNotRegisteredError(Exception):
    """事实声明的指标没有可重算的纯函数——显式失败，禁止静默跳过（R14）。"""


def recompute_fact(fact: dict, df: pd.DataFrame) -> float:
    """按事实的 metric/segment 在给定数据快照上独立重算。"""
    metric = fact["metric"]
    fn = METRIC_FUNCS.get(metric)
    if fn is None:
        raise MetricNotRegisteredError(f"指标 {metric!r} 未注册纯函数，无法独立重算（R14）")
    segment = fact["segment"]
    if segment == "overall":
        return float(fn(df))
    dim, val = segment.split("=", 1)
    sub = df[df[dim].astype(str) == val]
    if sub.empty:
        return float("nan")
    return float(fn(sub))
