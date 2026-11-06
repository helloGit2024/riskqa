"""工具层三闸、行级权限注入与调用闸单测。"""

from __future__ import annotations

import pytest

import riskqa.tools.dispatch as dispatch_mod
from riskqa.facts.store import FactStore
from riskqa.orchestration.graph_qa import sql_execute
from riskqa.tools.gates import (
    RowFilterParseError,
    apply_row_filter,
    check_sql,
    inject_row_filter,
)


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


def test_check_sql_rejects_injection_signatures():
    """闸③：UNION / 分号 / 注释 / xp_ / INTO OUTFILE 一律拒（SG-01 #4）。"""
    cases = {
        "UNION": "SELECT channel, AVG(is_fpd30) FROM fact_application LIMIT 10 "
        "UNION SELECT channel, AVG(is_fpd30) FROM fact_application LIMIT 10",
        "分号": "SELECT channel, AVG(is_fpd30) FROM fact_application LIMIT 10; DROP TABLE fact",
        "行注释": "SELECT channel, AVG(is_fpd30) FROM fact_application -- LIMIT 10",
        "块注释": "SELECT channel, AVG(is_fpd30) FROM fact_application /* x */ LIMIT 10",
        "xp_": "SELECT channel, AVG(is_fpd30) FROM fact_application LIMIT 10 xp_cmdshell('whoami')",
        "INTO OUTFILE": "SELECT channel, AVG(is_fpd30) FROM fact_application "
        "LIMIT 10 INTO OUTFILE '/tmp/x'",
    }
    for name, sql in cases.items():
        verdict = check_sql(sql)
        assert verdict.ok is False, name
        assert any("注入特征" in v for v in verdict.violations), name


def test_check_sql_rejects_non_select_whitelist():
    """闸①：非 SELECT/WITH 的只读语句也拒（PRAGMA/ATTACH/EXPLAIN）。"""
    for sql in (
        "PRAGMA table_info(fact_application)",
        "ATTACH DATABASE '/tmp/x.db' AS x",
        "EXPLAIN SELECT channel FROM fact_application LIMIT 10",
    ):
        verdict = check_sql(sql)
        assert verdict.ok is False
        assert any("只允许 SELECT" in v for v in verdict.violations)


def test_apply_row_filter_parses_equality_and_in(demo_df, semantic):
    """快路行权限：等值/IN/AND 在计算前收窄；未知字段与非受限语法显式失败。"""
    condition = semantic.row_filter("analyst_qa", "fact_application")
    filtered = apply_row_filter(demo_df, condition)
    assert set(filtered["channel"]) == {"A"}
    assert len(filtered) < len(demo_df)

    assert set(apply_row_filter(demo_df, "channel IN ('A', 'B')")["channel"]) == {"A", "B"}
    assert set(apply_row_filter(demo_df, "is_pass = 1")["is_pass"]) == {1}
    combined = apply_row_filter(demo_df, "channel = 'A' AND is_pass = 1")
    assert set(combined["channel"]) == {"A"}
    assert set(combined["is_pass"]) == {1}
    assert apply_row_filter(demo_df, "") is demo_df

    with pytest.raises(RowFilterParseError, match="不在数据列"):
        apply_row_filter(demo_df, "ghost = 'A'")
    with pytest.raises(RowFilterParseError, match="受限语法"):
        apply_row_filter(demo_df, "score > 0.5")


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
