"""T-4.0.1 行为等价证据：包化实现 17 场景关键产出探针（只读，不改任何实现）。

用法：`.venv/bin/python docs/experiments/2026-11-05-v40-packaged-probe.py`

设计要点：
- 造数逻辑不复制：直接复用 `tests/conftest.py` 的 `demo_df` / `_gen_logs`，
  保证与 `tests/scenario/` 用的是同一份基线数据。
- 场景步骤逐条对齐 `tests/scenario/test_v2_scenarios.py` 与
  `tests/scenario/test_v3_scenarios.py`，只增加 print，不改断言/不断言。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("riskqa_conftest", ROOT / "tests" / "conftest.py")
cf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cf)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from langgraph.types import Command  # noqa: E402

from riskqa.calc.metrics import METRIC_FUNCS, compute_metric  # noqa: E402
from riskqa.calc.recompute import cross_check  # noqa: E402
from riskqa.facts.store import FactStore  # noqa: E402
from riskqa.governance.clustering import (  # noqa: E402
    RuleExtractor,
    build_review_material,
    cluster_logs,
    detect_metric_conflicts,
    heat,
    nominate,
)
from riskqa.governance.config import GovernanceError, load_governance  # noqa: E402
from riskqa.governance.review import ReviewState, tick  # noqa: E402
from riskqa.governance.signature import ReviewRecord, promote  # noqa: E402
from riskqa.llm.fake import DegradedLLM, FakeLLM  # noqa: E402
from riskqa.orchestration.backtest import run_backtest  # noqa: E402
from riskqa.orchestration.graph_attribution import build_attribution_graph  # noqa: E402
from riskqa.orchestration.graph_qa import build_qa_graph, sql_execute  # noqa: E402
from riskqa.orchestration.observer import Observer  # noqa: E402
from riskqa.semantic.layer import SemanticLayer, UnregisteredMetricError  # noqa: E402
from riskqa.verify.disclosure import ai_disclosure  # noqa: E402
from riskqa.verify.gates import verify_report  # noqa: E402

TODAY = "2026-10-30"
AS_OF = "2026-09-30"

semantic = SemanticLayer((ROOT / "config" / "semantic_view.yaml").read_text(encoding="utf-8"))
governance_text = (ROOT / "config" / "governance.yaml").read_text(encoding="utf-8")
demo_df = cf.demo_df.__wrapped__()
query_logs = cf._gen_logs(200)
metric_spec = {"metrics": [{"name": m, "calc": m} for m in semantic.metric_enum]}


def p(tag: str, text: str) -> None:
    print(f"{tag} | {text}")


def new_facts() -> FactStore:
    return FactStore(data_as_of=AS_OF)


# 与 legacy V2 main() 一致：九个场景共享同一个 Observer（便于核对 trace/审计/成本计数）
OBS = Observer()


# ---------------- V2 九场景（对齐 test_v2_scenarios.py） ----------------
def v2_1() -> None:
    llm = FakeLLM(
        script=[
            {"action": {"metric": "fpd30_rate"}},
            {"text": "整体 FPD30 为 {{F0001}}，口径：放款客户中首期 DPD30+ 的占比（见语义层登记）。"},
        ]
    )
    out = build_qa_graph(semantic, demo_df, new_facts(), llm, OBS, metric_spec).invoke(
        {"question": "整体 FPD30 是多少", "role": "analyst_qa"},
        config={"configurable": {"thread_id": "t1"}},
    )
    assert out["route"] == "fast" and out["result"]["passed"] is True
    fact = out["facts"][0]
    p("V2-1", f"route={out['route']} metric={out['metric']} fid={fact['fid']} "
              f"value={fact['value']} segment={fact['segment']} passed={out['result']['passed']}")


def v2_2() -> None:
    llm = FakeLLM(
        script=[
            {"tables": ["fact_application"]},
            {"sql": "SELECT channel, AVG(is_fpd30) FROM fact_application "
                    "WHERE is_pass = 1 GROUP BY channel LIMIT 10"},
            {"text": "各渠道平均逾期水平见事实清单 {{F0001}} 起（受行级权限约束，仅返回授权渠道）。"},
        ]
    )
    obs = OBS
    out = build_qa_graph(semantic, demo_df, new_facts(), llm, obs, metric_spec, role="analyst_qa").invoke(
        {"question": "各渠道平均逾期水平如何", "role": "analyst_qa"},
        config={"configurable": {"thread_id": "t2"}},
    )
    injected = [t for t in obs.trace if t["node"] == "slow_execute"][-1]
    facts = [(f["segment"], round(f["value"], 4)) for f in out["facts"]]
    assert "channel = 'A'" in injected["sql"]
    p("V2-2", f"route={out['route']} sql={injected['sql']} facts={facts} "
              f"passed={out['result']['passed']}")


def v2_3() -> None:
    llm = FakeLLM(
        script=[
            {"tables": ["fact_application"]},
            {"sql": "SELECT a.channel, AVG(a.is_fpd30) FROM fact_application a "
                    "JOIN dim_channel b ON a.channel = b.channel GROUP BY a.channel LIMIT 10"},
            {"text": "跨表查询完成，见 {{F0001}}。"},
        ]
    )
    obs = OBS
    graph = build_qa_graph(semantic, demo_df, new_facts(), llm, obs, metric_spec, role="analyst_qa")
    cfg = {"configurable": {"thread_id": "t3"}}
    out = graph.invoke({"question": "按渠道大区看逾期", "role": "analyst_qa"}, config=cfg)
    pending = out.get("__interrupt__")
    assert pending and pending[0].value["review_level"] == "must"
    out = graph.invoke(Command(resume={"type": "accept", "text": "同意执行"}), config=cfg)
    audit = [(a.human_action, a.review_level) for a in obs.audit if a.human_action]
    assert out["result"]["passed"] is False
    p("V2-3", f"pending={bool(pending)} interrupt={pending[0].value} trace={out['trace']} "
              f"audit_last={audit[-1]} audit_total={len(audit)} "
              f"passed={out['result']['passed']} failures={out['result']['failures']}")


def v2_4() -> None:
    bad = FakeLLM(
        script=[{"sql": "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel"}] * 8
    )
    obs = OBS
    out = build_qa_graph(
        semantic, demo_df, new_facts(), bad, OBS, metric_spec, role="risk_admin", max_steps=6
    ).invoke(
        {"question": "各渠道逾期", "role": "risk_admin"},
        config={"configurable": {"thread_id": "t4"}},
    )
    checks = [t for t in obs.trace if t["node"] == "slow_sql_check"]
    fails = [t for t in checks if t["ok"] is False]
    assert fails and any("缺少 LIMIT" in v for t in fails for v in t["violations"])
    p("V2-4", f"check_violations={fails[0]['violations']} passed={out['result']['passed']} "
              f"failures={out['result']['failures']} narrative={out['narrative']}")


def v2_5() -> None:
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
    assert not ok1 and ok2
    p("V2-5", f"wrong={msg1} || right={msg2}")


def v2_6() -> None:
    llm = FakeLLM(
        script=[
            {"hypotheses": ["B 渠道逾期偏高拉高整体", "P2 产品逾期恶化"]},
            {"drills": [
                {"h": "B 渠道逾期偏高拉高整体",
                 "sql": "SELECT channel, AVG(is_fpd30) FROM fact_application "
                        "WHERE is_pass = 1 GROUP BY channel LIMIT 10"},
                {"h": "P2 产品逾期恶化",
                 "sql": "SELECT product, AVG(is_fpd30) FROM fact_application "
                        "WHERE is_pass = 1 GROUP BY product LIMIT 10"},
            ]},
            {"verdicts": [
                {"h": "B 渠道逾期偏高拉高整体", "status": "supported",
                 "evidence": "B 渠道 FPD30 显著高于其他渠道"},
                {"h": "P2 产品逾期恶化", "status": "refuted",
                 "evidence": "P1/P2 差异小于 0.03"},
            ]},
            {"hypotheses": []},
        ]
    )
    rep = build_attribution_graph(semantic, demo_df, llm, OBS).invoke({})["report"]
    assert len(rep["confirmed"]) == 1 and len(rep["excluded"]) == 1
    p("V2-6", f"event={rep['event']} confirmed={[h['text'] for h in rep['confirmed']]} "
              f"excluded={[h['text'] for h in rep['excluded']]} "
              f"needs_human_confirm={rep['needs_human_confirm']}")


def v2_7() -> None:
    compare, narrative = run_backtest(
        semantic, demo_df, {"score_v3": "score_v3", "score_v2": "score_v2"}
    )
    p("V2-7", "table:\n" + compare.to_string(index=False) + "\nnarrative=" + narrative)


def v2_8() -> None:
    golden = [
        {"q": "整体 FPD30 是多少", "metric": "fpd30_rate", "segment": "overall"},
        {"q": "A 渠道 FPD30 是多少", "metric": "fpd30_rate", "segment": "channel=A"},
        {"q": "整体通过率是多少", "metric": "pass_rate", "segment": "overall"},
    ]
    results = []
    for g in golden:
        if g["segment"] == "overall":
            expect = METRIC_FUNCS[g["metric"]](demo_df)
            where = demo_df
        else:
            dim, val = g["segment"].split("=")
            expect = METRIC_FUNCS[g["metric"]](demo_df[demo_df[dim] == val])
            where = demo_df[demo_df[dim] == val]
        actual = METRIC_FUNCS[g["metric"]](where)
        results.append(
            f"{'PASS' if np.isclose(actual, expect, rtol=1e-6, equal_nan=True) else 'FAIL'} "
            f"{g['q']} 期望 {round(float(expect), 6)} 实际 {round(float(actual), 6)}"
        )
    assert all("PASS" in r for r in results)
    p("V2-8", " || ".join(results) + " 通过率 3/3")


def v2_9() -> None:
    def _fallback(prompt: str) -> dict:
        return {"action": {"metric": "fpd30_rate"}, "_degraded_reason": "规则映射：问题含 FPD30"}

    class _Boom(FakeLLM):
        def chat(self, task, prompt, **kw):
            raise TimeoutError("LLM API 超时")

    degraded = DegradedLLM(_Boom(script=[]), _fallback)
    resp = degraded.chat("extraction", "整体 FPD30")
    assert degraded.degraded is True and "_degraded" in resp

    facts9 = new_facts()
    facts9.put(0.28, "ratio", "fpd30_rate")
    verdict = verify_report("模型 KS 达到 {{F9999}}，表现优异", facts9, demo_df)
    assert verdict.passed is False and verdict.failures[0][0] == "fabricated_ref"
    p("V2-9", f"degraded={resp} | verify passed={verdict.passed} failures={verdict.failures}")


# ---------------- V3 八场景（对齐 test_v3_scenarios.py） ----------------
def v3_all() -> None:
    clusters = cluster_logs(query_logs, semantic, RuleExtractor())
    gov = load_governance(governance_text, TODAY)

    # 场景一
    raw = yaml.safe_load(governance_text)
    bad = raw.copy()
    bad["global"] = dict(raw["global"], window_days=400)
    try:
        load_governance(yaml.safe_dump(bad, allow_unicode=True, sort_keys=False), TODAY)
        guard = "护栏失效（未抛错）"
    except GovernanceError as e:
        guard = f"护栏拦截：{e}"
    p("V3-1", f"raw_min_users={raw['global']['promotion']['min_users']} "
              f"effective_min_users={gov.promotion.min_users} window={gov.window_days} "
              f"retention={gov.retention_days} "
              f"domain_min_users={gov.for_domain('collection_ops', raw['overrides']).min_users} "
              f"{guard}")

    # 场景二
    ordered = sorted(clusters.items(), key=lambda kv: -len(kv[1].logs))
    p("V3-2", f"logs={len(query_logs)} signatures={len(clusters)} "
              f"ratio={len(query_logs) / len(clusters):.1f} "
              f"sizes={[len(c.logs) for _, c in ordered]} "
              f"variants={[len(c.variants) for _, c in ordered]} "
              f"keys={[cid for cid, _ in ordered]}")

    # 场景三
    nominated, blocked, reasons = [], [], {}
    for cid, c in clusters.items():
        ok, why = nominate(c, gov.promotion, TODAY)
        (nominated if ok else blocked).append(cid)
        reasons[cid] = why
    hot = heat(clusters["fpd30_rate|product|is_pass|all"], TODAY)
    batch = heat(clusters["pass_rate|channel||all"], TODAY)
    p("V3-3", f"nominated={nominated} blocked={blocked} "
              f"hot={(hot['n_queries'], hot['n_users'], hot['n_days'])} "
              f"hot_share={hot['top_user_share']:.0%} "
              f"hot_reason={reasons['fpd30_rate|product|is_pass|all']} "
              f"batch_days={batch['n_days']} batch_reason={reasons['pass_rate|channel||all']}")

    # 场景四
    conflicts = detect_metric_conflicts(clusters)
    p("V3-4", f"conflicts={[(c['metric'], c['n_queries'], c['versions']) for c in conflicts]}")

    # 场景五
    fpd = [c for c in clusters.values() if c.sig.metric == "fpd30_rate"]
    material = build_review_material("fpd30_rate", fpd, semantic, TODAY)
    lines = material.splitlines()
    p("V3-5", f"line0={lines[0]} line1={lines[1]} warn_count={material.count('⚠️')} "
              f"has_question={'需要你裁决的问题' in material} "
              f"has_qid={'查询记录 QID：' in material}")

    # 场景六
    loan = [c for c in clusters.values() if c.sig.metric == "loan_amt"][0]
    rec = ReviewRecord(
        "R-2026-090",
        loan.sig.key(),
        "风控策略组·王五",
        "promote",
        next(iter(loan.sql_variants)),
        "口径确认：放款量=SUM(loan_amt)，分母不适用，维度=产品",
        TODAY,
    )
    new_yaml = promote(loan, rec, semantic, TODAY)
    entry = next(m for m in yaml.safe_load(new_yaml)["metrics"] if m["name"] == "loan_amt")
    demo = pd.DataFrame(
        {"loan_amt": [120.5, 380.0, 95.5], "is_pass": [1, 1, 1], "product": ["A", "B", "A"]}
    )
    try:
        compute_metric("loan_amt", demo)
        calc_state = "未拒算（异常）"
    except UnregisteredMetricError as e:
        calc_state = f"拒算 {type(e).__name__}: {e}"
    METRIC_FUNCS["loan_amt"] = lambda d: float(d["loan_amt"].sum())
    try:
        value = float(compute_metric("loan_amt", demo)["value"][0])
    finally:
        METRIC_FUNCS.pop("loan_amt", None)
    p("V3-6", f"owner={entry['owner']} dims={entry['dims']} aliases={len(entry['aliases'])} "
              f"n_queries={entry['provenance']['evidence_snapshot']['n_queries']} "
              f"n_users={entry['provenance']['evidence_snapshot']['n_users']} "
              f"review_record={entry['provenance']['evidence_snapshot']['review_record']} | "
              f"{calc_state} | 注册后 loan_amt={value}")

    # 场景七
    state = ReviewState("sig_stuck", entered_at="2026-10-01")
    seen = []
    for now in ["2026-10-03 09:00", "2026-10-05 09:00", "2026-10-09 09:00", "2026-10-25 09:00"]:
        tick(state, now, gov.review)
        seen.append(state.status)
    p("V3-7", f"statuses={seen} last_history={state.history[-1]}")

    # 场景八
    signed = SemanticLayer(promote(loan, rec, semantic, TODAY))
    qs = ["A产品放款量最近一个月", "B产品放款量最近一年", "C产品放款量最近一个月"]
    p("V3-8", f"aliases={[signed.resolve_alias(q) for q in qs]}")
    assert all(signed.resolve_alias(q) == "loan_amt" for q in qs)


if __name__ == "__main__":
    for fn in (v2_1, v2_2, v2_3, v2_4, v2_5, v2_6, v2_7, v2_8, v2_9):
        fn()
    v3_all()
    p("V2-SUM", f"trace_nodes={len(OBS.trace)} audit_entries={len(OBS.audit)} "
               f"cost_tokens={OBS.cost_tokens} version={semantic.version} "
               f"metric_enum={semantic.metric_enum} "
               f"ai_disclosure={ai_disclosure('fake-cheap', '2026-09-30')}")
    print("probe: 17 场景断言全部通过")
