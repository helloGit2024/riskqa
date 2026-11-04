# -*- coding: utf-8 -*-
"""数据层：数据源注册表（新增数据源 = 加一个类，调用方零改动）。"""

from __future__ import annotations

import hashlib
from typing import Callable

import pandas as pd

from .snapshot import Manifest, load_snapshot_file, normalize_missing


class DataSourceRegistry:
    """数据源注册表：新增数据源 = 加一个类，调用方零改动"""

    def __init__(self):
        self._registry: dict[str, Callable] = {}

    def register(self, name: str):
        def deco(fn):
            self._registry[name] = fn
            return fn
        return deco

    def load(self, cfg: dict) -> tuple[pd.DataFrame, Manifest]:
        src = self._registry.get(cfg["type"])
        if src is None:
            raise KeyError(f"数据源 {cfg['type']!r} 未注册，已注册：{sorted(self._registry)}")
        loaded = src(cfg)
        if isinstance(loaded, tuple):  # 快照数据源自带 manifest（含 file_hash/columns）
            return loaded
        df = normalize_missing(loaded)
        man = Manifest(source=cfg["type"], locator=str(cfg.get("locator", "memory")),
                       data_as_of=cfg["as_of"], rows=len(df),
                       data_hash=hashlib.sha256(
                           pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()[:16])
        return df, man


REGISTRY = DataSourceRegistry()


@REGISTRY.register("memory")
def _load_memory(cfg: dict) -> pd.DataFrame:
    return cfg["frame"]


@REGISTRY.register("csv")
def _load_csv(cfg: dict) -> pd.DataFrame:
    return pd.read_csv(cfg["locator"])


@REGISTRY.register("snapshot")
def _load_snapshot_cfg(cfg: dict) -> tuple[pd.DataFrame, Manifest]:
    """正式数据源：manifest 是唯一入口，加载时做双 hash 校验（P-12）"""
    return load_snapshot_file(cfg["manifest"], root=cfg.get("root"))


def load_data(cfg: dict) -> tuple[pd.DataFrame, Manifest]:
    """上层唯一入口：返回 (df, manifest)。数据源类型是配置，不是代码分支"""
    return REGISTRY.load(cfg)
