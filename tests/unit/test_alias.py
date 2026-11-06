"""alias 同义词归一单测（T-4.1.1）。

覆盖 config/semantic_view.yaml 中全部指标名与 aliases（口语归一，US-02）；
未命中返回 None 交由慢路提名（P-04：不猜不填）。
路由层准确率 ≥95%（黄金题集）顺延 T-4.1.8 实测，本文件只做单元级验证。
"""

from __future__ import annotations

from riskqa.semantic.alias import build_alias_index, match_question, resolve_token
from riskqa.semantic.check import _check
from riskqa.semantic.layer import SemanticLayer


def test_index_covers_all_metrics_and_aliases(semantic: SemanticLayer):
    """索引必须覆盖配置里每一个指标名与每一条 alias，且指向正确指标。"""
    idx = build_alias_index(semantic.metrics)
    for name, m in semantic.metrics.items():
        assert idx[name.lower()] == name
        for a in m.get("aliases", []):
            assert idx[a.lower()] == name


def test_resolve_every_alias_and_name(semantic: SemanticLayer):
    """逐条 resolve：每条 alias 与每个指标名都能整词归一。"""
    idx = semantic.alias_index()
    for name, m in semantic.metrics.items():
        assert resolve_token(idx, name) == name
        for a in m.get("aliases", []):
            assert resolve_token(idx, a) == name


def test_resolve_normalizes_case_and_whitespace(semantic: SemanticLayer):
    idx = semantic.alias_index()
    assert resolve_token(idx, " FPD30 ") == "fpd30_rate"
    assert resolve_token(idx, "Pass") == "pass_rate"
    assert resolve_token(idx, "首期逾期率") == "fpd30_rate"


def test_resolve_unmapped_returns_none(semantic: SemanticLayer):
    """未登记词不猜不填：返回 None 进慢路提名（坏账率未登记，P-04）。"""
    idx = semantic.alias_index()
    assert resolve_token(idx, "坏账率") is None
    assert resolve_token(idx, "申请量") is None
    assert resolve_token(idx, "") is None


def test_match_question_spoken_phrases(semantic: SemanticLayer):
    """口语问句归一（golden_set 问法）：含别名/指标名的问句命中正确指标。"""
    cases = {
        "首期逾期率多少？": "fpd30_rate",  # Q003：考 alias 归一
        "整体 FPD30 是多少？": "fpd30_rate",  # Q001
        "各产品通过率是多少？": "pass_rate",  # Q004
        "2026-08 的 KS 是多少？": "ks",  # Q005
        "整体 AUC 是多少？": "auc",  # Q006
        "整体 PSI 是多少？": "psi",  # Q007
    }
    for q, want in cases.items():
        assert match_question(semantic.metrics, q) == want


def test_match_question_unregistered_returns_none(semantic: SemanticLayer):
    """映射不到进慢路提名：申请量/坏账率/非指标问题一律 None。"""
    for q in ("各渠道的申请量是多少？", "再帮我算下坏账率", "风控负责人的手机号是多少？"):
        assert match_question(semantic.metrics, q) is None


def test_match_question_multi_metric_yaml_order(semantic: SemanticLayer):
    """同句命中多个指标时取 YAML 登记顺序的第一个（现状行为固化，不改语义）。"""
    assert match_question(semantic.metrics, "整体 FPD30 和整体通过率各是多少？") == "fpd30_rate"


def test_alias_conflict_flagged_by_semantic_check():
    """同一 alias 指向两个指标：semantic-check 必须报错（P-08 双写防护）。"""
    yaml_text = """
version: "9.9"
metrics:
  - name: m_a
    desc: x
    unit: ratio
    dims: [channel]
    calc: fpd30_rate
    aliases: [同名]
    owner: t
    signed_at: "2026-01-01"
    changelog: []
  - name: m_b
    desc: x
    unit: ratio
    dims: [channel]
    calc: pass_rate
    aliases: [同名]
    owner: t
    signed_at: "2026-01-01"
    changelog: []
  - {name: m_c, desc: x, unit: ratio, dims: [channel], calc: ks, owner: t, signed_at: "2026-01-01", changelog: []}
  - {name: m_d, desc: x, unit: ratio, dims: [channel], calc: auc, owner: t, signed_at: "2026-01-01", changelog: []}
  - {name: m_e, desc: x, unit: ratio, dims: [channel], calc: psi, owner: t, signed_at: "2026-01-01", changelog: []}
tables:
  - {name: fact_application, columns: [apply_id]}
row_policies: {}
"""
    errs = _check(SemanticLayer(yaml_text))
    assert any("同名" in e and "同时指向" in e for e in errs)
