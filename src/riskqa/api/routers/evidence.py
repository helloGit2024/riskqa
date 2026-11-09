"""证据端点：事实详情与证据快照（P-07 / P-12：引用必须回表可查）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ...store.facts import FactRepo
from ...store.query_log import QueryLogRepo
from ...store.review import ReviewRepo
from ..auth import current_identity
from ..builders import evidence_payload, fact_detail_payload
from ..deps import open_db
from ..errors import ApiError
from ..settings import TokenIdentity

router = APIRouter(tags=["evidence"])


@router.get("/facts/{fid}")
def get_fact(
    fid: str,
    request: Request,
    ident: TokenIdentity = Depends(current_identity),  # noqa: B008  # FastAPI 依赖写法
) -> JSONResponse:
    deps = request.app.state.deps
    with open_db(deps) as conn:
        row = FactRepo(conn).get(fid)
    if row is None:
        # 查不到即判失败——不猜不填（P-07），404 不泄露其余信息
        raise ApiError("E_NOT_FOUND", f"事实 {fid} 不存在——引用必须回表可查（P-07）")
    return JSONResponse(status_code=200, content=fact_detail_payload(row))


@router.get("/evidence/{qid}")
def get_evidence(
    qid: str,
    request: Request,
    ident: TokenIdentity = Depends(current_identity),  # noqa: B008  # FastAPI 依赖写法
) -> JSONResponse:
    deps = request.app.state.deps
    with open_db(deps) as conn:
        log = QueryLogRepo(conn).get(qid)
        if log is None:
            raise ApiError("E_NOT_FOUND", f"证据 {qid} 不存在")
        facts = FactRepo(conn).list(qid=qid, limit=-1)
        chain = ReviewRepo(conn).list(subject_id=qid, limit=-1)
    return JSONResponse(status_code=200, content=evidence_payload(log, facts, chain, deps.manifest))
