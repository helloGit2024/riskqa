"""fact DAO + 数据库版 FactStore 适配器（只 INSERT；写入前拒绝 NaN/±Inf）。"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict
from typing import Any

from ..facts.store import Fact, UnknownFactError
from . import InvalidFactValueError
from .db import now_ts, transaction


def ensure_finite(value: Any, metric: str, segment: str) -> float:
    """fact.value 必须是有限实数：NaN/±Inf 显式拒收，不写哨兵"""
    try:
        num = float(value)
    except (TypeError, ValueError) as e:
        raise InvalidFactValueError(
            f"fact.value 非数值：metric={metric} segment={segment} value={value!r}"
        ) from e
    if not math.isfinite(num):
        raise InvalidFactValueError(
            f"fact.value 非有限数：metric={metric} segment={segment} value={num!r}"
        )
    return num


class FactRepo:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def next_fid(self) -> str:
        """F+序号续号：取库内最大序号 +1，不建序列表"""
        row = self._conn.execute(
            "SELECT MAX(CAST(SUBSTR(fid, 2) AS INTEGER)) AS n FROM fact"
        ).fetchone()
        return f"F{(row['n'] or 0) + 1:04d}"

    def insert(
        self,
        *,
        fid: str,
        value: Any,
        unit: str,
        metric: str,
        segment: str = "",
        source: str = "fast",
        qid: str | None = None,
        created_at: str | None = None,
    ) -> None:
        num = ensure_finite(value, metric, segment)
        self._conn.execute(
            "INSERT INTO fact (fid, value, unit, metric, segment, source, qid, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (fid, num, unit, metric, segment, source, qid, created_at or now_ts()),
        )

    def get(self, fid: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM fact WHERE fid=?", (fid,)).fetchone()
        return dict(row) if row else None

    def list(
        self, *, metric: str | None = None, segment: str | None = None, limit: int = 100
    ) -> list[dict]:
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


class SqliteFactStore:
    """与内存 FactStore 同接口（put/get/digest/manifest）；编排层零改动。

    data_as_of 不落库（决策 6）——由构造器/manifest 提供，落库字段与
    docs/data-model.md §2.2 一致。
    """

    def __init__(self, conn: sqlite3.Connection, data_as_of: str = ""):
        self._conn = conn
        self._repo = FactRepo(conn)
        self._data_as_of = data_as_of

    def put(
        self,
        value,
        unit: str,
        metric: str,
        segment: str = "overall",
        source: str = "fast",
        qid: str | None = None,
    ) -> str:
        """单事务内取号 + 落库；NaN/±Inf 由 FactRepo.insert 显式拒收"""
        with transaction(self._conn):
            fid = self._repo.next_fid()
            self._repo.insert(
                fid=fid,
                value=value,
                unit=unit,
                metric=metric,
                segment=segment,
                source=source,
                qid=qid,
            )
        return fid

    def get(self, fid: str) -> Fact:
        row = self._repo.get(fid)
        if row is None:
            raise UnknownFactError(f"{fid} 不存在——模型编造了引用")
        return Fact(
            row["fid"],
            row["value"],
            row["unit"],
            row["metric"],
            row["segment"],
            row["source"],
            self._data_as_of,
        )

    def digest(self) -> list[dict]:
        return [asdict(self.get(r["fid"])) for r in self._repo.list(limit=-1)]

    def manifest(self) -> dict:
        facts = self.digest()
        raw = json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str)
        return {"count": len(facts), "sha256": hashlib.sha256(raw.encode()).hexdigest()}
