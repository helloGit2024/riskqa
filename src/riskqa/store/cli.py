# -*- coding: utf-8 -*-
"""存储层 CLI：python -m riskqa.store.cli init|check|purge --db <path>

默认库：data/ops.db（gitignore，只进备份）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..governance.config import GovernanceError, load_governance_file
from .db import connect
from .retention import purge_query_log
from .schema import init_db, verify_schema

DEFAULT_DB = "data/ops.db"
DEFAULT_GOVERNANCE = "config/governance.yaml"


def _init(db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()
    print(f"init: {db_path.resolve()}")
    return 0


def _check(db_path: Path) -> int:
    if not db_path.exists():
        print(f"check 失败：库不存在 {db_path.resolve()}（先执行 init）", file=sys.stderr)
        return 1
    conn = connect(db_path)
    try:
        errs = verify_schema(conn)
    finally:
        conn.close()
    if errs:
        print("check 失败：" + "；".join(errs), file=sys.stderr)
        return 1
    print(f"check: OK（6 表 + 9 索引，{db_path.resolve()}）")
    return 0


def _purge(db_path: Path, config_path: Path) -> int:
    if not db_path.exists():
        print(f"purge 失败：库不存在 {db_path.resolve()}（先执行 init）", file=sys.stderr)
        return 1
    if not config_path.exists():
        print(f"purge 失败：治理配置不存在 {config_path.resolve()}——retention_days 必须来自配置（P-15）",
              file=sys.stderr)
        return 1
    try:
        cfg = load_governance_file(config_path)
    except GovernanceError as e:
        print(f"purge 失败：{e}", file=sys.stderr)
        return 1
    conn = connect(db_path)
    try:
        deleted = purge_query_log(conn, cfg.retention_days)
    finally:
        conn.close()
    print(f"purge: 删除 {deleted} 行（retention_days={cfg.retention_days}，{db_path.resolve()}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m riskqa.store.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="建库并执行 schema（幂等）")
    p_init.add_argument("--db", default=DEFAULT_DB)

    p_check = sub.add_parser("check", help="校验六表与索引齐全")
    p_check.add_argument("--db", default=DEFAULT_DB)

    p_purge = sub.add_parser("purge", help="按治理配置的 retention_days 清理旧 raw log")
    p_purge.add_argument("--db", default=DEFAULT_DB)
    p_purge.add_argument("--config", default=DEFAULT_GOVERNANCE)

    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if args.cmd == "init":
        return _init(db_path)
    if args.cmd == "purge":
        return _purge(db_path, Path(args.config))
    return _check(db_path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
