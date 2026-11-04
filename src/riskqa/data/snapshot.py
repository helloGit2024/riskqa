# -*- coding: utf-8 -*-
"""数据层：快照 + manifest（血缘）+ 缺失值归一。

正式数字永远基于带 manifest 的快照（P-12）：
- 写入：DataFrame → 归一 → CSV（原子落盘）→ manifest（双 hash）
- 读取：manifest → 校验文件字节 hash → 读回 → 列序/dtype 还原 → 语义 hash 校验
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class SnapshotError(Exception):
    """快照层错误基类——显式失败，不静默降级（P-14）"""


class ManifestNotFoundError(SnapshotError):
    """manifest 或数据文件缺失"""


class SnapshotIntegrityError(SnapshotError):
    """hash 不符、列序/dtype 还原失败、manifest 被篡改"""


class UnsupportedFormatError(SnapshotError):
    """不支持的快照格式"""


class ParquetEngineMissingError(SnapshotError):
    """请求 Parquet 但未安装引擎（R16 未批准，本批只做 CSV）"""


@dataclass(frozen=True)
class Manifest:
    """血缘凭证：报告首页必须印出 data_as_of；同 spec + 同快照 → 产物一致"""
    source: str
    locator: str
    data_as_of: str
    rows: int
    data_hash: str
    columns: tuple[str, ...] = ()
    schema_version: int = 1
    file_hash: str = ""
    created_at: str = ""
    format: str = "csv"
    dtypes: dict[str, str] | None = None


# ---------- 既有内存版行为（保持不变） ----------

def normalize_missing(df: pd.DataFrame) -> pd.DataFrame:
    """入口只做一次：'' / 'unknown' / -999 一律归一为 NaN。
    绝不下游各自理解——这是两份报告数字对不上的常见根因。"""
    out = df.copy()
    for col in out.columns:
        dtype = out[col].dtype
        # pandas 2 的字符串列是 object；pandas 3 是 str（StringDtype），两种都要归一
        if dtype == object or isinstance(dtype, pd.StringDtype):
            out[col] = out[col].replace({"": np.nan, "unknown": np.nan, "Unknown": np.nan})
    return out.replace(-999, np.nan)


def load_snapshot(df: pd.DataFrame, source: str, locator: str, data_as_of: str):
    """生产里 locator 是 parquet 路径；这里直接吃内存 DataFrame。
    返回 (归一后的 df, manifest)——上层计算层只认这个二元组。"""
    norm = normalize_missing(df)
    return norm, Manifest(source=source, locator=locator,
                          data_as_of=data_as_of, rows=len(norm),
                          data_hash=_data_hash(norm))


# ---------- 落盘与读回 ----------

_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SOURCE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_FORMATS = {"csv": ".csv", "parquet": ".parquet"}


def _data_hash(norm: pd.DataFrame) -> str:
    """legacy 语义 hash：归一后 DataFrame 的 16 位摘要（含索引）"""
    return hashlib.sha256(
        pd.util.hash_pandas_object(norm, index=True).values.tobytes()).hexdigest()[:16]


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_as_of(data_as_of: str) -> None:
    if not isinstance(data_as_of, str) or not _AS_OF_RE.match(data_as_of):
        raise ValueError(f"data_as_of 必须是 YYYY-MM-DD：{data_as_of!r}")
    try:
        datetime.strptime(data_as_of, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"data_as_of 不是合法日期：{data_as_of!r}（{e}）")


def _validate_source(source: str) -> None:
    if not isinstance(source, str) or not _SOURCE_RE.match(source) or source in {".", ".."}:
        raise ValueError(f"source 只允许 [A-Za-z0-9_.-] 且不能是 . / ..：{source!r}")


def _manifest_dict(man: Manifest) -> dict[str, Any]:
    return {
        "schema_version": man.schema_version,
        "source": man.source,
        "locator": man.locator,
        "format": man.format,
        "data_as_of": man.data_as_of,
        "rows": man.rows,
        "columns": list(man.columns),
        "dtypes": man.dtypes,
        "data_hash": man.data_hash,
        "file_hash": man.file_hash,
        "created_at": man.created_at,
    }


def _manifest_from_dict(data: dict[str, Any]) -> Manifest:
    required = ("source", "locator", "data_as_of", "rows", "data_hash", "file_hash")
    missing = [k for k in required if k not in data]
    if missing:
        raise SnapshotIntegrityError(f"manifest 缺字段：{missing}")
    return Manifest(
        source=data["source"], locator=data["locator"],
        data_as_of=data["data_as_of"], rows=int(data["rows"]),
        data_hash=data["data_hash"],
        columns=tuple(data.get("columns") or ()),
        schema_version=int(data.get("schema_version", 1)),
        file_hash=data["file_hash"],
        created_at=data.get("created_at", ""),
        format=data.get("format", "csv"),
        dtypes=data.get("dtypes"),
    )


def _read_manifest(path: Path) -> Manifest:
    if not path.exists():
        raise ManifestNotFoundError(f"manifest 不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise SnapshotIntegrityError(f"manifest 解析失败：{path}（{e}）")
    if not isinstance(data, dict):
        raise SnapshotIntegrityError(f"manifest 顶层必须是对象：{path}")
    return _manifest_from_dict(data)


def write_snapshot(df: pd.DataFrame, *, source: str, data_as_of: str,
                   root: str | Path = "data/snapshots", fmt: str = "csv") -> Manifest:
    """从 DataFrame 生成不可变快照 + manifest；返回 manifest。

    文件名 `<source>__<data_as_of>__<data_hash前8位>.<ext>`；同数据重复写幂等，
    同名不同内容显式报错，绝不覆盖（P-12）。
    """
    _validate_source(source)
    _validate_as_of(data_as_of)
    if fmt == "parquet":
        raise ParquetEngineMissingError(
            "Parquet 引擎未安装（pyarrow/fastparquet 均缺）；本批只支持 CSV，见 R16/T-4.0.5")
    if fmt not in _FORMATS:
        raise UnsupportedFormatError(f"不支持的快照格式：{fmt!r}（仅 csv）")
    if not isinstance(df.index, pd.RangeIndex):
        raise ValueError(f"快照要求 RangeIndex，实际 {type(df.index).__name__}——hash 口径依赖它")
    bad_cols = [c for c in df.columns if not isinstance(c, str)]
    if bad_cols:
        raise ValueError(f"列名必须全部是字符串：{bad_cols!r}")

    norm = normalize_missing(df)
    digest = _data_hash(norm)
    columns = tuple(str(c) for c in norm.columns)
    dtypes = {str(c): str(norm[c].dtype) for c in norm.columns}

    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    filename = f"{source}__{data_as_of}__{digest[:8]}.{fmt}"
    data_path = root_path / filename
    manifest_path = data_path.with_name(data_path.name + ".manifest.json")

    tmp_data = _temp_path(root_path, filename)
    tmp_manifest = _temp_path(root_path, filename + ".manifest.json")
    try:
        norm.to_csv(tmp_data, index=False, encoding="utf-8", lineterminator="\n")
        file_hash = _file_hash(tmp_data)
        manifest = Manifest(source=source, locator=filename, data_as_of=data_as_of,
                            rows=len(norm), data_hash=digest, columns=columns,
                            schema_version=1, file_hash=file_hash,
                            created_at=_now_ts(), format=fmt, dtypes=dtypes)
        tmp_manifest.write_text(
            json.dumps(_manifest_dict(manifest), ensure_ascii=False,
                       sort_keys=True, indent=2) + "\n", encoding="utf-8")

        if data_path.exists() or manifest_path.exists():
            existing = _reuse_existing(data_path, manifest_path, manifest)
            return existing
        os.replace(tmp_data, data_path)
        os.replace(tmp_manifest, manifest_path)

        # 写完立刻回读自校验：写-读-hash 闭环失败就删掉刚写的两份文件
        try:
            _, checked = load_snapshot_file(manifest_path, root=root_path)
        except SnapshotError:
            data_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            raise
        return checked
    finally:
        tmp_data.unlink(missing_ok=True)
        tmp_manifest.unlink(missing_ok=True)


def _reuse_existing(data_path: Path, manifest_path: Path,
                    fresh: Manifest) -> Manifest:
    """同名文件已存在：同内容幂等复用，不同内容显式拒绝覆盖"""
    if not data_path.exists():
        raise SnapshotIntegrityError(
            f"manifest 已存在但数据文件缺失：{manifest_path}")
    if _file_hash(data_path) != fresh.file_hash:
        raise SnapshotIntegrityError(
            f"同名快照已存在且内容不同，拒绝覆盖：{data_path}")
    if not manifest_path.exists():
        raise SnapshotIntegrityError(
            f"数据文件已存在但 manifest 缺失（血缘不完整）：{data_path}")
    existing = _read_manifest(manifest_path)
    if (existing.data_hash != fresh.data_hash or existing.source != fresh.source
            or existing.data_as_of != fresh.data_as_of):
        raise SnapshotIntegrityError(
            f"同名文件与已有 manifest 不一致，拒绝覆盖：{manifest_path}")
    return existing


def _temp_path(root: Path, filename: str) -> Path:
    fd, name = tempfile.mkstemp(dir=str(root), prefix=f".{filename}.", suffix=".tmp")
    os.close(fd)
    return Path(name)


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_snapshot_file(manifest_path: str | Path, *,
                       root: str | Path | None = None) -> tuple[pd.DataFrame, Manifest]:
    """按 manifest 加载快照并做双 hash 校验；任何不一致都显式报错。"""
    manifest_path = Path(manifest_path)
    man = _read_manifest(manifest_path)

    if man.format == "parquet":
        raise ParquetEngineMissingError(
            "Parquet 引擎未安装（pyarrow/fastparquet 均缺）；本批只支持 CSV，见 R16/T-4.0.5")
    if man.format != "csv":
        raise UnsupportedFormatError(f"不支持的快照格式：{man.format!r}（仅 csv）")
    if not man.file_hash:
        raise SnapshotIntegrityError(f"manifest 缺 file_hash，无法校验：{manifest_path}")

    base = Path(root).resolve() if root is not None else manifest_path.resolve().parent
    data_path = _resolve_within(base, man.locator)
    if not data_path.exists():
        raise ManifestNotFoundError(f"数据文件不存在：{data_path}")

    if _file_hash(data_path) != man.file_hash:
        raise SnapshotIntegrityError("文件被篡改/损坏")

    try:
        raw = pd.read_csv(data_path, encoding="utf-8")
    except (OSError, ValueError, pd.errors.ParserError) as e:
        raise SnapshotIntegrityError(f"快照读取失败：{data_path}（{e}）")

    if man.columns:
        if set(raw.columns) != set(man.columns) or len(raw.columns) != len(man.columns):
            raise SnapshotIntegrityError(
                f"列集合与 manifest 不一致：文件 {list(raw.columns)} vs {list(man.columns)}")
        raw = raw[list(man.columns)]

    for col, dtype in (man.dtypes or {}).items():
        if col not in raw.columns:
            raise SnapshotIntegrityError(f"manifest 记录的列不存在：{col}")
        try:
            raw[col] = raw[col].astype(dtype)
        except (TypeError, ValueError) as e:
            raise SnapshotIntegrityError(f"列 {col} 还原为 {dtype} 失败（{e}）")

    norm = normalize_missing(raw)
    if _data_hash(norm) != man.data_hash:
        raise SnapshotIntegrityError(
            "读回数据与 manifest 的 data_hash 不一致（列序/dtype/归一化）")
    if len(norm) != man.rows:
        raise SnapshotIntegrityError(f"行数与 manifest 不一致：{len(norm)} vs {man.rows}")
    return norm, man


def _resolve_within(base: Path, locator: str) -> Path:
    """locator 必须是快照根内的相对路径；绝对路径或 .. 一律拒绝"""
    target = Path(locator)
    if target.is_absolute():
        raise SnapshotIntegrityError(f"locator 不允许绝对路径：{locator}")
    resolved = (base / target).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise SnapshotIntegrityError(f"locator 逃出快照根目录：{locator}")
    return resolved
