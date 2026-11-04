# -*- coding: utf-8 -*-
"""事实层：FactStore + fact_id（全文数字唯一来源）。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Fact:
    fid: str
    value: object
    unit: str
    metric: str
    segment: str      # V1 修复 bug 的字段：整体 vs 分维度精确匹配
    source: str       # fast | slow（哪条路产的，交叉验证用）
    data_as_of: str


class FactStore:
    """模型只许引用 {{F0001}}，禁写裸数字——数字必须可溯源"""

    def __init__(self, data_as_of: str = ""):
        self._seq = 0
        self._facts: dict[str, Fact] = {}
        self._data_as_of = data_as_of

    def put(self, value, unit: str, metric: str, segment: str = "overall",
            source: str = "fast") -> str:
        self._seq += 1
        fid = f"F{self._seq:04d}"
        self._facts[fid] = Fact(fid, value, unit, metric, segment, source, self._data_as_of)
        return fid

    def get(self, fid: str) -> Fact:
        try:
            return self._facts[fid]
        except KeyError:
            raise UnknownFactError(f"{fid} 不存在——模型编造了引用")

    def digest(self) -> list[dict]:
        """注入上下文：模型需要知道有哪些数可用，才能写叙事"""
        return [asdict(f) for f in self._facts.values()]

    def manifest(self) -> dict:
        raw = json.dumps([asdict(f) for f in self._facts.values()],
                         sort_keys=True, ensure_ascii=False, default=str)
        return {"count": len(self._facts),
                "sha256": hashlib.sha256(raw.encode()).hexdigest()}


class UnknownFactError(Exception):
    """模型引用了不存在的 fact_id——编造引用，校验闸必抓"""
