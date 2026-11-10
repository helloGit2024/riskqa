"""demo 快照：synthetic 硬标识、DEMO 日期约束与加载器 demo 模式闸门。"""

from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import pytest

from riskqa.api.routers.ops import health_payload
from riskqa.data.snapshot import (
    SnapshotIntegrityError,
    SyntheticSnapshotError,
    load_snapshot_file,
    normalize_missing,
    write_snapshot,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"channel": ["A", "B"], "is_pass": [1, 0], "score": [0.5, 0.7]})


def test_synthetic_requires_demo_as_of(snapshot_root):
    with pytest.raises(ValueError, match="DEMO"):
        write_snapshot(
            _frame(), source="demo", data_as_of="2026-09-30", root=snapshot_root, synthetic=True
        )


def test_non_synthetic_rejects_demo_as_of(snapshot_root):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        write_snapshot(_frame(), source="demo", data_as_of="DEMO", root=snapshot_root)


def test_synthetic_roundtrip_keeps_flag(snapshot_root, monkeypatch):
    monkeypatch.setenv("RISKQA_MODE", "demo")
    man = write_snapshot(
        _frame(), source="demo_application", data_as_of="DEMO", root=snapshot_root, synthetic=True
    )

    assert man.synthetic is True
    assert man.data_as_of == "DEMO"
    assert man.locator.startswith("demo_application__DEMO__")

    manifest_path = snapshot_root / (man.locator + ".manifest.json")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert raw["synthetic"] is True
    assert raw["data_as_of"] == "DEMO"

    loaded, checked = load_snapshot_file(manifest_path, root=snapshot_root, mode="demo")
    assert checked.synthetic is True
    pd.testing.assert_frame_equal(loaded, normalize_missing(_frame()))


def test_loader_rejects_synthetic_outside_demo(snapshot_root, monkeypatch):
    """非 demo 模式加载 synthetic → 显式拒绝（R14 / P-12），不静默放行。"""
    monkeypatch.setenv("RISKQA_MODE", "demo")
    man = write_snapshot(
        _frame(), source="demo_application", data_as_of="DEMO", root=snapshot_root, synthetic=True
    )
    manifest_path = snapshot_root / (man.locator + ".manifest.json")

    monkeypatch.delenv("RISKQA_MODE", raising=False)
    with pytest.raises(SyntheticSnapshotError, match="RISKQA_MODE=demo"):
        load_snapshot_file(manifest_path, root=snapshot_root)

    monkeypatch.setenv("RISKQA_MODE", "production")
    with pytest.raises(SyntheticSnapshotError, match="拒绝启动"):
        load_snapshot_file(manifest_path, root=snapshot_root)


def test_loader_allows_synthetic_in_demo_env(snapshot_root, monkeypatch):
    monkeypatch.setenv("RISKQA_MODE", "demo")
    man = write_snapshot(
        _frame(), source="demo_application", data_as_of="DEMO", root=snapshot_root, synthetic=True
    )

    _, checked = load_snapshot_file(
        snapshot_root / (man.locator + ".manifest.json"), root=snapshot_root
    )
    assert checked.synthetic is True


def test_old_manifest_without_synthetic_is_backward_compatible(snapshot_root):
    """旧 manifest 无 synthetic 字段 → 按非 synthetic 处理，照常加载。"""
    man = write_snapshot(
        _frame(), source="fact_application", data_as_of="2026-09-30", root=snapshot_root
    )
    manifest_path = snapshot_root / (man.locator + ".manifest.json")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw.pop("synthetic", None)
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    _, checked = load_snapshot_file(manifest_path, root=snapshot_root)
    assert checked.synthetic is False


def test_synthetic_manifest_with_real_date_is_rejected(snapshot_root):
    """手改 manifest 把 synthetic 配真实日期 → 加载即失败，不允许伪装业务日期。"""
    man = write_snapshot(
        _frame(), source="fact_application", data_as_of="2026-09-30", root=snapshot_root
    )
    manifest_path = snapshot_root / (man.locator + ".manifest.json")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["synthetic"] = True
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    with pytest.raises(SnapshotIntegrityError, match="不得写成真实日期"):
        load_snapshot_file(manifest_path, root=snapshot_root, mode="demo")


def test_health_marks_synthetic_snapshot(api_deps, api_settings):
    """health 返回 data_mode=demo-synthetic，latest=DEMO，一眼可见是模拟数据。"""
    man = replace(api_deps.manifest, data_as_of="DEMO", synthetic=True)
    code, body = health_payload(replace(api_deps, manifest=man), api_settings)

    assert body["data_mode"] == "demo-synthetic"
    assert body["snapshot"]["latest"] == "DEMO"
    assert code == 503  # FakeLLM 仍让三态为 degraded


def test_health_marks_production_snapshot(api_deps, api_settings):
    _, body = health_payload(api_deps, api_settings)

    assert body["data_mode"] == "production"
    assert body["snapshot"]["latest"] == "2026-09-30"
