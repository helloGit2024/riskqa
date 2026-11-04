# -*- coding: utf-8 -*-
"""校验闸单测：裸数字 / 编造引用 / 重算不一致。"""

from __future__ import annotations

import pytest

from riskqa.facts.store import FactStore
from riskqa.verify.gates import verify_report


def test_bare_number_is_rejected(demo_df):
    facts = FactStore(data_as_of="2026-09-30")
    verdict = verify_report("整体 FPD30 是 0.2859，符合预期。", facts, demo_df)
    assert verdict.passed is False
    assert verdict.failures[0][0] == "bare_number"


def test_fabricated_ref_is_rejected(demo_df):
    facts = FactStore(data_as_of="2026-09-30")
    verdict = verify_report("见事实 {{F9999}}。", facts, demo_df)
    assert verdict.passed is False
    assert verdict.failures == [("fabricated_ref", "F9999 不存在——模型编造了引用")]


def test_render_mismatch_is_rejected(demo_df):
    facts = FactStore(data_as_of="2026-09-30")
    facts.put(0.28, "ratio", "fpd30_rate")
    verdict = verify_report("整体 FPD30 为 {{F0001}}。", facts, demo_df)
    assert verdict.passed is False
    assert verdict.failures[0][0] == "render_mismatch"
    assert verdict.failures[0][1] == "F0001"


def test_correct_fact_passes_all_gates(demo_df):
    facts = FactStore(data_as_of="2026-09-30")
    facts.put(0.2859042553191489, "ratio", "fpd30_rate")
    verdict = verify_report("整体 FPD30 为 {{F0001}}。", facts, demo_df)
    assert verdict.passed is True
    assert verdict.failures == []
