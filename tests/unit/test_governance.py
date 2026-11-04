# -*- coding: utf-8 -*-
"""治理层单测：SQL 归一、口径指纹、热度与提名。"""

from __future__ import annotations

import pytest

from riskqa.governance.clustering import (
    RuleExtractor,
    caliber_fingerprint,
    cluster_logs,
    heat,
    nominate,
    normalize_sql,
)

TODAY = "2026-10-30"


def test_normalize_sql_replaces_literals_and_collapses_whitespace():
    sql = ("SELECT  product, AVG(is_fpd30) AS v\nFROM t WHERE product='A' "
           "AND is_pass=1 GROUP BY product LIMIT 10")
    assert normalize_sql(sql) == (
        "SELECT product, AVG(is_fpd30) AS v FROM t "
        "WHERE product=? AND is_pass=? GROUP BY product LIMIT ?")


def test_caliber_fingerprint_ignores_parameter_variants():
    a = ("SELECT product, AVG(is_fpd30) FROM t WHERE product='A' "
         "GROUP BY product LIMIT 10")
    b = ("SELECT product, AVG(is_fpd30) FROM t WHERE product='B' "
         "GROUP BY product LIMIT 10")
    assert caliber_fingerprint(a) == caliber_fingerprint(b) == "AVG(is_fpd30) # product=?"

    no_where = "SELECT product, AVG(is_fpd30) FROM t GROUP BY product LIMIT 10"
    assert caliber_fingerprint(no_where) == "AVG(is_fpd30) # NOWHERE"
    assert caliber_fingerprint(a) != caliber_fingerprint(no_where)


def test_heat_and_nominate_on_frozen_baseline(semantic, query_logs, governance_cfg):
    clusters = cluster_logs(query_logs, semantic, RuleExtractor())

    hot = clusters["fpd30_rate|product|is_pass|all"]
    h = heat(hot, TODAY)
    assert (h["n_queries"], h["n_users"], h["n_days"]) == (30, 6, 28)
    assert h["top_user_share"] == pytest.approx(0.833, abs=1e-3)
    ok, why = nominate(hot, governance_cfg.promotion, TODAY)
    assert ok is False and "单人占比" in why

    batch = clusters["pass_rate|channel||all"]
    assert heat(batch, TODAY)["concentrated"] is True
    ok, why = nominate(batch, governance_cfg.promotion, TODAY)
    assert ok is False and "会议批量" in why

    steady = clusters["loan_amt|product|product|all"]
    ok, why = nominate(steady, governance_cfg.promotion, TODAY)
    assert ok is True and "达标" in why
