"""alert DAO：告警发送记录 + 认领（唯一放行 UPDATE 的表）。"""

from __future__ import annotations

import sqlite3


class AlertRepo:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, *, ts: str, channel: str, level: str, subject: str, body: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO alert (ts, channel, level, subject, body) VALUES (?,?,?,?,?)",
            (ts, channel, level, subject, body),
        )
        return int(cur.lastrowid)

    def list(self, *, acked: bool | None = None, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM alert"
        if acked is True:
            sql += " WHERE acked_by IS NOT NULL"
        elif acked is False:
            sql += " WHERE acked_by IS NULL"
        sql += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in self._conn.execute(sql, (limit,))]

    def ack(self, alert_id: int, acked_by: str) -> bool:
        """认领：已认领的不覆盖；返回是否本次认领成功"""
        cur = self._conn.execute(
            "UPDATE alert SET acked_by=? WHERE id=? AND acked_by IS NULL", (acked_by, alert_id)
        )
        return cur.rowcount == 1
