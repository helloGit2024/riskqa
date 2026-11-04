"""连接层：统一 PRAGMA、显式事务、时间戳与 JSON 编解码。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any


def now_ts() -> str:
    """统一时间戳：YYYY-MM-DD HH:MM:SS 本地时间"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path: str | Path) -> sqlite3.Connection:
    """打开连接：WAL + 外键 + 5s 忙等 + NORMAL 同步；自动提交交给 transaction()"""
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """单写事务：BEGIN IMMEDIATE，异常回滚；已在事务中则直接复用"""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def encode_json(value: Any) -> str:
    """JSON 字段落库：已是字符串则原样存（调用方保证是 JSON 文本）"""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_json(text: str | None) -> Any:
    """JSON 字段读出：解析失败按原文返回，不静默丢数据"""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text
