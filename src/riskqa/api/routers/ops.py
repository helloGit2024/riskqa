"""运维端点：health（`security: []`，无需 token）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...store.schema import verify_schema
from ..deps import AppDeps, open_db
from ..settings import Settings

router = APIRouter(tags=["ops"])


def health_payload(deps: AppDeps, settings: Settings) -> tuple[int, dict]:
    """三态判定：db / snapshot / llm_gateway 任一异常即 degraded → 503。

    V4.1 只有 FakeLLM（真网关属 T-4.1.7），故 llm_gateway 恒为 degraded_local，
    health 会诚实返回 503，而不是把假模型报成 ok。
    """
    with open_db(deps) as conn:
        db_errors = verify_schema(conn)
    snapshot_ok = deps.manifest is not None
    llm = "degraded_local" if settings.llm_mode == "fake" else "ok"
    ok = not db_errors and snapshot_ok and llm == "ok"

    body = {
        "status": "ok" if ok else "degraded",
        "db": "error" if db_errors else "ok",
        "snapshot": {
            "latest": deps.manifest.data_as_of if snapshot_ok else "",
            "digest": (deps.manifest.file_hash or deps.manifest.data_hash) if snapshot_ok else "",
        },
        "llm_gateway": llm,
    }
    return (200 if ok else 503), body


@router.get("/health")
def health(request: Request) -> JSONResponse:
    code, body = health_payload(request.app.state.deps, request.app.state.settings)
    return JSONResponse(status_code=code, content=body)
