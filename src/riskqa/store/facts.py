# -*- coding: utf-8 -*-
"""fact DAO：只 INSERT；写入前拒绝 NaN/±Inf（P-12 的可复现底座）。"""

from __future__ import annotations

import math
import sqlite3
from typing import Any

from . import InvalidFactValueError
from .db import now_ts


def ensure_finite(value: Any, metric: str, segment: str) -> float:
    """fact.value 必须是有限实数：NaN/±Inf 显式拒收，不写哨兵"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise InvalidFactValueError(
            f"fact.value 非数值：metric={metric} segment={segment} value={value!r}")
    if not math.isfinite(num):
        raise InvalidFactValueError(
            f"fact.value 非有限数：metric={metric} segment={segment} value={num!r}")
    return num


class FactRepo:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def next_fid(self) -> str:
        """F+序号续号：取库内最大序号 +1，不建序列表"""
        row = self._conn.execute(
            "SELECT MAX(CAST(SUBSTR(fid, 2) AS INTEGER)) AS n FROM fact").fetchone()
        return f"F{(row['n'] or 0) + 1:04d}"

    def insert(self, *, fid: str, value: Any, unit: str, metric: str,
               segment: str = "", source: str = "fast", qid: str | None = None,
               created_at: str | None = None) -> None:
        num = ensure_finite(value, metric, segment)
        self._conn.execute(
            "INSERT INTO fact (fid, value, unit, metric, segment, source, qid, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (fid, num, unit, metric, segment, source, qid, created_at or now_ts()))

    def get(self, fid: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM fact WHERE fid=?", (fid,)).fetchone()
        return dict(row) if row else None

    def list(self, *, metric: str | None = None, segment: str | None = None,
             limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM fact"
        cond, args = [], []
        if metric is not None:
            cond.append("metric=?")
            args.append(metric)
        if segment is not None:
            cond.append("segment=?")
            args.append(segment)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY CAST(SUBSTR(fid, 2) AS INTEGER) LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._conn.execute(sql, args)]
