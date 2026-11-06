"""T-4.1.2 快路：四类拒服、结果契约与 P95 采样。"""

from __future__ import annotations

import time

import pandas as pd
import pytest
import yaml

from riskqa.facts.store import FactStore
from riskqa.orchestration.fast_path import (
    AskRequest,
    CalcNotRegisteredError,
    DimensionNotAllowedError,
    NoFactError,
    ask_fast,
    build_ask_metric_schema,
    parse_question,
    pre_tool_gate,
)
from riskqa.semantic.layer import (
    SemanticLayer,
    UnregisteredMetricError,
    UnsignedMetricError,
)

AS_OF = "2026-09-30"
OVERALL_FPD30 = 0.2859042553191489


def _patched(semantic: SemanticLayer, name: str, patch: dict) -> SemanticLayer:
    """在内存里改一份 YAML 副本，不动 config/（P-15：配置仍是唯一事实源）。"""
    cfg = yaml.safe_load(semantic.to_yaml())
    for metric in cfg["metrics"]:
        if metric["name"] == name:
            metric.update(patch)
    return SemanticLayer(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))


def test_schema_enum_comes_from_semantic_layer(semantic: SemanticLayer):
    """P-08：FC 工具 enum 必须由语义层生成，不能手写。"""
    schema = build_ask_metric_schema(semantic)
    params = schema["parameters"]["properties"]
    assert schema["name"] == "ask_metric"
    assert params["metric"]["enum"] == semantic.metric_enum
    assert params["dims"]["items"]["enum"] == semantic.dim_enum


def test_parse_question_hits_alias_and_dims(semantic: SemanticLayer):
    req = parse_question("FPD30 按渠道看一下", semantic)
    assert req is not None
    assert req.metric == "fpd30_rate"
    assert req.dims == ("channel",)


def test_parse_question_misses_metric_goes_slow(semantic: SemanticLayer):
    """未命中指标时返回 None，由路由交慢路——不在快路猜。"""
    assert parse_question("各渠道平均逾期水平如何", semantic) is None


def test_parse_question_extracts_filter_and_period(semantic: SemanticLayer):
    req = parse_question("A渠道 FPD30 2026-07", semantic)
    assert req is not None
    assert req.filters == {"channel": "A"}
    assert req.time_range == ("2026-07", "2026-07")


def test_reject_invented_metric(semantic: SemanticLayer, demo_df, facts):
    with pytest.raises(UnregisteredMetricError):
        ask_fast(AskRequest(metric="invented_rate"), semantic, demo_df, facts)


def test_reject_invented_metric_from_llm(semantic, demo_df, facts, fake_llm):
    """模型选的指标也必须过前闸，不能凭模型输出直接算。"""
    llm = fake_llm([{"action": {"metric": "invented_rate"}}])
    with pytest.raises(UnregisteredMetricError):
        ask_fast(
            AskRequest(metric="fpd30_rate"),
            semantic,
            demo_df,
            facts,
            question="FPD30 是多少",
            llm=llm,
        )


def test_reject_dimension_not_allowed(semantic: SemanticLayer, demo_df, facts):
    """ks 只声明 vintage，按 channel 拆维度必须拒服。"""
    with pytest.raises(DimensionNotAllowedError):
        ask_fast(AskRequest(metric="ks", dims=("channel",)), semantic, demo_df, facts)


def test_reject_multi_dim(semantic: SemanticLayer, demo_df, facts):
    with pytest.raises(DimensionNotAllowedError):
        ask_fast(
            AskRequest(metric="fpd30_rate", dims=("channel", "product")),
            semantic,
            demo_df,
            facts,
        )


def test_reject_unsigned_metric(semantic: SemanticLayer, demo_df, facts):
    unsigned = _patched(semantic, "fpd30_rate", {"owner": ""})
    with pytest.raises(UnsignedMetricError):
        ask_fast(AskRequest(metric="fpd30_rate"), unsigned, demo_df, facts)


def test_reject_calc_not_registered(semantic: SemanticLayer, demo_df, facts):
    ghost = _patched(semantic, "fpd30_rate", {"calc": "ghost_calc"})
    with pytest.raises(CalcNotRegisteredError):
        ask_fast(AskRequest(metric="fpd30_rate"), ghost, demo_df, facts)


def test_result_contract(semantic: SemanticLayer, demo_df, facts):
    result = ask_fast(AskRequest(metric="fpd30_rate"), semantic, demo_df, facts)
    assert len(result.facts) == 1
    assert result.facts[0].value == pytest.approx(OVERALL_FPD30)
    assert result.data_as_of == AS_OF
    assert result.ai_disclosure is True
    assert result.group_by is None


def test_grouped_facts_contract(semantic: SemanticLayer, demo_df, facts):
    result = ask_fast(AskRequest(metric="fpd30_rate", dims=("channel",)), semantic, demo_df, facts)
    assert result.group_by == "channel"
    assert {f.segment for f in result.facts} == {"channel=A", "channel=B", "channel=C"}


def test_no_fact_refuses_report(semantic: SemanticLayer, demo_df, facts):
    """过滤后无数据 → 无事实，禁止出报告（P-06）。"""
    with pytest.raises(NoFactError):
        ask_fast(
            AskRequest(metric="fpd30_rate", filters={"channel": "Z"}),
            semantic,
            demo_df,
            facts,
        )


def test_changelog_empty_list_still_signed(semantic: SemanticLayer):
    """与 semantic/check.py 一致：changelog 允许空列表，不算未签字。"""
    pre_tool_gate(AskRequest(metric="psi"), semantic)


def test_fast_path_p95_under_2s(semantic: SemanticLayer, demo_df: pd.DataFrame):
    """验收原文：快路 P95<2s（阈值不放宽，抖动就修实现不降标准）。"""
    elapsed_ms: list[float] = []
    for _ in range(1000):
        store_facts = FactStore(data_as_of=AS_OF)
        start = time.perf_counter()
        ask_fast(
            AskRequest(metric="fpd30_rate", dims=("channel",)),
            semantic,
            demo_df,
            store_facts,
        )
        elapsed_ms.append((time.perf_counter() - start) * 1000)

    elapsed_ms.sort()
    median_ms = elapsed_ms[len(elapsed_ms) // 2]
    p95_ms = elapsed_ms[int(len(elapsed_ms) * 0.95)]
    print(
        f"\nP95 采样：n={len(elapsed_ms)}，数据={len(demo_df)} 行，"
        f"中位数={median_ms:.2f}ms，P95={p95_ms:.2f}ms，阈值=2000ms"
    )
    assert p95_ms < 2000, f"快路 P95={p95_ms:.2f}ms 超过 2s"
