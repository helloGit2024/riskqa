"""校验闸单测：裸数字 / 编造引用 / 重算不一致 / 遍历范围。"""

from __future__ import annotations

import pytest

from riskqa.facts.store import FactStore
from riskqa.verify.gates import verify_report

AS_OF = "2026-09-30"
CORRECT_FPD30 = 0.2859042553191489


def test_bare_number_is_rejected(demo_df):
    facts = FactStore(data_as_of=AS_OF)
    verdict = verify_report("整体 FPD30 是 0.2859，符合预期。", facts, demo_df)
    assert verdict.passed is False
    assert verdict.failures[0][0] == "bare_number"


@pytest.mark.parametrize(
    "text",
    [
        "逾期率为 0.28591。",  # 任意位小数（旧规则只抓 1—4 位）
        "占比 28.6%。",  # 百分比
        "样本 1,200 条。",  # 千分位
        "区间 0.2~0.3。",  # 区间
        "共 1200 笔。",  # 带单位整数
    ],
)
def test_bare_number_variants_are_rejected(text, demo_df):
    facts = FactStore(data_as_of=AS_OF)
    verdict = verify_report(text, facts, demo_df)
    assert [f[0] for f in verdict.failures] == ["bare_number"]


def test_bare_number_exemptions_do_not_trigger(demo_df):
    """日期、年月、版本、指标代号、维度取值属于合法叙述，不算裸数字。"""
    facts = FactStore(data_as_of=AS_OF)
    fid = facts.put(CORRECT_FPD30, "ratio", "fpd30_rate")
    narrative = (
        f"截至 2026-09-30（2026 年 9 月，版本 V4.1），"
        f"整体 FPD30 为 {{{{{fid}}}}}；A 渠道与 P1 产品见语义层登记。"
    )
    verdict = verify_report(narrative, facts, demo_df)
    assert verdict.passed is True
    assert verdict.failures == []


def test_fabricated_ref_is_rejected(demo_df):
    facts = FactStore(data_as_of=AS_OF)
    verdict = verify_report("见事实 {{F9999}}。", facts, demo_df)
    assert verdict.passed is False
    assert verdict.failures == [("fabricated_ref", "F9999 不存在——模型编造了引用")]


def test_reference_lookup_is_existence_only_not_format(demo_df):
    """P-07：引用查存在性，不查格式——F99999 与 not-a-fid 都按编造引用处理。"""
    facts = FactStore(data_as_of=AS_OF)
    verdict = verify_report("见 {{F99999}} 与 {{not-a-fid}}。", facts, demo_df)
    assert [f[0] for f in verdict.failures] == ["fabricated_ref", "fabricated_ref"]
    assert "F99999" in verdict.failures[0][1]
    assert "not-a-fid" in verdict.failures[1][1]


def test_empty_reference_is_illegal(demo_df):
    facts = FactStore(data_as_of=AS_OF)
    verdict = verify_report("见 {{ }}。", facts, demo_df)
    assert verdict.failures == [("illegal_ref", " ")]


def test_render_mismatch_is_rejected(demo_df):
    facts = FactStore(data_as_of=AS_OF)
    facts.put(0.28, "ratio", "fpd30_rate")
    verdict = verify_report("整体 FPD30 为 {{F0001}}。", facts, demo_df)
    assert verdict.passed is False
    assert verdict.failures[0][0] == "render_mismatch"
    assert verdict.failures[0][1] == "F0001"


def test_correct_fact_passes_all_gates(demo_df):
    facts = FactStore(data_as_of=AS_OF)
    facts.put(CORRECT_FPD30, "ratio", "fpd30_rate")
    verdict = verify_report("整体 FPD30 为 {{F0001}}。", facts, demo_df)
    assert verdict.passed is True
    assert verdict.failures == []


def test_unreferenced_fact_not_recomputed(demo_df):
    """未被叙事引用的中间事实不进入重算——这是有意设计，不是漏检。

    校验闸只对"要说给用户听的那部分"负责；库里其它中间事实（包括错值）
    不应连带判失败。若有人改回全量遍历，本用例会立刻变红。
    """
    facts = FactStore(data_as_of=AS_OF)
    facts.put(0.28, "ratio", "fpd30_rate")  # F0001：错值，但叙事不引用它
    correct = facts.put(CORRECT_FPD30, "ratio", "fpd30_rate")  # F0002
    verdict = verify_report(f"整体 FPD30 为 {{{{{correct}}}}}。", facts, demo_df)
    assert verdict.passed is True
    assert verdict.failures == []


def test_unregistered_calc_is_explicit_failure(demo_df):
    """指标没有可重算纯函数时显式失败，不再静默跳过（R14）。"""
    facts = FactStore(data_as_of=AS_OF)
    fid = facts.put(0.5, "ratio", "ghost_rate")
    verdict = verify_report(f"幽灵指标为 {{{{{fid}}}}}。", facts, demo_df)
    assert verdict.passed is False
    assert verdict.failures[0][0] == "unregistered_calc"
    assert verdict.failures[0][1] == fid
