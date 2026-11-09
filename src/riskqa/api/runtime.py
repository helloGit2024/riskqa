"""API 运行时：run 级事实隔离、强制慢路代理、归一键与 id 生成。

为什么不直接复用 `SqliteFactStore`：
- 它 `digest()` 返回全表事实，校验闸回退模板会把历史事实全列出来；
- SQLite 连接不能跨线程，图又只构建一次（interrupt 续跑要求同一 checkpointer）。
因此图持有一个 `SharedFactStore` 代理，按请求上下文切换到本次 run 的
`RunFactStore`（fid 仍由数据库全局续号）。`store/` 与 `orchestration/` 零改动。
"""

from __future__ import annotations

import hashlib
import itertools
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from typing import Any

from ..store.db import connect
from ..store.facts import SqliteFactStore

AI_DISCLOSURE = "本回答由 AI 生成；数字来自语义层已签字口径，引用可回查。"

# 引擎分级（auto/sample/must）→ 契约枚举（none/spot/must）
ENGINE_TO_CONTRACT = {"auto": "none", "sample": "spot", "must": "must"}

_counter = itertools.count(1)


def new_id(prefix: str) -> str:
    """契约 id：R/Q 前缀 + 纯数字（ReviewRecord.rid 要求 ^R[0-9]+$）"""
    return f"{prefix}{int(time.time() * 1000)}{next(_counter) % 1000:03d}"


def build_signature(
    metric: str, group_by: str = "", scope: dict[str, Any] | None = None, time_range: str = "all"
) -> str:
    """(metric,dims,filters,time_range) 归一键；filters 按键排序保证稳定"""
    filters = (scope or {}).get("filters") or {}
    fstr = ",".join(f"{k}={filters[k]}" for k in sorted(filters))
    return f"{metric}|{group_by or ''}|{fstr}|{time_range or 'all'}"


class RunFactStore:
    """一次请求的事实视图：写库走全局续号，digest 只看本次 run。"""

    def __init__(self, backing: SqliteFactStore, qid: str) -> None:
        self._backing = backing
        self._qid = qid
        self._fids: list[str] = []

    def put(
        self,
        value: Any,
        unit: str,
        metric: str,
        segment: str = "overall",
        source: str = "fast",
        qid: str | None = None,
    ) -> str:
        fid = self._backing.put(
            value, unit, metric, segment=segment, source=source, qid=qid or self._qid
        )
        self._fids.append(fid)
        return fid

    def get(self, fid: str):
        return self._backing.get(fid)

    def digest(self) -> list[dict]:
        return [asdict(self._backing.get(fid)) for fid in self._fids]

    def manifest(self) -> dict:
        raw = json.dumps(self.digest(), sort_keys=True, ensure_ascii=False, default=str)
        return {"count": len(self._fids), "sha256": hashlib.sha256(raw.encode()).hexdigest()}


_current: ContextVar[RunFactStore | None] = ContextVar("riskqa_api_run_facts", default=None)


class SharedFactStore:
    """图持有的稳定代理：真正的事实落在当前请求的 RunFactStore 上。"""

    def _require(self) -> RunFactStore:
        store = _current.get()
        if store is None:
            raise RuntimeError("事实读写发生在 run_scope 之外——API 层缺陷，拒绝继续")
        return store

    def put(self, *args, **kwargs) -> str:
        return self._require().put(*args, **kwargs)

    def get(self, fid: str):
        return self._require().get(fid)

    def digest(self) -> list[dict]:
        return self._require().digest()

    def manifest(self) -> dict:
        return self._require().manifest()


@contextmanager
def run_scope(deps, qid: str):
    """一次请求：短连接 + 独立事实视图；退出即复位，绝不泄漏到下一个请求"""
    conn = connect(deps.db_path)
    try:
        store = RunFactStore(
            SqliteFactStore(conn, deps.manifest.data_as_of if deps.manifest else ""), qid
        )
        token = _current.set(store)
        try:
            yield store
        finally:
            _current.reset(token)
    finally:
        conn.close()


class SlowOnlySemantic:
    """explore 的强制慢路语义：仅把 match_metric 固定为 None，其余全部委托。

    编排层 `entry_route` 只看 `sem.match_metric`；API 不改编排层，因此在这条
    链路上包一层代理，让语义层命中也走慢路。数字计算与行权限仍走原语义层。
    """

    def __init__(self, inner) -> None:
        object.__setattr__(self, "_inner", inner)

    def match_metric(self, question: str) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_inner"), name)


def spec_from_sem(sem) -> dict:
    """校验闸重算用的指标清单：全部来自语义层（P-15），不内嵌默认值"""
    return {
        "metrics": [
            {"name": name, "calc": meta["calc"]}
            for name, meta in sem.metrics.items()
            if meta.get("calc")
        ]
    }


def public_fact(fact: dict) -> dict:
    """按 FactRef 白名单投影，避免把内部字段漏给调用方"""
    return {
        "fid": fact["fid"],
        "value": fact["value"],
        "unit": fact["unit"],
        "segment": fact.get("segment", ""),
    }
