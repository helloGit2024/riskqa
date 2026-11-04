# -*- coding: utf-8 -*-
"""V3 八场景迁移（来源：legacy/问数Agent_持续运营V3.py L610—L710）。

golden 值冻结于 2026-11-04、pandas 2.2.3；测试不 import legacy。
"""

from __future__ import annotations

import copy

import pytest
import yaml

from riskqa.calc.metrics import METRIC_FUNCS, compute_metric
from riskqa.governance.clustering import (
    RuleExtractor,
    build_review_material,
    cluster_logs,
    detect_metric_conflicts,
    heat,
    nominate,
)
from riskqa.governance.config import GovernanceError, load_governance
from riskqa.governance.review import ReviewState, tick
from riskqa.governance.signature import ReviewRecord, promote
from riskqa.semantic.layer import SemanticLayer, UnregisteredMetricError

TODAY = "2026-10-30"


@pytest.fixture(scope="module")
def clusters(semantic, query_logs):
    return cluster_logs(query_logs, semantic, RuleExtractor())


def _promote_loan(clusters, semantic) -> SemanticLayer:
    loan = next(c for c in clusters.values() if c.sig.metric == "loan_amt")
    rec = ReviewRecord("R-2026-090", loan.sig.key(), "风控策略组·王五", "promote",
                       next(iter(loan.sql_variants)),
                       "口径确认：放款量=SUM(loan_amt)，分母不适用，维度=产品",
                       "2026-10-30")
    return SemanticLayer(promote(loan, rec, semantic, TODAY))


def test_v3_1_governance_three_layers_and_guardrails(
        governance_text, governance_cfg):
    """场景一：治理三层配置——域覆盖 + 临时调整生效，护栏拦截非法阈值。"""
    raw = yaml.safe_load(governance_text)
    assert raw["global"]["promotion"]["min_users"] == 3
    assert raw["global"]["window_days"] == 30
    assert raw["global"]["retention_days"] == 365
    assert raw["global"]["review"]["sla_hours"] == 72

    assert governance_cfg.promotion.min_users == 2          # 临时调低在 TODAY 生效
    assert governance_cfg.window_days == 30
    assert governance_cfg.retention_days == 365
    assert governance_cfg.for_domain(
        "collection_ops", raw["overrides"]).min_users == 5  # 第二层主题域覆盖

    bad = copy.deepcopy(raw)
    bad["global"]["window_days"] = 400
    bad_text = yaml.safe_dump(bad, allow_unicode=True, sort_keys=False)
    with pytest.raises(GovernanceError, match="热度窗口"):
        load_governance(bad_text, TODAY)


def test_v3_2_clustering_compresses_199_logs_to_6_signatures(clusters, query_logs):
    """场景二：意图签名归并——199 条日志 → 6 签名，压缩比 33.2×。"""
    assert len(query_logs) == 199
    assert len(clusters) == 6
    assert round(len(query_logs) / len(clusters), 1) == 33.2

    ordered = sorted(clusters.values(), key=lambda c: -len(c.logs))
    assert [len(c.logs) for c in ordered] == [92, 47, 30, 16, 12, 2]
    assert [len(c.variants) for c in ordered] == [6, 5, 1, 2, 1, 1]
    assert {c.sig.key() for c in clusters.values()} == {
        "loan_amt|product|product|all",
        "fpd30_rate|channel|is_pass|all",
        "fpd30_rate|product|is_pass|all",
        "fpd30_rate|channel||all",
        "pass_rate|channel||all",
        "pass_rate|vintage||all",
    }


def test_v3_3_heat_nominates_four_and_blocks_two(clusters, governance_cfg):
    """场景三：热度三维度——4 个签名进评审队列，2 个被防刷量/批量拦截。"""
    nominated, blocked = [], []
    reasons = {}
    for cid, cluster in clusters.items():
        ok, why = nominate(cluster, governance_cfg.promotion, TODAY)
        (nominated if ok else blocked).append(cid)
        reasons[cid] = why
        assert heat(cluster, TODAY)["n_queries"] == len(cluster.logs)

    assert len(nominated) == 4
    assert len(blocked) == 2

    hot = clusters["fpd30_rate|product|is_pass|all"]
    h = heat(hot, TODAY)
    assert (h["n_queries"], h["n_users"], h["n_days"]) == (30, 6, 28)
    assert h["top_user_share"] == pytest.approx(0.833, abs=1e-3)
    assert "单人占比" in reasons["fpd30_rate|product|is_pass|all"]

    batch = heat(clusters["pass_rate|channel||all"], TODAY)
    assert batch["concentrated"] is True
    assert "会议批量" in reasons["pass_rate|channel||all"]


def test_v3_4_conflict_detection_exact_and_zero_false_positive(clusters):
    """场景四：口径指纹冲突——fpd30_rate 精确检出 2 种口径，其余指标零误报。"""
    conflicts = detect_metric_conflicts(clusters)
    assert len(conflicts) == 1
    mc = conflicts[0]
    assert mc["metric"] == "fpd30_rate"
    assert mc["n_queries"] == 93
    assert mc["versions"] == {
        "AVG(is_fpd30) # is_pass=?": 77,
        "AVG(is_fpd30) # NOWHERE": 16,
    }
    assert {c["metric"] for c in conflicts} == {"fpd30_rate"}


def test_v3_5_review_material_has_panorama_and_decision_question(clusters, semantic):
    """场景五：Owner 评审材料——全景数字 + 只回答待裁问题，标出异类口径。"""
    fpd = [c for c in clusters.values() if c.sig.metric == "fpd30_rate"]
    material = build_review_material("fpd30_rate", fpd, semantic, TODAY)
    lines = material.splitlines()

    assert lines[0] == "# 待评审指标：fpd30_rate"
    assert lines[1] == ("## 全景（93 次查询，10 位用户，28 天，"
                        "8 种问法，3 个签名，2 种口径）")
    assert "需要你裁决的问题" in material
    assert material.count("⚠️") == 1
    assert "查询记录 QID：" in material


def test_v3_6_promotion_signs_yaml_and_requires_calc_registration(clusters, semantic):
    """场景六：晋升签字——写 YAML + evidence 快照 + alias 回填；纯函数未注册拒算。"""
    new_yaml = promote(
        next(c for c in clusters.values() if c.sig.metric == "loan_amt"),
        ReviewRecord("R-2026-090", "loan_amt|product|product|all",
                     "风控策略组·王五", "promote",
                     "SELECT product, SUM(loan_amt) AS v FROM fact_application "
                     "WHERE product='A' GROUP BY product LIMIT 10",
                     "口径确认：放款量=SUM(loan_amt)", "2026-10-30"),
        semantic, TODAY)
    parsed = yaml.safe_load(new_yaml)
    assert parsed["version"] == semantic.version
    entry = next(m for m in parsed["metrics"] if m["name"] == "loan_amt")
    assert entry["owner"] == "风控策略组·王五"
    assert entry["signed_at"] == "2026-10-30"
    assert entry["dims"] == ["product"]
    assert len(entry["aliases"]) == 6
    assert entry["provenance"]["evidence_snapshot"]["n_queries"] == 92
    assert entry["provenance"]["evidence_snapshot"]["n_users"] == 9
    assert entry["provenance"]["evidence_snapshot"]["review_record"] == "R-2026-090"

    signed = SemanticLayer(new_yaml)
    demo = _loan_demo_frame()
    try:
        with pytest.raises(UnregisteredMetricError):
            compute_metric("loan_amt", demo)
        # 迁移差异：legacy V3 断言 ValueError，新类型 UnregisteredMetricError 不是其子类
        METRIC_FUNCS["loan_amt"] = lambda d: float(d["loan_amt"].sum())
        assert float(compute_metric("loan_amt", demo)["value"][0]) == pytest.approx(596.0)
    finally:
        METRIC_FUNCS.pop("loan_amt", None)

    assert "loan_amt" in signed.alias_index().values()


def test_v3_7_review_escalation_chain_to_shelved(clusters, governance_cfg):
    """场景七：评审升级链——SLA 72h → 2× 升级 → 7× 组织搁置。"""
    state = ReviewState("loan_amt|product|product|all", entered_at="2026-10-01")
    seen = []
    for now in ["2026-10-03 09:00", "2026-10-05 09:00",
                "2026-10-09 09:00", "2026-10-25 09:00"]:
        tick(state, now, governance_cfg.review)
        seen.append(state.status)

    assert seen == ["pending_review", "reminded", "overdue", "shelved"]
    assert len(state.history) == 4
    assert state.history[-1] == "2026-10-25 09:00 → shelved"


def test_v3_8_promoted_aliases_hit_natural_questions(clusters, semantic):
    """场景八：alias 回填——三种口语问法都能命中晋升后的 loan_amt。"""
    signed = _promote_loan(clusters, semantic)
    questions = [
        "A产品放款量最近一个月",
        "B产品放款量最近一年",
        "C产品放款量最近一个月",
    ]
    assert [signed.resolve_alias(q) for q in questions] == ["loan_amt"] * 3


def _loan_demo_frame():
    import pandas as pd
    return pd.DataFrame({
        "loan_amt": [120.5, 380.0, 95.5],
        "is_pass": [1, 1, 1],
        "product": ["A", "B", "A"],
    })
