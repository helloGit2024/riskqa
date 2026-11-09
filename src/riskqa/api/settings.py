"""API 运行配置：token → 身份表、路径与 LLM 模式。

安全纪律（P-01 / R14）：
- token 只从环境变量 `RISKQA_TOKENS` 读，代码与仓库里没有任何密钥。
- 配置缺失/格式非法/角色越界 → 启动即失败，绝不以空表放行。
- 角色只允许契约里的 analyst / owner / admin。
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ALLOWED_ROLES = ("analyst", "owner", "admin")
LLM_MODES = ("fake",)  # 真网关在 T-4.1.7；此处不假装支持


class SettingsError(Exception):
    """运行配置缺失或非法——启动即失败，不带病运行"""


@dataclass(frozen=True)
class TokenIdentity:
    """token 绑定的身份；角色决定可用端点与行级权限范围"""

    user: str
    dept: str
    role: str


@dataclass(frozen=True)
class Settings:
    tokens: Mapping[str, TokenIdentity]
    semantic_path: Path = Path("config/semantic_view.yaml")
    governance_path: Path = Path("config/governance.yaml")
    ops_db_path: Path = Path("data/ops.db")
    snapshot_dir: Path = Path("data/snapshots")
    llm_mode: str = "fake"
    data_as_of: str = ""


def _parse_tokens(raw: str) -> dict[str, TokenIdentity]:
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise SettingsError(f"RISKQA_TOKENS 不是合法 JSON：{e}") from e
    if not isinstance(data, dict) or not data:
        raise SettingsError("RISKQA_TOKENS 必须是非空 JSON 对象（token → 身份）")

    out: dict[str, TokenIdentity] = {}
    for token, ident in data.items():
        if not isinstance(token, str) or not token:
            raise SettingsError("RISKQA_TOKENS 的 token 必须是非空字符串")
        if not isinstance(ident, dict):
            raise SettingsError(f"token {token[:4]}… 的身份必须是对象")
        missing = [k for k in ("user", "dept", "role") if not ident.get(k)]
        if missing:
            raise SettingsError(f"token {token[:4]}… 缺字段：{missing}")
        role = ident["role"]
        if role not in ALLOWED_ROLES:
            raise SettingsError(
                f"token {token[:4]}… 角色非法：{role!r}，允许 {list(ALLOWED_ROLES)}"
            )
        out[token] = TokenIdentity(user=str(ident["user"]), dept=str(ident["dept"]), role=role)
    return out


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """从环境变量加载；任何缺失/非法都显式抛 SettingsError（不静默降级）"""
    e = os.environ if env is None else env

    raw_tokens = e.get("RISKQA_TOKENS", "").strip()
    if not raw_tokens:
        raise SettingsError(
            "缺少 RISKQA_TOKENS 环境变量——身份表为空时拒绝启动（P-01/P-10），"
            '格式：{"<token>":{"user":"...","dept":"...","role":"analyst|owner|admin"}}'
        )

    llm_mode = e.get("RISKQA_LLM_MODE", "fake").strip()
    if llm_mode not in LLM_MODES:
        raise SettingsError(
            f"RISKQA_LLM_MODE={llm_mode!r} 暂不支持：真网关属 T-4.1.7，本版只允许 {list(LLM_MODES)}"
        )

    return Settings(
        tokens=_parse_tokens(raw_tokens),
        semantic_path=Path(e.get("RISKQA_SEMANTIC", "config/semantic_view.yaml")),
        governance_path=Path(e.get("RISKQA_GOVERNANCE", "config/governance.yaml")),
        ops_db_path=Path(e.get("RISKQA_OPS_DB", "data/ops.db")),
        snapshot_dir=Path(e.get("RISKQA_SNAPSHOTS", "data/snapshots")),
        llm_mode=llm_mode,
        data_as_of=e.get("RISKQA_DATA_AS_OF", "").strip(),
    )
