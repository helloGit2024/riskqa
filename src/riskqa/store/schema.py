# -*- coding: utf-8 -*-
"""schema 初始化与自检：幂等建表 + 六表/索引存在性检查。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import SchemaError

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

TABLES = ("query_log", "fact", "review_record", "promotion", "audit_entry", "alert")
INDEXES = (
    "idx_ql_ts", "idx_ql_user", "idx_ql_sig",
    "idx_fact_metric",
    "idx_rr_state", "idx_rr_assignee",
    "idx_promo_metric",
    "idx_audit_ts", "idx_audit_actor",
)


def init_db(conn: sqlite3.Connection) -> None:
    """幂等执行 schema.sql，并把 schema 版本记为 1"""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("PRAGMA user_version=1")


def verify_schema(conn: sqlite3.Connection) -> list[str]:
    """返回缺失项清单；空列表 = 六表与九个索引齐全"""
    have_tables = {
        row["name"] for row in
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    have_indexes = {
        row["name"] for row in
        conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    errs = [f"缺表 {name}" for name in TABLES if name not in have_tables]
    errs += [f"缺索引 {name}" for name in INDEXES if name not in have_indexes]
    return errs


def require_schema(conn: sqlite3.Connection) -> None:
    """ DAO 使用前的硬检查：schema 不全直接失败（不静默降级）"""
    errs = verify_schema(conn)
    if errs:
        raise SchemaError("运营库 schema 不完整：" + "；".join(errs))
