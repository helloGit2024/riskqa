"""存储层冒烟：建表幂等、append-only、保留期、SqliteFactStore 往返。"""

from __future__ import annotations

import sqlite3

import pytest

from riskqa.store import InvalidFactValueError
from riskqa.store.facts import FactRepo, SqliteFactStore
from riskqa.store.query_log import QueryLogRepo
from riskqa.store.retention import purge_query_log
from riskqa.store.schema import init_db, verify_schema


def test_init_db_is_idempotent(db_conn):
    init_db(db_conn)
    init_db(db_conn)
    assert verify_schema(db_conn) == []


def test_query_log_is_append_only_except_signature_backfill(db_conn):
    repo = QueryLogRepo(db_conn)
    repo.insert(
        qid="Q0001",
        question="各渠道逾期",
        sql="SELECT 1 LIMIT 1",
        result_digest={"value": 0.2},
        user="u01",
        dept="风险策略部",
        ts="2025-01-01 00:00:00",
    )

    with pytest.raises(sqlite3.IntegrityError, match="P-12"):
        db_conn.execute("UPDATE query_log SET question='changed' WHERE qid='Q0001'")

    assert repo.backfill_signature("Q0001", "sig-1") == 1
    assert repo.backfill_signature("Q0001", "sig-2") == 0
    assert repo.get("Q0001")["signature"] == "sig-1"


def test_retention_only_deletes_old_rows(db_conn):
    repo = QueryLogRepo(db_conn)
    repo.insert(
        qid="Q-OLD",
        question="q",
        sql="SELECT 1 LIMIT 1",
        result_digest={},
        user="u",
        dept="d",
        ts="2025-01-01 00:00:00",
    )
    repo.insert(
        qid="Q-NEW",
        question="q",
        sql="SELECT 1 LIMIT 1",
        result_digest={},
        user="u",
        dept="d",
        ts="2026-10-01 00:00:00",
    )

    deleted = purge_query_log(db_conn, days=365, today="2026-10-30 00:00:00")
    assert deleted == 1
    assert repo.get("Q-OLD") is None
    assert repo.get("Q-NEW") is not None


def test_fact_is_append_only(db_conn):
    repo = FactRepo(db_conn)
    repo.insert(fid="F0001", value=0.5, unit="ratio", metric="pass_rate")
    with pytest.raises(sqlite3.IntegrityError, match="P-12"):
        db_conn.execute("DELETE FROM fact WHERE fid='F0001'")
    with pytest.raises(sqlite3.IntegrityError, match="P-12"):
        db_conn.execute("UPDATE fact SET value=0.9 WHERE fid='F0001'")


def test_sqlite_fact_store_roundtrip_and_nan_rejection(db_conn):
    store = SqliteFactStore(db_conn, data_as_of="2026-09-30")
    fid = store.put(0.5, "ratio", "pass_rate")
    assert fid == "F0001"

    fact = store.get(fid)
    assert (fact.fid, fact.value, fact.metric, fact.segment) == (
        "F0001",
        0.5,
        "pass_rate",
        "overall",
    )
    assert fact.data_as_of == "2026-09-30"
    assert store.manifest()["count"] == 1
    assert len(store.manifest()["sha256"]) == 64

    with pytest.raises(InvalidFactValueError, match="非有限数"):
        store.put(float("nan"), "ratio", "pass_rate")
    with pytest.raises(InvalidFactValueError, match="非有限数"):
        store.put(float("inf"), "ratio", "pass_rate")
    with pytest.raises(InvalidFactValueError, match="非数值"):
        store.put("not-a-number", "ratio", "pass_rate")

    # 拒收后事务已回滚，序号继续可用
    assert store.put(0.6, "ratio", "pass_rate") == "F0002"
