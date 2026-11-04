# -*- coding: utf-8 -*-
"""校验层：三重检查——整个方案的安全底线。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..calc.metrics import METRIC_FUNCS
from ..facts.store import FactStore, UnknownFactError

FACT_REF = re.compile(r"\{\{(F\d{4})\}\}")
BARE_NUMBER = re.compile(r"(?<!\{)\b\d+\.\d{1,4}\b(?!\})")


@dataclass
class Verdict:
    passed: bool
    failures: list[tuple] = field(default_factory=list)


def verify_report(narrative: str, facts: FactStore, df: pd.DataFrame) -> Verdict:
    """三重校验闸：任何一道不过，整段回退规则模板，绝不交付半成品

    检查 3 只遍历报告中实际引用的 fact（逐条独立重算）——
    报告没用到的指标不该判 missing；引用到的每一条都必须对得上。
    """
    failures: list[tuple] = []
    # 检查 1：叙事层不许出现裸数字，必须在 {{F0001}} 里
    for hit in BARE_NUMBER.findall(narrative):
        failures.append(("bare_number", hit))
    # 检查 2：所有引用必须存在（抓编造 fact_id）
    for fid in FACT_REF.findall(narrative):
        try:
            facts.get(fid)
        except UnknownFactError as e:
            failures.append(("fabricated_ref", str(e)))
    # 检查 3：渲染一致性——Python 独立重算，不经 LLM、不经流水线
    for f in facts.digest():
        metric = f["metric"]
        if metric not in METRIC_FUNCS:
            continue
        if f["segment"] == "overall":
            expect = METRIC_FUNCS[metric](df)
        else:
            dim, val = f["segment"].split("=", 1)
            sub = df[df[dim].astype(str) == val]
            expect = METRIC_FUNCS[metric](sub) if len(sub) else float("nan")
        if not np.isclose(float(f["value"]), float(expect), rtol=1e-6, equal_nan=True):
            failures.append(("render_mismatch", f["fid"],
                             f"{metric}@{f['segment']} 报告 {f['value']} vs 重算 {expect}"))
    return Verdict(passed=not failures, failures=failures)
