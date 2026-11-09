"""校验闸中间件（T-4.1.6）：同口径重算、越权空结果与回退审计。"""

from __future__ import annotations

from riskqa.orchestration.graph_qa import build_qa_graph

CFG = {"configurable": {"thread_id": "verify-mw"}}


def test_filter_scoped_recompute_has_no_false_positive(
    semantic, demo_df, facts, observer, spec, fake_llm
):
    """反证：带 filters 的快路事实按同口径重算，不再误判 render_mismatch。

    修复前 merge_verify 只用行权限收窄后的全量 df 重算，risk_admin 的
    channel=A 事实（0.2239）会被拿去与全量 0.2859 比对而误回退。
    """
    llm = fake_llm(
        [
            {"action": {"metric": "fpd30_rate"}},
            {"text": "A 渠道 FPD30 为 {{F0001}}。"},
        ]
    )
    graph = build_qa_graph(semantic, demo_df, facts, llm, observer, spec, role="risk_admin")
    out = graph.invoke({"question": "A 渠道 FPD30 是多少", "role": "risk_admin"}, config=CFG)

    assert out["route"] == "fast"
    assert out["scope"] == {"filters": {"channel": "A"}, "time_range": None}
    assert out["result"]["passed"] is True
    assert "[规则模板回退]" not in out["narrative"]


def test_denied_result_does_not_go_through_fallback(
    semantic, demo_df, facts, observer, spec, fake_llm
):
    """越权过滤后为空：直接空结果返回，不进回退、不产生叙事。"""
    llm = fake_llm([{"action": {"metric": "fpd30_rate"}}])
    graph = build_qa_graph(semantic, demo_df, facts, llm, observer, spec, role="analyst_qa")
    out = graph.invoke({"question": "B 渠道 FPD30 是多少", "role": "analyst_qa"}, config=CFG)

    assert out["result"] == {"passed": True, "empty": True}
    assert out.get("narrative", "") == ""
    assert "[规则模板回退]" not in out.get("narrative", "")
    assert observer.audit[-1].human_action == "row_filter_denied"


def test_fallback_is_audited_and_template_skips_gate(
    semantic, demo_df, facts, observer, spec, fake_llm
):
    """校验失败 → 整段回退 + 审计留痕；回退产物含裸数字但不再进校验闸（P-06 例外）。"""
    llm = fake_llm(
        [
            {"action": {"metric": "fpd30_rate"}},
            {"text": "整体 FPD30 是 0.2859。"},
        ]
    )
    graph = build_qa_graph(semantic, demo_df, facts, llm, observer, spec, role="analyst_qa")
    out = graph.invoke({"question": "整体 FPD30 是多少", "role": "analyst_qa"}, config=CFG)

    assert out["result"]["passed"] is False
    assert [f[0] for f in out["result"]["failures"]] == ["bare_number"]
    assert out["narrative"].startswith("[规则模板回退] 原因：")
    assert "fpd30_rate =" in out["narrative"]  # 事实清单直接输出裸值（P-06 例外）
    assert out["trace"][-1] == "merge_verify(fallback)"

    entry = observer.audit[-1]
    assert entry.human_action == "verify_fallback"
    assert entry.review_level == "auto"
    assert entry.actor == "analyst_qa"
    assert entry.route == "fast"
    assert "bare_number" in entry.sql
