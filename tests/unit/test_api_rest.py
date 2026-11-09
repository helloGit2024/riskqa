"""facts / evidence / reviews / governance.candidates（T-4.1.5 第三笔：剩余 4 端点）。

数据全部预置到临时 ops.db：raw log 与事实落库属 T-4.2.1，本版用夹具直写验证读取链路。
"""

from __future__ import annotations

from datetime import date

from riskqa.store.db import connect
from riskqa.store.facts import FactRepo
from riskqa.store.query_log import QueryLogRepo
from riskqa.store.review import ReviewRepo

SQL_A = (
    "SELECT channel, AVG(is_fpd30) FROM fact_application "
    "WHERE is_pass = 1 GROUP BY channel LIMIT 10"
)
SQL_B = (
    "SELECT channel, AVG(is_pass) FROM fact_application WHERE is_pass = 1 GROUP BY channel LIMIT 10"
)
SQL_ALIAS = (
    "SELECT channel, AVG(is_fpd30) AS v FROM fact_application "
    "WHERE is_pass = 1 GROUP BY channel LIMIT 10"
)

ANALYST_HEADERS = {"X-RiskQA-Token": "tok-analyst"}
OWNER_HEADERS = {"X-RiskQA-Token": "tok-owner"}


def _seed(db_path):
    """预置：一条 raw log、两条事实、两张评审单（query + promotion）"""
    conn = connect(db_path)
    try:
        facts = FactRepo(conn)
        facts.insert(
            fid="F0001",
            value=0.4,
            unit="ratio",
            metric="fpd30_rate",
            segment="",
            source="fast",
            qid="Q0001",
        )
        facts.insert(
            fid="F0002",
            value=0.5,
            unit="ratio",
            metric="fpd30_rate",
            segment="channel=A",
            source="fast",
            qid="Q0001",
        )
        QueryLogRepo(conn).insert(
            qid="Q0001",
            question="各渠道 FPD30",
            sql=SQL_A,
            result_digest={"value": 0.4},
            user="u01",
            dept="风险策略部",
            ts="2026-10-20 10:00:00",
            confirmed_by=["u00"],
            signature="fpd30_rate|channel|is_pass|all",
        )
        ReviewRepo(conn).insert(
            rid="R0001",
            subject_type="query",
            subject_id="Q0001",
            level="must",
            assignee="u02",
            sla_due="2026-10-23 10:00:00",
            material={"kind": "explore", "qid": "Q0001"},
        )
    finally:
        conn.close()


def _seed_logs(db_path, rows: list[tuple[str, str, str]]) -> None:
    """rows: (qid, sql, user)"""
    conn = connect(db_path)
    try:
        repo = QueryLogRepo(conn)
        for i, (qid, sql, user) in enumerate(rows):
            repo.insert(
                qid=qid,
                question="各渠道 FPD30",
                sql=sql,
                result_digest={"value": 0.1},
                user=user,
                dept="风险策略部",
                ts=f"2026-10-{(i % 25) + 1:02d} 10:00:00",
            )
    finally:
        conn.close()


# ---------- GET /facts/{fid} ----------


def test_get_fact_returns_contract_fields(api_client, api_db_path):
    _seed(api_db_path)

    resp = api_client.get("/api/v1/facts/F0002", headers=ANALYST_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "fid": "F0002",
        "value": 0.5,
        "unit": "ratio",
        "segment": "channel=A",
        "metric": "fpd30_rate",
        "source": "fast",
        "qid": "Q0001",
        "created_at": body["created_at"],
    }
    assert body["created_at"]


def test_get_fact_missing_returns_404(api_client):
    """引用必须回表可查（P-07）：不存在即 404 + E_NOT_FOUND，不猜不填。"""
    resp = api_client.get("/api/v1/facts/F9999", headers=ANALYST_HEADERS)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "E_NOT_FOUND"


def test_get_fact_requires_token(api_client):
    assert api_client.get("/api/v1/facts/F0001").status_code == 401


# ---------- GET /evidence/{qid} ----------


def test_get_evidence_includes_sql_facts_and_review_chain(api_client, api_db_path):
    _seed(api_db_path)

    resp = api_client.get("/api/v1/evidence/Q0001", headers=ANALYST_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["qid"] == "Q0001"
    assert body["question"] == "各渠道 FPD30"
    assert body["sql"] == SQL_A
    assert body["sql_edited"] is False
    assert body["data_as_of"] == "2026-09-30"
    assert body["snapshot_digest"] == "testfilehash"
    assert [f["fid"] for f in body["facts"]] == ["F0001", "F0002"]
    assert body["facts"][0] == {
        "fid": "F0001",
        "value": 0.4,
        "unit": "ratio",
        "segment": "",
    }
    assert body["confirmed_by"] == ["u00"]
    assert len(body["review_chain"]) == 1
    assert body["review_chain"][0]["rid"] == "R0001"
    assert body["review_chain"][0]["sla_due"] == "2026-10-23 10:00:00"
    assert "material" not in body["review_chain"][0]


def test_get_evidence_missing_returns_404(api_client):
    resp = api_client.get("/api/v1/evidence/Q9999", headers=ANALYST_HEADERS)

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "E_NOT_FOUND"


# ---------- POST /reviews ----------


def test_submit_review_must_pends_until_owner_decides(api_client):
    """must → 201 + pending + sla_due；随后 Owner 可裁决（P-11）。"""
    resp = api_client.post(
        "/api/v1/reviews",
        json={
            "subject_type": "slow_result",
            "subject_id": "Q0002",
            "level": "must",
            "assignee": "u02",
            "material": {"kind": "explore"},
        },
        headers=ANALYST_HEADERS,
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["state"] == "pending"
    assert body["level"] == "must"
    assert body["subject_type"] == "slow_result"
    assert body["assignee"] == "u02"
    assert body["sla_due"]
    assert "material" not in body

    decided = api_client.post(
        f"/api/v1/reviews/{body['rid']}/decision",
        json={"decision": "reject", "signer": "u02", "reason": "口径不明"},
        headers=OWNER_HEADERS,
    )
    assert decided.status_code == 200
    assert decided.json()["state"] == "rejected"


def test_submit_review_none_is_signed_immediately(api_client):
    """level=none 免审：直接 signed 留痕，不进待办队列。"""
    resp = api_client.post(
        "/api/v1/reviews",
        json={
            "subject_type": "query",
            "subject_id": "Q0003",
            "level": "none",
            "assignee": "u02",
        },
        headers=ANALYST_HEADERS,
    )

    assert resp.status_code == 201
    assert resp.json()["state"] == "signed"


def test_submit_review_rejects_unknown_level(api_client):
    resp = api_client.post(
        "/api/v1/reviews",
        json={
            "subject_type": "query",
            "subject_id": "Q0004",
            "level": "auto",
            "assignee": "u02",
        },
        headers=ANALYST_HEADERS,
    )

    assert resp.status_code == 422


# ---------- GET /governance/candidates ----------


def _freeze_today(monkeypatch) -> None:
    monkeypatch.setattr("riskqa.api.routers.governance._today", lambda: "2026-10-30")


def test_candidates_aggregate_heat_by_signature(api_client, api_db_path, monkeypatch):
    _freeze_today(monkeypatch)
    _seed_logs(
        api_db_path,
        [
            ("Q1001", SQL_A, "u01"),
            ("Q1002", SQL_ALIAS, "u02"),
            ("Q1003", SQL_B, "u03"),
        ],
    )

    resp = api_client.get("/api/v1/governance/candidates", headers=OWNER_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert [item["metric"] for item in body["items"]] == ["fpd30_rate", "pass_rate"]

    fpd30 = body["items"][0]
    assert fpd30["signature"] == "fpd30_rate|channel|is_pass|all"
    assert fpd30["heat"] == {
        "n_queries": 2,
        "n_users": 2,
        "n_days": 2,
        "top_user_share": 0.5,
        "concentrated": False,
    }
    assert fpd30["conflict_flag"] == "⚠ 口径不一致"
    assert fpd30["state"] == "pending"
    assert body["items"][1]["conflict_flag"] == ""


def test_candidates_state_filter_and_paging(api_client, api_db_path, monkeypatch):
    _freeze_today(monkeypatch)
    _seed_logs(api_db_path, [("Q1001", SQL_A, "u01"), ("Q1003", SQL_B, "u03")])

    pending = api_client.get(
        "/api/v1/governance/candidates", params={"state": "pending"}, headers=OWNER_HEADERS
    )
    shelved = api_client.get(
        "/api/v1/governance/candidates", params={"state": "shelved"}, headers=OWNER_HEADERS
    )
    page = api_client.get(
        "/api/v1/governance/candidates", params={"limit": 1, "offset": 1}, headers=OWNER_HEADERS
    )

    assert pending.json()["total"] == 2
    assert shelved.json() == {"total": 0, "items": []}
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1


def test_candidates_rejects_bad_state(api_client):
    resp = api_client.get(
        "/api/v1/governance/candidates", params={"state": "done"}, headers=OWNER_HEADERS
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "E_GOVERNANCE_INVALID"


def test_candidates_owner_only(api_client):
    """SG-01 #2：analyst 调 owner 端点 → 403（认证通过、角色不足）。"""
    resp = api_client.get("/api/v1/governance/candidates", headers=ANALYST_HEADERS)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "E_UNAUTHORIZED"


def test_candidates_requires_token(api_client):
    assert api_client.get("/api/v1/governance/candidates").status_code == 401


def test_candidate_today_is_not_hardcoded():
    """热度窗口基准日取当天，不写死 legacy 的 2026-10-30。"""
    from riskqa.api.routers import governance

    assert governance._today() == date.today().isoformat()
