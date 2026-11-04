# -*- coding: utf-8 -*-
"""快照 CLI：python -m riskqa.data.cli snapshot|verify

snapshot：从 CSV 生成带 manifest 的不可变快照
verify：按 manifest 校验快照完整性（双 hash）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .snapshot import SnapshotError, load_snapshot_file, write_snapshot

DEFAULT_ROOT = "data/snapshots"


def _snapshot(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.exists():
        print(f"snapshot 失败：输入文件不存在 {src.resolve()}", file=sys.stderr)
        return 1
    try:
        df = pd.read_csv(src, encoding="utf-8")
    except (OSError, ValueError, pd.errors.ParserError) as e:
        print(f"snapshot 失败：读取输入失败（{e}）", file=sys.stderr)
        return 1
    try:
        man = write_snapshot(df, source=args.source, data_as_of=args.as_of, root=args.root)
    except (SnapshotError, ValueError, OSError) as e:
        print(f"snapshot 失败：{e}", file=sys.stderr)
        return 1
    manifest_path = Path(args.root).resolve() / (man.locator + ".manifest.json")
    print(f"snapshot: {manifest_path}")
    print(f"  rows={man.rows} data_as_of={man.data_as_of} "
          f"data_hash={man.data_hash} file_hash={man.file_hash}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    try:
        _, man = load_snapshot_file(args.manifest)
    except (SnapshotError, ValueError, OSError) as e:
        print(f"verify 失败：{e}", file=sys.stderr)
        return 1
    print(f"verify: OK {Path(args.manifest).resolve()}")
    print(f"  rows={man.rows} data_as_of={man.data_as_of} "
          f"data_hash={man.data_hash} file_hash={man.file_hash}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m riskqa.data.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_snap = sub.add_parser("snapshot", help="从 CSV 生成快照 + manifest")
    p_snap.add_argument("--input", required=True, help="输入 CSV 路径")
    p_snap.add_argument("--source", required=True, help="数据源名（[A-Za-z0-9_.-]）")
    p_snap.add_argument("--as-of", required=True, help="业务数据日期 YYYY-MM-DD")
    p_snap.add_argument("--root", default=DEFAULT_ROOT, help="快照根目录")

    p_verify = sub.add_parser("verify", help="按 manifest 校验快照完整性")
    p_verify.add_argument("--manifest", required=True, help="manifest 路径")

    args = parser.parse_args(argv)
    if args.cmd == "snapshot":
        return _snapshot(args)
    return _verify(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
