"""错误码单一映射（api-contract §3.3）。

约定：
- 领域异常 → `E_*` 只在这一处转换，避免各路由各写一套文案。
- `E_UNAUTHORIZED` 通常 401；`owner`/`admin` 专属端点被 analyst 调用时按
  security §七 #2 返回 403（P5 拍板），由调用方显式传 `status_code=403`。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# 契约 §3.3 全集 + 本轮新增 E_SLOW_UNCONVERGED（P6 拍板）
ERROR_STATUS: dict[str, int] = {
    "E_UNAUTHORIZED": 401,
    "E_UNREGISTERED_METRIC": 400,
    "E_UNSIGNED_METRIC": 400,
    "E_CALC_NOT_REGISTERED": 400,
    "E_DIM_NOT_ALLOWED": 400,
    "E_BARE_NUMBER": 422,
    "E_FABRICATED_REF": 422,
    "E_RECOMPUTE_MISMATCH": 422,
    "E_SLOW_UNCONVERGED": 422,
    "E_SQL_REJECTED": 400,
    "E_ROW_FILTER_DENIED": 403,
    "E_REVIEW_REQUIRED": 409,
    "E_SLA_TIMEOUT": 504,
    "E_GOVERNANCE_INVALID": 400,
}


class ApiError(Exception):
    """带契约错误码的业务异常；message 面向调用方，不放堆栈"""

    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        if code not in ERROR_STATUS:
            raise ValueError(f"未登记的 API 错误码：{code!r}")
        self.code = code
        self.message = message
        self.status_code = status_code or ERROR_STATUS[code]
        super().__init__(f"{code}: {message}")

    def to_body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def install_error_handler(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())
