"""身份识别：token → 角色 → 行权限/端点权限。

铁律（api-contract §3.2 / P-10）：身份只认请求头，任何端点都不接受 body 自报。
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request

from .errors import ApiError
from .settings import TokenIdentity

TOKEN_HEADER = "X-RiskQA-Token"  # noqa: S105  # 请求头名称，不是密钥

# 契约角色 → 语义层 row_policies 的键（config/semantic_view.yaml 只有这两个键）
ROLE_TO_ENGINE = {"analyst": "analyst_qa", "owner": "risk_admin", "admin": "risk_admin"}


def engine_role(role: str) -> str:
    try:
        return ROLE_TO_ENGINE[role]
    except KeyError as e:  # 理论上 settings 已挡，这里保持显式失败
        raise ApiError("E_UNAUTHORIZED", f"未知角色：{role!r}") from e


def current_identity(request: Request) -> TokenIdentity:
    token = request.headers.get(TOKEN_HEADER, "")
    if not token:
        raise ApiError("E_UNAUTHORIZED", f"缺少 {TOKEN_HEADER} 请求头")
    ident = request.app.state.settings.tokens.get(token)
    if ident is None:
        raise ApiError("E_UNAUTHORIZED", "token 无效")
    return ident


def require_role(*allowed: str) -> Callable[..., TokenIdentity]:
    """端点级角色闸：认证失败 401，认证通过但角色不足 403（SG-01 #2）"""

    def _dep(
        ident: TokenIdentity = Depends(current_identity),  # noqa: B008  # FastAPI 依赖写法
    ) -> TokenIdentity:
        if ident.role not in allowed:
            raise ApiError(
                "E_UNAUTHORIZED",
                f"角色不足：该端点需要 {list(allowed)}，当前 {ident.role}",
                status_code=403,
            )
        return ident

    return _dep
