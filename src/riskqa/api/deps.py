"""进程级依赖容器与数据库连接助手。

SQLite 连接不能跨线程复用（FastAPI 同步端点跑在线程池），因此只持有路径，
每个请求开一条短连接；启动时单独校验 schema（fail fast）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..data.snapshot import Manifest
from ..governance.config import GovernanceConfig
from ..llm.fake import FakeLLM
from ..semantic.layer import SemanticLayer
from ..store.db import connect


@dataclass
class AppDeps:
    sem: SemanticLayer
    df: pd.DataFrame
    governance: GovernanceConfig
    db_path: Path
    manifest: Manifest | None
    llm_factory: Callable[[], FakeLLM]


@contextmanager
def open_db(deps: AppDeps) -> Iterator[sqlite3.Connection]:
    """请求级连接：用完即关，避免线程归属问题"""
    conn = connect(deps.db_path)
    try:
        yield conn
    finally:
        conn.close()
