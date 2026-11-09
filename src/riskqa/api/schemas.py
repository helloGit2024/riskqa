"""请求体模型：只做形状校验，身份一律以请求头为准（P4 一致性另校验）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Caller(BaseModel):
    """契约保留字段；必须与 token 身份一致，否则 401"""

    model_config = ConfigDict(extra="forbid")

    user: str = Field(min_length=1)
    dept: str = Field(min_length=1)
    role: Literal["analyst", "owner", "admin"]


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    time_range: str = "all"  # OPEN-QUESTIONS #34：只回传不参与计算
    caller: Caller


class ExploreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    max_fix_rounds: int = Field(default=2, ge=0, le=2)
    caller: Caller


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "shelve"]
    signer: str = Field(min_length=1)
    reason: str = ""
