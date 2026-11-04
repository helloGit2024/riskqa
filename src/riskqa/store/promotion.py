# -*- coding: utf-8 -*-
"""promotion DAO：只追加；evidence 自包含快照存 JSON。"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import decode_json, encode_json


class PromotionRepo:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, *, pid: str, metric: str, signature: str, promoted_at: str,
               owner: str, evidence: Any, aliases_added: Any,
               calc_registered: int = 0) -> None:
        self._conn.execute(
            "INSERT INTO promotion (pid, metric, signature, promoted_at, owner, "
            "evidence, aliases_added, calc_registered) VALUES (?,?,?,?,?,?,?,?)",
            (pid, metric, signature, promoted_at, owner, encode_json(evidence),
             encode_json(aliases_added), int(calc_registered)))

    def get(self, pid: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM promotion WHERE pid=?", (pid,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["evidence"] = decode_json(data["evidence"])
        data["aliases_added"] = decode_json(data["aliases_added"])
        return data

    def list(self, *, metric: str | None = None, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM promotion"
        args: list = []
        if metric is not None:
            sql += " WHERE metric=?"
            args.append(metric)
        sql += " ORDER BY promoted_at DESC LIMIT ?"
        args.append(limit)
        rows = []
        for r in self._conn.execute(sql, args):
            data = dict(r)
            data["evidence"] = decode_json(data["evidence"])
            data["aliases_added"] = decode_json(data["aliases_added"])
            rows.append(data)
        return rows
