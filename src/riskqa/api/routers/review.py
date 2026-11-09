"""人审提交端点：慢路结果 / 归因结论进评审队列（P-11）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ...store.review import ReviewRepo
from ..auth import current_identity
from ..builders import review_payload, sla_due
from ..deps import open_db
from ..runtime import new_id
from ..schemas import ReviewSubmitBody
from ..settings import TokenIdentity

router = APIRouter(tags=["review"])


@router.post("/reviews", status_code=201)
def submit_review(
    body: ReviewSubmitBody,
    request: Request,
    ident: TokenIdentity = Depends(current_identity),  # noqa: B008  # FastAPI 依赖写法
) -> JSONResponse:
    """level=none 免审直接留痕（signed）；spot/must 挂 pending 等 Owner 裁决。"""
    deps = request.app.state.deps
    rid = new_id("R")
    state = "signed" if body.level == "none" else "pending"
    with open_db(deps) as conn:
        repo = ReviewRepo(conn)
        repo.insert(
            rid=rid,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            level=body.level,
            assignee=body.assignee,
            sla_due=sla_due(deps.governance),
            state=state,
            material=body.material,
        )
        row = repo.get(rid)
    return JSONResponse(status_code=201, content=review_payload(row))
