"""问数端点：ask（自动路由）与 explore（强制慢路），以及人审决策 resume。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ...store.review import ReviewRepo
from ..auth import current_identity, engine_role, require_role
from ..builders import (
    PENDING_TEXT,
    ask_payload,
    create_review,
    explore_payload,
    outcome_error,
    review_payload,
)
from ..deps import open_db
from ..errors import ApiError
from ..runtime import new_id, run_scope
from ..schemas import AskBody, DecisionBody, ExploreBody
from ..settings import TokenIdentity

router = APIRouter(tags=["ask"])

_DECISIONS = {"approve": "signed", "reject": "rejected", "shelve": "shelved"}


def _assert_caller(caller, ident: TokenIdentity) -> None:
    """P4：caller 字段保留，但必须与 token 身份一致；不一致按认证失败处理。"""
    if (caller.user, caller.dept, caller.role) != (ident.user, ident.dept, ident.role):
        raise ApiError("E_UNAUTHORIZED", "body.caller 与 token 身份不一致")


def _assignee(deps, out: dict) -> str:
    metric = out.get("metric") or ""
    owner = (deps.sem.metrics.get(metric) or {}).get("owner")
    return owner or "risk_admin"


def _invoke(request: Request, graph, question: str, ident: TokenIdentity, qid: str) -> dict:
    deps = request.app.state.deps
    with run_scope(deps, qid):
        return graph.invoke(
            {"question": question, "role": engine_role(ident.role)},
            config={"configurable": {"thread_id": qid}},
        )


def _pending(
    deps, *, out: dict, qid: str, question: str, kind: str, subject_type: str
) -> JSONResponse:
    """must：图停在 slow_review，落评审单并返回 202；thread_id 记在 material 里供续跑"""
    rid = new_id("R")
    with open_db(deps) as conn:
        create_review(
            conn,
            deps.governance,
            rid=rid,
            subject_type=subject_type,
            subject_id=qid,
            engine_level=out.get("review_level", "must"),
            assignee=_assignee(deps, out),
            material={
                "kind": kind,
                "qid": qid,
                "thread_id": qid,
                "question": question,
                "sql": out.get("sql", ""),
            },
        )
    return JSONResponse(
        status_code=202,
        content={
            "route": "slow",
            "review_id": rid,
            "state": "pending",
            "message": PENDING_TEXT,
        },
    )


def _run_review_row(deps, *, rid: str, out: dict, qid: str, question: str, kind: str, stype: str):
    """已完成（未中断）的慢路结果留痕；没有挂起态，绝不写 thread_id（否则裁决会误续跑）"""
    with open_db(deps) as conn:
        row = create_review(
            conn,
            deps.governance,
            rid=rid,
            subject_type=stype,
            subject_id=qid,
            engine_level=out.get("review_level", "auto"),
            assignee=_assignee(deps, out),
            material={"kind": kind, "qid": qid, "question": question},
        )
    return row


@router.post("/ask")
def ask(body: AskBody, request: Request, ident: TokenIdentity = Depends(current_identity)):  # noqa: B008
    _assert_caller(body.caller, ident)
    deps = request.app.state.deps
    qid = new_id("Q")

    out = _invoke(request, request.app.state.graph_ask, body.question, ident, qid)

    if out.get("__interrupt__"):
        return _pending(
            deps, out=out, qid=qid, question=body.question, kind="ask", subject_type="query"
        )

    error = outcome_error(out)
    if error is not None:
        raise error

    payload = ask_payload(out, deps.sem, body.time_range)
    # 慢路 auto/sample 也要留痕（sample = 先返回后抽检）
    if out.get("route") == "slow":
        row = _run_review_row(
            deps,
            rid=new_id("R"),
            out=out,
            qid=qid,
            question=body.question,
            kind="ask",
            stype="query",
        )
        payload["review_level"] = row["level"]

    return JSONResponse(status_code=200, content=payload)


@router.post("/explore")
def explore(body: ExploreBody, request: Request, ident: TokenIdentity = Depends(current_identity)):  # noqa: B008
    _assert_caller(body.caller, ident)
    deps = request.app.state.deps
    qid = new_id("Q")

    out = _invoke(request, request.app.state.graph_explore, body.question, ident, qid)

    if out.get("__interrupt__"):
        return _pending(
            deps,
            out=out,
            qid=qid,
            question=body.question,
            kind="explore",
            subject_type="slow_result",
        )

    error = outcome_error(out)
    if error is not None:
        raise error

    # P3：explore 保留 fail-closed——行权限注入后无可执行范围直接 403，不返回空结果
    if not out.get("exec_result") and not out.get("exec_error"):
        raise ApiError(
            "E_ROW_FILTER_DENIED",
            "行级权限注入后无可执行范围：explore 拒绝继续（越权不返回空结果）",
        )

    row = _run_review_row(
        deps,
        rid=new_id("R"),
        out=out,
        qid=qid,
        question=body.question,
        kind="explore",
        stype="slow_result",
    )
    return JSONResponse(
        status_code=200, content=explore_payload(out, deps.sem, review_payload(row))
    )


@router.post("/reviews/{rid}/decision")
def decide(
    rid: str,
    body: DecisionBody,
    request: Request,
    ident: TokenIdentity = Depends(require_role("owner", "admin")),  # noqa: B008
):
    if body.signer != ident.user:
        raise ApiError("E_UNAUTHORIZED", "signer 必须是当前 token 的持有人", status_code=403)
    if body.decision in {"reject", "shelve"} and not body.reason:
        raise ApiError("E_GOVERNANCE_INVALID", "reject / shelve 必须填写 reason")

    deps = request.app.state.deps
    with open_db(deps) as conn:
        repo = ReviewRepo(conn)
        row = repo.get(rid)
        if row is None:
            raise ApiError("E_REVIEW_REQUIRED", f"评审单 {rid} 不存在")
        if row["state"] not in {"pending", "reminded", "overdue"}:
            raise ApiError("E_REVIEW_REQUIRED", f"评审单 {rid} 状态为 {row['state']}，不可再决策")
        repo.transition(
            rid,
            from_state=row["state"],
            to_state=_DECISIONS[body.decision],
            decided_by=body.signer,
            decision=body.decision,
        )
        row = repo.get(rid)

    result = None
    material = row.get("material") or {}
    if body.decision == "approve" and material.get("thread_id"):
        result = _resume(request, material, review_payload(row))

    content = review_payload(row)
    if result is not None:
        content["result"] = result
    return JSONResponse(status_code=200, content=content)


def _resume(request: Request, material: dict, review: dict) -> dict:
    """P2：同一 checkpointer + 同一 thread_id 续跑，不重跑慢路。"""
    from langgraph.types import Command

    deps = request.app.state.deps
    graph = (
        request.app.state.graph_ask
        if material.get("kind") == "ask"
        else request.app.state.graph_explore
    )
    with run_scope(deps, material["qid"]):
        out = graph.invoke(
            Command(resume={"type": "accept"}),
            config={"configurable": {"thread_id": material["thread_id"]}},
        )
    error = outcome_error(out)
    if error is not None:
        raise error
    if material.get("kind") == "ask":
        return ask_payload(out, deps.sem)
    return explore_payload(out, deps.sem, review)
