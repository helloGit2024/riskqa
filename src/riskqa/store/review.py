"""review_record DAO：状态机推进用条件 UPDATE，冲突显式失败。"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import ConcurrentTransitionError, InvalidTransitionError
from .db import decode_json, encode_json, now_ts

ALLOWED = {
    "pending": {"reminded", "overdue", "signed", "shelved", "rejected"},
    "reminded": {"overdue", "signed", "shelved", "rejected"},
    "overdue": {"signed", "shelved", "rejected"},
    "signed": set(),
    "shelved": set(),
    "rejected": set(),
}


class ReviewRepo:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(
        self,
        *,
        rid: str,
        subject_type: str,
        subject_id: str,
        level: str,
        assignee: str,
        sla_due: str,
        state: str = "pending",
        material: Any = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO review_record (rid, subject_type, subject_id, level, state, "
            "assignee, sla_due, material) VALUES (?,?,?,?,?,?,?,?)",
            (
                rid,
                subject_type,
                subject_id,
                level,
                state,
                assignee,
                sla_due,
                None if material is None else encode_json(material),
            ),
        )

    def get(self, rid: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM review_record WHERE rid=?", (rid,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["material"] = decode_json(data["material"])
        return data

    def list(
        self, *, state: str | None = None, assignee: str | None = None, limit: int = 100
    ) -> list[dict]:
        sql = "SELECT * FROM review_record"
        cond, args = [], []
        if state is not None:
            cond.append("state=?")
            args.append(state)
        if assignee is not None:
            cond.append("assignee=?")
            args.append(assignee)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY sla_due ASC LIMIT ?"
        args.append(limit)
        rows = []
        for r in self._conn.execute(sql, args):
            data = dict(r)
            data["material"] = decode_json(data["material"])
            rows.append(data)
        return rows

    def transition(
        self,
        rid: str,
        *,
        from_state: str,
        to_state: str,
        decided_by: str | None = None,
        decision: str | None = None,
        decided_at: str | None = None,
    ) -> None:
        """条件推进：WHERE rid=? AND state=旧值；0 行 = 并发冲突"""
        if to_state not in ALLOWED.get(from_state, set()):
            raise InvalidTransitionError(f"review_record 不允许 {from_state} -> {to_state}")
        cur = self._conn.execute(
            "UPDATE review_record SET state=?, decided_by=?, decision=?, decided_at=? "
            "WHERE rid=? AND state=?",
            (
                to_state,
                decided_by,
                decision,
                decided_at or (now_ts() if to_state in {"signed", "shelved", "rejected"} else None),
                rid,
                from_state,
            ),
        )
        if cur.rowcount == 0:
            raise ConcurrentTransitionError(
                f"review_record {rid} 状态推进失败：期望 {from_state}，已被并发修改"
            )
