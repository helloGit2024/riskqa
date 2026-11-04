# -*- coding: utf-8 -*-
"""数据层：快照 + manifest（血缘）+ 缺失值归一。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Manifest:
    """血缘凭证：报告首页必须印出 data_as_of；同 spec + 同快照 → 产物一致"""
    source: str
    locator: str
    data_as_of: str
    rows: int
    data_hash: str


def normalize_missing(df: pd.DataFrame) -> pd.DataFrame:
    """入口只做一次：'' / 'unknown' / -999 一律归一为 NaN。
    绝不下游各自理解——这是两份报告数字对不上的常见根因。"""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].replace({"": np.nan, "unknown": np.nan, "Unknown": np.nan})
    return out.replace(-999, np.nan)


def load_snapshot(df: pd.DataFrame, source: str, locator: str, data_as_of: str):
    """生产里 locator 是 parquet 路径；这里直接吃内存 DataFrame。
    返回 (归一后的 df, manifest)——上层计算层只认这个二元组。"""
    norm = normalize_missing(df)
    digest = hashlib.sha256(
        pd.util.hash_pandas_object(norm, index=True).values.tobytes()).hexdigest()[:16]
    return norm, Manifest(source=source, locator=locator,
                          data_as_of=data_as_of, rows=len(norm), data_hash=digest)
