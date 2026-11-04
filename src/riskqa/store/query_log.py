# -*- coding: utf-8 -*-
"""query_log DAO：raw log 只 INSERT；唯一合法 UPDATE 是 signature 回填。"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import decode_json, encode_json, now_ts


class QueryLogRepo:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, *, qid: str, question: str, sql: str, result_digest: Any,
               user: str, dept: str, ts: str | None = None, sql_edited: int = 0,
               confirmed_by: Any = None, signature: str | None = None) -> None:
        """无条件落 raw log；不提供 UPDATE/DELETE 通用入口（P-12）"""
        self._conn.execute(
            "INSERT INTO query_log (qid, question, sql, sql_edited, result_digest, "
            "user, dept, ts, confirmed_by, signature) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (qid, question, sql, int(sql_edited), encode_json(result_digest),
             user, dept, ts or now_ts(), encode_json(confirmed_by if confirmed_by is not None else []),
             signature))

    def get(self, qid: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM query_log WHERE qid=?", (qid,)).fetchone()
        return _decode_row(row)

    def list(self, *, limit: int = 100, user: str | None = None,
             since: str | None = None) -> list[dict]:
        sql = "SELECT * FROM query_log"
        cond, args = [], []
        if user is not None:
            cond.append("user=?")
            args.append(user)
        if since is not None:
            cond.append("ts>=?")
            args.append(since)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        return [_decode_row(r) for r in self._conn.execute(sql, args)]

    def backfill_signature(self, qid: str, signature: str) -> int:
        """仅 NULL → 值回填；已有签名或并发抢先时返回 0（触发器兜底）"""
        if not signature:
            raise ValueError("signature 不能为空——回填写入空值等于没回填")
        cur = self._conn.execute(
            "UPDATE query_log SET signature=? WHERE qid=? AND signature IS NULL",
            (signature, qid))
        return cur.rowcount


def _decode_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    data["result_digest"] = decode_json(data["result_digest"])
    data["confirmed_by"] = decode_json(data["confirmed_by"])
    return data
