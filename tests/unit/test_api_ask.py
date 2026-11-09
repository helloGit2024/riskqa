"""ask / explore / decision 端点（T-4.1.5 第二笔）。

数字基线全部固定：analyst 行权限只可见 A 渠道（0.22391857506361323），
admin 可见全量（0.2859042553191489）。全部用 FakeLLM 脚本，不接真模型（P-17）。
"""

from __future__ import annotations

import pytest

from riskqa.api.builders import EMPTY_TEXT, PENDING_TEXT, outcome_error
from riskqa.api.errors import ERROR_STATUS
from riskqa.api.runtime import SharedFactStore, run_scope

ANALYST_FPD30 = 0.22391857506361323
ALL_FPD30 = 0.2859042553191489

FAST_Q = "各渠道首期逾期率"
FAST_Q_OVERALL = "首期逾期率"
DENIED_Q = "B渠道首期逾期率"
SLOW_Q = "各渠道平均逾期水平如何"

GOOD_SQL = (
    "SELECT channel, AVG(is_fpd30) FROM fact_application "
    "WHERE is_pass = 1 GROUP BY channel LIMIT 10"
)
# 无 LIMIT：三闸驳回 → 修正 2 轮后 step_limit
BAD_SQL = "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel"
# 分母错（漏 is_pass=1）：交叉验证不一致 → cross_fail
WRONG_DENOM_SQL = "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel LIMIT 10"
# JOIN + LIMIT：三闸放行，但分级为 must（触发 interrupt）；demo 执行器不支持 → 降级
MUST_SQL = (
    "SELECT channel, AVG(is_fpd30) FROM fact_application "
    "JOIN dim_channel ON fact_application.channel = dim_channel.channel "
    "WHERE is_pass = 1 GROUP BY channel LIMIT 10"
)
# 只查 B 渠道：analyst 行权限注入后为空 → explore fail-closed
OUT_OF_SCOPE_SQL = (
    "SELECT channel, AVG(is_fpd30) FROM fact_application "
    "WHERE is_pass = 1 AND channel = 'B' GROUP BY channel LIMIT 10"
)

ANALYST_HEADERS = {"X-RiskQA-Token": "tok-analyst"}
ADMIN_HEADERS = {"X-RiskQA-Token": "tok-admin"}
OWNER_HEADERS = {"X-RiskQA-Token": "tok-owner"}

ANALYST_CALLER = {"user": "u01", "dept": "风险策略部", "role": "analyst"}
ADMIN_CALLER = {"user": "u03", "dept": "风控中台", "role": "admin"}


def _body(question: str, caller: dict) -> dict:
    return {"question": question, "caller": caller}


def test_ask_fast_analyst_matches_baseline(api_client_factory):
    """快路数字必须与基线一致：analyst 行权限下 A 渠道 FPD30 = 0.22391857506361323。"""
    script = [{}, {"text": "A 渠道首期逾期率见 {{F0001}}。"}]
    with api_client_factory(script) as client:
        resp = client.post(
            "/api/v1/ask", json=_body(FAST_Q, ANALYST_CALLER), headers=ANALYST_HEADERS
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["route"] == "fast"
    assert body["metric"] == "fpd30_rate"
    assert body["signature"] == "fpd30_rate|channel||all"
    assert body["review_level"] == "none"
    assert body["caliber"]["owner"] == "风控策略组"
    assert body["caliber"]["signed_at"] == "2026-09-30"
    assert len(body["facts"]) == 1
    assert body["facts"][0]["segment"] == "channel=A"
    assert body["facts"][0]["value"] == pytest.approx(ANALYST_FPD30, rel=1e-12)


def test_ask_fast_admin_overall_matches_baseline(api_client_factory):
    """admin 无行权限收窄：全量 FPD30 = 0.2859042553191489。"""
    script = [{}, {"text": "全量首期逾期率见 {{F0001}}。"}]
    with api_client_factory(script) as client:
        resp = client.post(
            "/api/v1/ask", json=_body(FAST_Q_OVERALL, ADMIN_CALLER), headers=ADMIN_HEADERS
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["signature"] == "fpd30_rate|||all"
    assert body["facts"][0]["value"] == pytest.approx(ALL_FPD30, rel=1e-12)


def test_ask_row_filter_denied_returns_empty_200(api_client_factory):
    """P3：ask 越权 → 200 + 空 facts + 空结果说明，不报错（报错会泄露记录存在）。"""
    with api_client_factory([{}, {"text": "不会走到叙事"}]) as client:
        resp = client.post(
            "/api/v1/ask", json=_body(DENIED_Q, ANALYST_CALLER), headers=ANALYST_HEADERS
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["route"] == "fast"
    assert body["facts"] == []
    assert body["answer_text"] == EMPTY_TEXT
    assert body["review_level"] == "none"


def test_ask_must_returns_202_then_resume(api_client_factory):
    """P2：must → 202 挂起 → Owner approve → 同一 thread_id 续跑（不重跑慢路）。"""
    script = [
        {"tables": ["fact_application", "dim_channel"]},
        {"sql": MUST_SQL},
        {"text": "高风险查询已确认执行；演示执行器不支持跨表，未产出事实。"},
    ]
    with api_client_factory(script) as client:
        first = client.post(
            "/api/v1/ask", json=_body(SLOW_Q, ANALYST_CALLER), headers=ANALYST_HEADERS
        )
        assert first.status_code == 202
        pending = first.json()
        assert pending == {
            "route": "slow",
            "review_id": pending["review_id"],
            "state": "pending",
            "message": PENDING_TEXT,
        }
        rid = pending["review_id"]

        decision = client.post(
            f"/api/v1/reviews/{rid}/decision",
            json={"decision": "approve", "signer": "u02"},
            headers=OWNER_HEADERS,
        )

    assert decision.status_code == 200
    body = decision.json()
    assert body["rid"] == rid
    assert body["state"] == "signed"
    assert body["level"] == "must"
    assert body["decided_by"] == "u02"
    result = body["result"]
    assert result["route"] == "slow"
    assert result["metric"] == "fpd30_rate"
    assert result["review_level"] == "must"
    assert result["facts"] == []


def test_ask_cross_fail_maps_422(api_client_factory):
    """交叉验证不一致 → 422 E_RECOMPUTE_MISMATCH（两侧数字只进 message，不平均）。"""
    script = [{"tables": ["fact_application"]}, {"sql": WRONG_DENOM_SQL}]
    with api_client_factory(script) as client:
        resp = client.post(
            "/api/v1/ask", json=_body(SLOW_Q, ANALYST_CALLER), headers=ANALYST_HEADERS
        )

    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "E_RECOMPUTE_MISMATCH"
    assert "0.1461794019933555" in error["message"]
    assert "0.22391857506361323" in error["message"]


def test_ask_step_limit_maps_422(api_client_factory):
    """3 次生成都不合规 → 422 E_SLOW_UNCONVERGED。"""
    script = [{"tables": ["fact_application"]}] + [{"sql": BAD_SQL}] * 3
    with api_client_factory(script) as client:
        resp = client.post(
            "/api/v1/ask", json=_body(SLOW_Q, ANALYST_CALLER), headers=ANALYST_HEADERS
        )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "E_SLOW_UNCONVERGED"


def test_timeout_maps_504():
    """timeout → 504 E_SLA_TIMEOUT（HTTP 级需要可注入时钟，映射在 builders 层验证）。"""
    error = outcome_error({"result": {"failures": [("timeout", 60.0)]}})

    assert error is not None
    assert error.code == "E_SLA_TIMEOUT"
    assert error.status_code == 504
    assert ERROR_STATUS["E_SLA_TIMEOUT"] == 504


def test_explore_returns_slow_result(api_client_factory):
    """explore 强制慢路：命中语义层的问题也走 SQL + 交叉验证，返回 verdict/review。"""
    script = [
        {"tables": ["fact_application"]},
        {"sql": GOOD_SQL},
        {"text": "A 渠道首期逾期率见 {{F0001}}。"},
    ]
    with api_client_factory(script) as client:
        resp = client.post(
            "/api/v1/explore", json=_body(FAST_Q, ANALYST_CALLER), headers=ANALYST_HEADERS
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["sql"] == GOOD_SQL
    assert body["verdict"]["passed"] is True
    assert body["verdict"]["cross_check"]["ok"] is True
    assert body["facts"][0]["segment"] == "channel=A"
    assert body["facts"][0]["value"] == pytest.approx(ANALYST_FPD30, rel=1e-12)
    assert body["review"]["level"] == "spot"
    assert body["review"]["state"] == "pending"


def test_explore_row_filter_denied_403(api_client_factory):
    """P3：explore 保留 fail-closed——行权限注入后无可执行范围 → 403，不返回空结果。"""
    script = [{"tables": ["fact_application"]}, {"sql": OUT_OF_SCOPE_SQL}]
    with api_client_factory(script) as client:
        resp = client.post(
            "/api/v1/explore", json=_body(SLOW_Q, ANALYST_CALLER), headers=ANALYST_HEADERS
        )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "E_ROW_FILTER_DENIED"


def test_ai_headers_on_success_and_error(api_client_factory):
    """P-16：所有出口都带 AI 标识与 data_as_of（含 200 / 403 / 202）。"""
    script = [{"tables": ["fact_application"]}, {"sql": OUT_OF_SCOPE_SQL}]
    with api_client_factory(script) as client:
        ok = client.post("/api/v1/ask", json=_body(FAST_Q, ANALYST_CALLER), headers=ANALYST_HEADERS)
        denied = client.post(
            "/api/v1/explore", json=_body(SLOW_Q, ANALYST_CALLER), headers=ANALYST_HEADERS
        )
        health = client.get("/api/v1/health")

    for resp in (ok, denied, health):
        assert resp.headers["X-AI-Disclosure"] == "true"
        assert resp.headers["X-Data-As-Of"] == "2026-09-30"


def test_caller_must_match_token(api_client_factory):
    """P4：body.caller 与 token 身份不一致 → 401（不接受 body 自报身份）。"""
    with api_client_factory([]) as client:
        resp = client.post("/api/v1/ask", json=_body(FAST_Q, ADMIN_CALLER), headers=ANALYST_HEADERS)

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "E_UNAUTHORIZED"


def test_run_fact_store_isolates_run(api_deps):
    """run 级事实隔离：fid 全局续号，digest 只看本次 run；离开 run_scope 显式失败。"""
    shared = SharedFactStore()

    with run_scope(api_deps, "Q1"):
        f1 = shared.put(0.1, "ratio", "fpd30_rate", segment="channel=A", source="fast")
        assert [f["fid"] for f in shared.digest()] == [f1]
        assert shared.manifest()["count"] == 1

    with pytest.raises(RuntimeError, match="run_scope"):
        shared.digest()

    with run_scope(api_deps, "Q2"):
        f2 = shared.put(0.2, "ratio", "fpd30_rate", segment="channel=B", source="fast")
        assert f2 != f1
        assert [f["fid"] for f in shared.digest()] == [f2]
