# -*- coding: utf-8 -*-
"""存储层 CLI：python -m riskqa.store.cli init|check --db <path>

默认库：data/ops.db（gitignore，只进备份）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .db import connect
from .schema import init_db, verify_schema

DEFAULT_DB = "data/ops.db"


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m riskqa.store.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="建库并执行 schema（幂等）")
    p_init.add_argument("--db", default=DEFAULT_DB)

    p_check = sub.add_parser("check", help="校验六表与索引齐全")
    p_check.add_argument("--db", default=DEFAULT_DB)

    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if args.cmd == "init":
        return _init(db_path)
    return _check(db_path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
