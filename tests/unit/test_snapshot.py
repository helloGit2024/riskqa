"""快照与 manifest 单测：往返、篡改、幂等、Parquet 缺失。"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from riskqa.data.snapshot import (
    ManifestNotFoundError,
    ParquetEngineMissingError,
    SnapshotIntegrityError,
    load_snapshot_file,
    normalize_missing,
    write_snapshot,
)


def _demo_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "channel": ["A", "B"],
            "is_pass": [1, 0],
            "score": [0.5, 0.7],
        }
    )


def test_write_and_load_roundtrip(snapshot_root):
    df = _demo_frame()
    man = write_snapshot(df, source="fact_application", data_as_of="2026-09-30", root=snapshot_root)
    assert man.rows == 2
    assert man.columns == ("channel", "is_pass", "score")
    assert man.format == "csv"
    assert len(man.file_hash) == 64
    assert len(man.data_hash) == 16

    manifest_path = snapshot_root / (man.locator + ".manifest.json")
    loaded, checked = load_snapshot_file(manifest_path, root=snapshot_root)
    assert checked.data_hash == man.data_hash
    pd.testing.assert_frame_equal(loaded, normalize_missing(df))


def test_same_data_is_idempotent(snapshot_root):
    df = _demo_frame()
    first = write_snapshot(
        df, source="fact_application", data_as_of="2026-09-30", root=snapshot_root
    )
    second = write_snapshot(
        df, source="fact_application", data_as_of="2026-09-30", root=snapshot_root
    )
    assert (second.locator, second.data_hash, second.file_hash) == (
        first.locator,
        first.data_hash,
        first.file_hash,
    )


def test_tampered_file_is_rejected(snapshot_root):
    man = write_snapshot(
        _demo_frame(), source="fact_application", data_as_of="2026-09-30", root=snapshot_root
    )
    data_path = snapshot_root / man.locator
    data_path.write_text(data_path.read_text(encoding="utf-8") + "tampered,\n", encoding="utf-8")
    with pytest.raises(SnapshotIntegrityError, match="篡改"):
        load_snapshot_file(snapshot_root / (man.locator + ".manifest.json"), root=snapshot_root)


def test_parquet_is_explicitly_unsupported(snapshot_root):
    with pytest.raises(ParquetEngineMissingError, match="Parquet"):
        write_snapshot(
            _demo_frame(),
            source="fact_application",
            data_as_of="2026-09-30",
            root=snapshot_root,
            fmt="parquet",
        )


def test_missing_manifest_raises(snapshot_root):
    with pytest.raises(ManifestNotFoundError):
        load_snapshot_file(snapshot_root / "nope.manifest.json", root=snapshot_root)


def test_locator_cannot_escape_snapshot_root(snapshot_root):
    evil = {
        "source": "fact_application",
        "locator": "../evil.csv",
        "data_as_of": "2026-09-30",
        "rows": 0,
        "data_hash": "x",
        "file_hash": "x",
        "format": "csv",
    }
    path = snapshot_root / "evil.manifest.json"
    path.write_text(json.dumps(evil), encoding="utf-8")
    with pytest.raises(SnapshotIntegrityError, match="逃出"):
        load_snapshot_file(path, root=snapshot_root)
