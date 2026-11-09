"""API 骨架、认证与 health（T-4.1.5 第一笔）。"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from riskqa.api.auth import engine_role, require_role
from riskqa.api.errors import install_error_handler
from riskqa.api.routers.ops import health_payload
from riskqa.api.settings import SettingsError, load_settings

AS_OF = "2026-09-30"


def test_health_is_degraded_without_real_llm(api_client):
    """V4.1 只有 FakeLLM → llm_gateway 诚实报 degraded_local，HTTP 503。"""
    resp = api_client.get("/api/v1/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] == "ok"
    assert body["snapshot"] == {"latest": AS_OF, "digest": "testfilehash"}
    assert body["llm_gateway"] == "degraded_local"


def test_health_ok_when_three_states_green(api_deps, api_settings):
    """三态全绿才是 200：把 llm_mode 换成非 fake（真网关位）验证判定逻辑。"""
    from dataclasses import replace

    settings = replace(api_settings, llm_mode="gateway")
    code, body = health_payload(api_deps, settings)

    assert code == 200
    assert body["status"] == "ok"
    assert body["llm_gateway"] == "ok"


def test_health_degrades_when_snapshot_missing(api_deps, api_settings):
    from dataclasses import replace

    code, body = health_payload(replace(api_deps, manifest=None), api_settings)

    assert code == 503
    assert body["snapshot"] == {"latest": "", "digest": ""}


def test_health_needs_no_token(api_client):
    assert api_client.get("/api/v1/health").status_code == 503


def test_missing_token_returns_401(api_settings):
    # 用契约里要求 owner 的端点：当前未建，先用探针应用验证认证依赖本身
    probe = _probe_app(api_settings, "owner")
    resp = probe.get("/probe")

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "E_UNAUTHORIZED"
    assert "X-RiskQA-Token" in resp.json()["error"]["message"]


def test_unknown_token_returns_401(api_settings):
    probe = _probe_app(api_settings, "owner")
    resp = probe.get("/probe", headers={"X-RiskQA-Token": "nope"})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "E_UNAUTHORIZED"


def test_analyst_on_owner_endpoint_returns_403(api_settings):
    """SG-01 #2：认证通过但角色不足 → 403，不是 401。"""
    probe = _probe_app(api_settings, "owner")
    resp = probe.get("/probe", headers={"X-RiskQA-Token": "tok-analyst"})

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "E_UNAUTHORIZED"
    assert "角色不足" in resp.json()["error"]["message"]


def test_owner_passes_role_gate(api_settings):
    probe = _probe_app(api_settings, "owner")
    resp = probe.get("/probe", headers={"X-RiskQA-Token": "tok-owner"})

    assert resp.status_code == 200
    assert resp.json() == {"user": "u02", "role": "owner"}


def test_engine_role_mapping():
    """契约角色 → 语义层 row_policies 键：只有 analyst_qa / risk_admin 两个键。"""
    assert engine_role("analyst") == "analyst_qa"
    assert engine_role("owner") == "risk_admin"
    assert engine_role("admin") == "risk_admin"


def test_settings_fail_closed_without_tokens():
    with pytest.raises(SettingsError, match="RISKQA_TOKENS"):
        load_settings({})


def test_settings_rejects_bad_json():
    with pytest.raises(SettingsError, match="JSON"):
        load_settings({"RISKQA_TOKENS": "{not json"})


def test_settings_rejects_bad_role():
    raw = '{"t1": {"user": "u", "dept": "d", "role": "root"}}'
    with pytest.raises(SettingsError, match="角色非法"):
        load_settings({"RISKQA_TOKENS": raw})


def test_settings_rejects_unknown_llm_mode():
    raw = '{"t1": {"user": "u", "dept": "d", "role": "analyst"}}'
    with pytest.raises(SettingsError, match="暂不支持"):
        load_settings({"RISKQA_TOKENS": raw, "RISKQA_LLM_MODE": "gateway"})


def test_settings_accepts_valid_tokens():
    raw = '{"t1": {"user": "u", "dept": "d", "role": "owner"}}'
    st = load_settings({"RISKQA_TOKENS": raw})

    assert st.tokens["t1"].role == "owner"
    assert st.llm_mode == "fake"


def _probe_app(settings, role: str) -> TestClient:
    """测试专用探针：验证认证依赖，不污染生产路由。"""
    app = FastAPI()
    app.state.settings = settings
    install_error_handler(app)

    @app.get("/probe")
    def probe(ident=Depends(require_role(role))):  # noqa: B008  # FastAPI 依赖即默认值
        return {"user": ident.user, "role": ident.role}

    return TestClient(app)
