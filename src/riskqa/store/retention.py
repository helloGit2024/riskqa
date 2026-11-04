# -*- coding: utf-8 -*-
"""保留期清理：唯一 DELETE 路径，只清 query_log，期限由调用方传入。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta


def purge_query_log(conn: sqlite3.Connection, days: int,
                    today: str | None = None) -> int:
    """删除 ts < today - days 的 raw log，返回删除行数。

    days 必须显式传入（来自 config/governance.yaml 的 retention_days）——
    代码内不内嵌 365，守住 P-15 的单一事实源。
    """
    if not isinstance(days, int) or days <= 0:
        raise ValueError("days 必须是正整数（retention_days 从治理配置读取，P-15）")
    base = datetime.strptime(today, "%Y-%m-%d %H:%M:%S") if today else datetime.now()
    cutoff = (base - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("DELETE FROM query_log WHERE ts < ?", (cutoff,))
    return cur.rowcount
