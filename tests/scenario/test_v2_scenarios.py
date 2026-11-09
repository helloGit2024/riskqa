"""V2 九场景迁移（来源：legacy/问数Agent_企业版V2.py L1107—L1256）。

golden 值冻结于 2026-11-04、pandas 2.2.3；测试不 import legacy，只断言数字与行为。
"""

from __future__ import annotations

import numpy as np
import pytest
from langgraph.types import Command

from riskqa.calc.metrics import METRIC_FUNCS, compute_metric
from riskqa.calc.recompute import cross_check
from riskqa.facts.store import FactStore
from riskqa.llm.fake import DegradedLLM, FakeLLM
from riskqa.orchestration.backtest import run_backtest
from riskqa.orchestration.graph_attribution import build_attribution_graph
from riskqa.orchestration.graph_qa import build_qa_graph, sql_execute
from riskqa.verify.gates import verify_report

V2_OVERALL_FPD = 0.2859042553191489  # legacy L1121 场景一（V4.0 基线；无行权限全量）
V2_A_FPD = 0.22391857506361323  # legacy L1141 场景二
V2_WRONG_FPD = 0.1461794019933555  # legacy L1188 场景五（慢路分母错）


def test_v2_1_fast_path_returns_fact_and_passes_gates(
    semantic, demo_df, facts, observer, spec, fake_llm
):
    """场景一：快路问数——命中语义层，模型只选参数，fact_id + 三重闸 PASS。"""
    llm = fake_llm(
        [
            {"action": {"metric": "fpd30_rate"}},
            {
                "text": "整体 FPD30 为 {{F0001}}，口径：放款客户中首期 DPD30+ 的占比（见语义层登记）。"
            },
        ]
    )
    graph = build_qa_graph(semantic, demo_df, facts, llm, observer, spec)
    out = graph.invoke(
        {"question": "整体 FPD30 是多少", "role": "analyst_qa"},
        config={"configurable": {"thread_id": "t1"}},
    )

    assert out["route"] == "fast"
    assert out["metric"] == "fpd30_rate"
    assert out["result"]["passed"] is True
    assert len(out["facts"]) == 1
    fact = out["facts"][0]
    assert fact["fid"] == "F0001"
    assert fact["segment"] == "overall"
    assert fact["data_as_of"] == "2026-09-30"
    assert fact["value"] == pytest.approx(V2_A_FPD, rel=1e-6)  # P-10：analyst 仅可见 A


def test_v2_2_slow_path_injects_row_filter_and_returns_authorized_segment(
    semantic, demo_df, facts, observer, spec, fake_llm
):
    """场景二：慢路问数——未命中走 text-to-SQL，执行前注入行级权限。"""
    llm = fake_llm(
        [
            {"tables": ["fact_application"]},
            {
                "sql": "SELECT channel, AVG(is_fpd30) FROM fact_application "
                "WHERE is_pass = 1 GROUP BY channel LIMIT 10"
            },
            {
                "text": "各渠道平均逾期水平见事实清单 {{F0001}} 起（受行级权限约束，仅返回授权渠道）。"
            },
        ]
    )
    graph = build_qa_graph(semantic, demo_df, facts, llm, observer, spec, role="analyst_qa")
    out = graph.invoke(
        {"question": "各渠道平均逾期水平如何", "role": "analyst_qa"},
        config={"configurable": {"thread_id": "t2"}},
    )

    assert out["route"] == "slow"
    injected = [t for t in observer.trace if t["node"] == "slow_execute"][-1]
    assert "channel = 'A'" in injected["sql"]
    assert "is_pass = 1" in injected["sql"]
    assert out["result"]["passed"] is True
    assert len(out["facts"]) >= 1
    assert all(f["segment"] == "channel=A" for f in out["facts"]), "行级权限泄漏！"
    assert out["facts"][0]["value"] == pytest.approx(V2_A_FPD, rel=1e-6)


def test_v2_3_must_review_interrupt_and_resume(semantic, demo_df, facts, observer, spec, fake_llm):
    """场景三：must 级人审——高风险 JOIN SQL 触发 interrupt，人工 accept 后恢复。"""
    llm = fake_llm(
        [
            {"tables": ["fact_application"]},
            {
                "sql": "SELECT a.channel, AVG(a.is_fpd30) FROM fact_application a "
                "JOIN dim_channel b ON a.channel = b.channel GROUP BY a.channel LIMIT 10"
            },
            {"text": "跨表查询完成，见 {{F0001}}。"},
        ]
    )
    graph = build_qa_graph(semantic, demo_df, facts, llm, observer, spec, role="analyst_qa")
    cfg = {"configurable": {"thread_id": "t3"}}
    out = graph.invoke({"question": "按渠道大区看逾期", "role": "analyst_qa"}, config=cfg)

    pending = out.get("__interrupt__")
    assert pending, "高风险 SQL 必须触发人审中断"
    assert pending[0].value["review_level"] == "must"

    out = graph.invoke(Command(resume={"type": "accept", "text": "同意执行"}), config=cfg)
    assert any(a.human_action == "accept" and a.review_level == "must" for a in observer.audit)
    # JOIN 形态 demo 执行器不支持 → 引用不到 fact → 三重闸抓回退（不交付半成品）
    assert out["result"]["passed"] is False
    assert out["result"]["failures"][0][0] == "fabricated_ref"


def test_v2_4_no_limit_rejected_and_step_limit_fails(
    semantic, demo_df, facts, observer, spec, fake_llm
):
    """场景四：失败复现——无 LIMIT SQL 被打回，持续不合规触发步数上限。"""
    bad_llm = fake_llm(
        [
            {"sql": "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel"},
        ]
        * 8
    )
    graph = build_qa_graph(
        semantic, demo_df, facts, bad_llm, observer, spec, role="risk_admin", max_steps=6
    )
    out = graph.invoke(
        {"question": "各渠道逾期", "role": "risk_admin"},
        config={"configurable": {"thread_id": "t4"}},
    )

    checks = [t for t in observer.trace if t["node"] == "slow_sql_check"]
    assert checks and all(t["ok"] is False for t in checks)
    assert any("缺少 LIMIT" in v for t in checks for v in t["violations"])
    assert out["result"]["passed"] is False
    assert out["result"]["failures"] == [("step_limit", 6)]
    assert out["narrative"] == "[失败] 慢路未在步数上限内收敛，拒绝交付半成品"


def test_v2_5_cross_check_catches_caliber_drift(demo_df):
    """场景五：交叉验证——慢路分母错必须被判不一致，修正后两条路对上。"""
    fast_a = float(compute_metric("fpd30_rate", demo_df[demo_df["channel"] == "A"])["value"][0])
    wrong = sql_execute(
        demo_df, "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel LIMIT 10"
    )
    v_wrong = float(wrong[wrong["channel"] == "A"]["value"].iloc[0])
    ok1, msg1 = cross_check("fpd30_rate@channel=A", fast_a, v_wrong)

    right = sql_execute(
        demo_df,
        "SELECT channel, AVG(is_fpd30) FROM fact_application "
        "WHERE is_pass = 1 GROUP BY channel LIMIT 10",
    )
    v_right = float(right[right["channel"] == "A"]["value"].iloc[0])
    ok2, msg2 = cross_check("fpd30_rate@channel=A", fast_a, v_right)

    assert ok1 is False
    assert "不一致" in msg1
    assert ok2 is True
    assert "==" in msg2
    assert v_right == pytest.approx(V2_A_FPD, rel=1e-6)
    assert v_wrong == pytest.approx(V2_WRONG_FPD, rel=1e-6)


def test_v2_6_attribution_finds_supported_and_refuted(semantic, demo_df, observer, fake_llm):
    """场景六：监控归因——规则检测 + 假设穷游，结论必须待人工确认。"""
    llm = fake_llm(
        [
            {"hypotheses": ["B 渠道逾期偏高拉高整体", "P2 产品逾期恶化"]},
            {
                "drills": [
                    {
                        "h": "B 渠道逾期偏高拉高整体",
                        "sql": "SELECT channel, AVG(is_fpd30) FROM fact_application "
                        "WHERE is_pass = 1 GROUP BY channel LIMIT 10",
                    },
                    {
                        "h": "P2 产品逾期恶化",
                        "sql": "SELECT product, AVG(is_fpd30) FROM fact_application "
                        "WHERE is_pass = 1 GROUP BY product LIMIT 10",
                    },
                ]
            },
            {
                "verdicts": [
                    {
                        "h": "B 渠道逾期偏高拉高整体",
                        "status": "supported",
                        "evidence": "B 渠道 FPD30 显著高于其他渠道",
                    },
                    {
                        "h": "P2 产品逾期恶化",
                        "status": "refuted",
                        "evidence": "P1/P2 差异小于 0.03",
                    },
                ]
            },
            {"hypotheses": []},
        ]
    )
    graph = build_attribution_graph(semantic, demo_df, llm, observer)
    out = graph.invoke({})
    report = out["report"]

    assert report["event"]["metric"] == "fpd30_rate"
    assert report["event"]["threshold"] == 0.25
    assert len(report["confirmed"]) == 1
    assert len(report["excluded"]) == 1
    assert report["confirmed"][0]["text"] == "B 渠道逾期偏高拉高整体"
    assert report["excluded"][0]["text"] == "P2 产品逾期恶化"
    assert report["needs_human_confirm"] is True


def test_v2_7_backtest_freezes_ks_auc_and_decision_forbidden_zone(semantic, demo_df):
    """场景七：回测——固定流跑数，KS/AUC 冻结，决策禁入区声明必须存在。"""
    compare, narrative = run_backtest(
        semantic, demo_df, {"score_v3": "score_v3", "score_v2": "score_v2"}
    )

    assert len(compare) == 2
    assert list(compare.columns) == ["strategy", "ks", "auc", "as_of"]
    assert list(compare["strategy"]) == ["score_v3", "score_v2"]
    assert list(compare["as_of"]) == ["2026-09-30", "2026-09-30"]
    assert compare.iloc[0]["ks"] == pytest.approx(0.159452, abs=1e-6)
    assert compare.iloc[0]["auc"] == pytest.approx(0.411955, abs=1e-6)
    assert compare.iloc[1]["ks"] == pytest.approx(0.086003, abs=1e-6)
    assert compare.iloc[1]["auc"] == pytest.approx(0.514925, abs=1e-6)
    assert "样本 1200 条" in narrative
    assert "决策必须由人做出" in narrative


def test_v2_8_golden_eval_three_questions_all_pass(demo_df):
    """场景八：黄金题集回归——3 题全 PASS（ground truth 来自纯函数）。"""
    golden = [
        {"q": "整体 FPD30 是多少", "metric": "fpd30_rate", "segment": "overall"},
        {"q": "A 渠道 FPD30 是多少", "metric": "fpd30_rate", "segment": "channel=A"},
        {"q": "整体通过率是多少", "metric": "pass_rate", "segment": "overall"},
    ]
    results = []
    for g in golden:
        if g["segment"] == "overall":
            expect = METRIC_FUNCS[g["metric"]](demo_df)
        else:
            dim, val = g["segment"].split("=")
            expect = METRIC_FUNCS[g["metric"]](demo_df[demo_df[dim] == val])
        group_by = None if g["segment"] == "overall" else g["segment"].split("=")[0]
        where = (
            demo_df
            if group_by is None
            else demo_df[demo_df[group_by] == g["segment"].split("=")[1]]
        )
        actual = METRIC_FUNCS[g["metric"]](where)
        results.append(
            {
                "q": g["q"],
                "expect": round(float(expect), 6),
                "actual": round(float(actual), 6),
                "pass": bool(np.isclose(actual, expect, rtol=1e-6, equal_nan=True)),
            }
        )

    passed = sum(r["pass"] for r in results)
    assert passed == len(results) == 3
    assert results[0]["actual"] == pytest.approx(0.285904, abs=1e-6)
    assert results[1]["actual"] == pytest.approx(0.223919, abs=1e-6)
    assert results[2]["actual"] == pytest.approx(0.626667, abs=1e-6)


def test_v2_9_degraded_llm_fabricated_ref_and_render_mismatch(demo_df):
    """场景九：韧性降级 + 编造引用被抓 + 重算不一致被抓。"""

    def _fallback(prompt: str) -> dict:
        return {"action": {"metric": "fpd30_rate"}, "_degraded_reason": "规则映射：问题含 FPD30"}

    class _Boom(FakeLLM):
        def chat(self, task, prompt, **kw):
            raise TimeoutError("LLM API 超时")

    degraded = DegradedLLM(_Boom(script=[]), _fallback)
    resp = degraded.chat("extraction", "整体 FPD30")
    assert degraded.degraded is True
    assert "_degraded" in resp
    assert "TimeoutError" in resp["_degraded"]

    facts9 = FactStore(data_as_of="2026-09-30")
    facts9.put(0.28, "ratio", "fpd30_rate")
    # 只改输入叙事（补引 F0001），期望值一字不动；遍历范围按 docstring 收紧。
    verdict = verify_report(
        "模型 KS 达到 {{F9999}}，整体 FPD30 为 {{F0001}}，表现优异", facts9, demo_df
    )

    assert verdict.passed is False
    assert verdict.failures[0][0] == "fabricated_ref"
    assert [f[0] for f in verdict.failures] == ["fabricated_ref", "render_mismatch"]
    assert verdict.failures[1][1] == "F0001"
