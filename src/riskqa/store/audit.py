# -*- coding: utf-8 -*-
"""audit_entry DAO：旁路审计只追加；aid 自增。"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import decode_json, encode_json


class AuditRepo:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, *, ts: str, actor: str, action: str, prev_hash: str,
               target: str | None = None, detail: Any = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO audit_entry (ts, actor, action, target, detail, prev_hash) "
            "VALUES (?,?,?,?,?,?)",
            (ts, actor, action, target, None if detail is None else encode_json(detail),
             prev_hash))
        return int(cur.lastrowid)

    def list(self, *, actor: str | None = None, action: str | None = None,
             limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM audit_entry"
        cond, args = [], []
        if actor is not None:
            cond.append("actor=?")
            args.append(actor)
        if action is not None:
            cond.append("action=?")
            args.append(action)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY aid DESC LIMIT ?"
        args.append(limit)
        rows = []
        for r in self._conn.execute(sql, args):
            data = dict(r)
            data["detail"] = decode_json(data["detail"])
            rows.append(data)
        return rows
