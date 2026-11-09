"""治理端点：晋升候选列表（热度三维度 + 冲突标注）。

数据来源是 raw log（query_log）与评审单（review_record），不做任何口径计算；
提名阈值判定与跨签名口径指纹冲突属 T-4.2.2 / T-4.2.3，本版只暴露已算出的信号。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from ...governance.clustering import Cluster, QueryLog, RuleExtractor, cluster_logs, heat
from ...store.query_log import QueryLogRepo
from ...store.review import ReviewRepo
from ..auth import require_role
from ..deps import open_db
from ..errors import ApiError
from ..settings import TokenIdentity

router = APIRouter(tags=["governance"])

_STATES = {"pending", "reminded", "overdue", "shelved", "all"}
# 已裁决的评审单不再是候选（signed / rejected 终态）
_CLOSED = {"signed", "rejected"}


def _today() -> str:
    """热度窗口基准日；测试注入固定日期，避免依赖真实时钟"""
    return date.today().isoformat()


def _to_logs(rows: list[dict]) -> list[QueryLog]:
    return [
        QueryLog(
            qid=r["qid"],
            question=r["question"],
            sql=r["sql"],
            sql_edited=bool(r["sql_edited"]),
            result_digest=r["result_digest"],
            user=r["user"],
            dept=r["dept"],
            ts=r["ts"],
            confirmed_by=tuple(r["confirmed_by"] or []),
        )
        for r in rows
    ]


def _states_by_signature(rows: list[dict]) -> dict[str, str]:
    """每个签名取最新一张评审单的状态（rid 单调递增，后写覆盖先写）"""
    latest: dict[str, str] = {}
    for row in sorted(rows, key=lambda r: r["rid"]):
        if row["subject_type"] == "promotion":
            latest[row["subject_id"]] = row["state"]
    return latest


def _candidate(cluster_id: str, cluster: Cluster, state: str, today: str) -> dict:
    h = heat(cluster, today)
    return {
        "signature": cluster_id,
        "metric": cluster.sig.metric,
        "heat": {
            "n_queries": h["n_queries"],
            "n_users": h["n_users"],
            "n_days": h["n_days"],
            "top_user_share": h["top_user_share"],
            "concentrated": h["concentrated"],
        },
        "conflict_flag": "⚠ 口径不一致" if cluster.conflicts else "",
        "state": state,
    }


@router.get("/governance/candidates")
def list_candidates(
    request: Request,
    state: str = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ident: TokenIdentity = Depends(require_role("owner", "admin")),  # noqa: B008
) -> JSONResponse:
    if state not in _STATES:
        raise ApiError("E_GOVERNANCE_INVALID", f"state 非法：{state!r}，允许 {sorted(_STATES)}")

    deps = request.app.state.deps
    with open_db(deps) as conn:
        logs = QueryLogRepo(conn).list(limit=-1)
        reviews = ReviewRepo(conn).list(limit=-1)

    clusters = cluster_logs(_to_logs(logs), deps.sem, RuleExtractor())
    latest = _states_by_signature(reviews)
    today = _today()

    items = []
    for cid, cluster in clusters.items():
        st = latest.get(cid, "pending")
        if st in _CLOSED:
            continue
        items.append(_candidate(cid, cluster, st, today))
    items.sort(key=lambda item: (-item["heat"]["n_queries"], item["signature"]))
    if state != "all":
        items = [item for item in items if item["state"] == state]

    return JSONResponse(
        status_code=200, content={"total": len(items), "items": items[offset : offset + limit]}
    )
