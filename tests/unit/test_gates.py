"""工具层三闸、行级权限注入与调用闸单测。"""

from __future__ import annotations

import riskqa.tools.dispatch as dispatch_mod
from riskqa.facts.store import FactStore
from riskqa.orchestration.graph_qa import sql_execute
from riskqa.tools.gates import check_sql, inject_row_filter


def test_check_sql_accepts_readonly_with_limit():
    verdict = check_sql(
        "SELECT channel, AVG(is_fpd30) FROM fact_application "
        "WHERE is_pass = 1 GROUP BY channel LIMIT 10"
    )
    assert verdict.ok is True
    assert verdict.violations == ()


def test_check_sql_rejects_missing_limit_select_star_and_dml():
    no_limit = check_sql("SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel")
    assert no_limit.ok is False
    assert any("缺少 LIMIT" in v for v in no_limit.violations)

    star = check_sql("SELECT * FROM fact_application LIMIT 10")
    assert star.ok is False
    assert any("SELECT *" in v for v in star.violations)

    dml = check_sql("DELETE FROM fact_application WHERE apply_id = 'AP1'")
    assert dml.ok is False
    assert any("DML/DDL" in v for v in dml.violations)


def test_check_sql_rejects_cartesian_product():
    verdict = check_sql("SELECT channel, AVG(is_fpd30) FROM fact_application, dim_channel LIMIT 10")
    assert verdict.ok is False
    assert any("笛卡尔积" in v for v in verdict.violations)


def test_inject_row_filter_inserts_or_ands_condition():
    base = "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel LIMIT 10"
    injected = inject_row_filter(base, "fact_application", "channel = 'A'")
    assert injected == (
        "SELECT channel, AVG(is_fpd30) FROM fact_application "
        "WHERE channel = 'A' GROUP BY channel LIMIT 10"
    )

    with_where = (
        "SELECT channel, AVG(is_fpd30) FROM fact_application "
        "WHERE is_pass = 1 GROUP BY channel LIMIT 10"
    )
    assert inject_row_filter(with_where, "fact_application", "channel = 'A'") == (
        "SELECT channel, AVG(is_fpd30) FROM fact_application "
        "WHERE (channel = 'A') AND is_pass = 1 GROUP BY channel LIMIT 10"
    )

    assert inject_row_filter(base, "fact_application", "") == base


def test_row_policy_and_unauthorized_empty_result(semantic, demo_df):
    assert semantic.row_filter("analyst_qa", "fact_application") == "channel = 'A'"
    assert semantic.row_filter("risk_admin", "fact_application") is None

    # 越权条件注入后返回空结果，不报错（P-10：不泄漏"有没有数据"）
    sql = "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel LIMIT 10"
    denied = inject_row_filter(sql, "fact_application", "channel = 'Z'")
    result = sql_execute(demo_df, denied)
    assert len(result) == 0


def test_pre_tool_gate_whitelist_metric_and_empty_report(semantic):
    old = dispatch_mod.SEMANTIC
    facts = FactStore(data_as_of="2026-09-30")
    try:
        dispatch_mod.SEMANTIC = semantic.metrics
        assert (
            dispatch_mod.pre_tool_gate(
                {"name": "query_metric", "args": {"metric": "fpd30_rate"}}, facts
            ).ok
            is True
        )
        assert dispatch_mod.pre_tool_gate({"name": "drop_table"}, facts).ok is False
        assert (
            dispatch_mod.pre_tool_gate(
                {"name": "query_metric", "args": {"metric": "loan_amt"}}, facts
            ).ok
            is False
        )
        assert (
            dispatch_mod.pre_tool_gate(
                {"name": "query_metric", "args": {"metric": "fpd30_rate", "group_by": "apply_id"}},
                facts,
            ).ok
            is False
        )
        assert dispatch_mod.pre_tool_gate({"name": "finish"}, facts).ok is False

        facts.put(0.5, "ratio", "pass_rate")
        assert dispatch_mod.pre_tool_gate({"name": "finish"}, facts).ok is True
    finally:
        dispatch_mod.SEMANTIC = old
