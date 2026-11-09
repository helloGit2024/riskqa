"""校验层：三重检查——整个方案的安全底线。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..facts.store import FactStore, UnknownFactError
from .recompute import MetricNotRegisteredError, recompute_fact

FACT_REF = re.compile(r"\{\{([^{}]*)\}\}")

# 豁免：叙述里合法出现的"非指标数字"（日期、版本、指标代号、维度取值）
_EXEMPT_PATTERNS = (
    re.compile(r"\b20\d{2}-\d{1,2}-\d{1,2}\b"),  # ISO 日期 2026-09-30
    re.compile(r"\b20\d{2}-\d{2}\b"),  # 年月 2026-07
    re.compile(r"\b20\d{2}\s*年(?:\s*\d{1,2}\s*月)?"),  # 2026 年 / 2026 年 9 月
    re.compile(r"\bV\d+(?:\.\d+)+\b", re.IGNORECASE),  # 版本号 V4.1
    re.compile(r"\b(?:FPD|DPD)\d+\+?", re.IGNORECASE),  # 指标代号 FPD30 / DPD30+
    re.compile(r"\b(?:channel|product|vintage)\s*[=＝]\s*[A-Za-z0-9]+", re.IGNORECASE),  # channel=A
    re.compile(r"\b[A-C]\s*渠道"),  # A 渠道
    re.compile(r"\bP[12]\s*产品"),  # P1 产品
    re.compile(r"\bP[12]\b"),  # P1 / P2
)

# 裸数字判定：任意位小数 / 百分比 / 千分位 / 区间 / 带单位整数
_NUMBER_PATTERNS = (
    re.compile(r"\d+\.\d+"),
    re.compile(r"\d+(?:\.\d+)?\s*%"),
    re.compile(r"\d{1,3}(?:,\d{3})+"),
    re.compile(r"\d+(?:\.\d+)?\s*[-~～至]\s*\d+(?:\.\d+)?"),
    re.compile(r"\d+(?:\.\d+)?\s*(?:条|个|笔|户|人|次|元|万元|亿元|天|小时|分钟|秒|ms|倍|bp)"),
)


@dataclass
class Verdict:
    passed: bool
    failures: list[tuple] = field(default_factory=list)


def _bare_numbers(narrative: str) -> list[str]:
    """先屏蔽 {{引用}} 与豁免片段，再按数值形态逐类抓取（重叠区间合并为一条）。"""
    masked = FACT_REF.sub(lambda m: " " * len(m.group(0)), narrative)
    for pattern in _EXEMPT_PATTERNS:
        masked = pattern.sub(lambda m: " " * len(m.group(0)), masked)
    spans: list[tuple[int, int]] = []
    for pattern in _NUMBER_PATTERNS:
        spans.extend((m.start(), m.end()) for m in pattern.finditer(masked))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [masked[start:end] for start, end in merged]


def verify_report(narrative: str, facts: FactStore, df: pd.DataFrame) -> Verdict:
    """三重校验闸：任何一道不过，整段回退规则模板，绝不交付半成品。

    语义边界：校验闸只对"要说给用户听的那部分"负责，不连带审查库里所有
    中间事实——检查 3 只重算叙事中实际引用、且查得到的事实（有意设计，
    见 test_unreferenced_fact_not_recomputed）。
    """
    failures: list[tuple] = []

    # 检查 1：叙事层不许出现裸数字，必须在 {{F0001}} 里
    for hit in _bare_numbers(narrative):
        failures.append(("bare_number", hit))

    # 检查 2：所有引用必须存在（抓编造 fact_id；只查存在性，不查格式，P-07）
    referenced: list[dict] = []
    seen: set[str] = set()
    for raw in FACT_REF.findall(narrative):
        fid = raw.strip()
        if not fid:
            failures.append(("illegal_ref", raw))
            continue
        try:
            fact = facts.get(fid)
        except UnknownFactError as e:
            failures.append(("fabricated_ref", str(e)))
            continue
        if fid not in seen:
            seen.add(fid)
            referenced.append(
                {"fid": fid, "value": fact.value, "metric": fact.metric, "segment": fact.segment}
            )

    # 检查 3：渲染一致性——对叙事引用的事实独立重算，不经 LLM、不经流水线
    for f in referenced:
        try:
            expect = recompute_fact(f, df)
        except MetricNotRegisteredError as e:
            failures.append(("unregistered_calc", f["fid"], str(e)))
            continue
        if not np.isclose(float(f["value"]), float(expect), rtol=1e-6, equal_nan=True):
            failures.append(
                (
                    "render_mismatch",
                    f["fid"],
                    f"{f['metric']}@{f['segment']} 报告 {f['value']} vs 重算 {expect}",
                )
            )

    return Verdict(passed=not failures, failures=failures)
