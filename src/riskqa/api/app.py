"""FastAPI 应用工厂（T-4.1.5）。

启动顺序（任一失败即拒绝启动，R14）：
1. `load_settings()`：token 表缺失 → SettingsError（P-01/P-10）
2. 语义层 / 治理配置：口径与参数只从 config/ 读（P-15）
3. ops.db：建表幂等校验
4. 最新快照 manifest：正式数字必须基于快照（P-12），没有就起不来

`create_app(deps=..., settings=...)` 供测试注入，不触碰磁盘与环境变量。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI

from ..data.snapshot import Manifest, load_snapshot_file
from ..governance.config import load_governance_file
from ..llm.fake import FakeLLM
from ..orchestration.graph_qa import build_qa_graph
from ..orchestration.observer import Observer
from ..semantic.layer import load_semantic
from ..store.db import connect
from ..store.schema import init_db, verify_schema
from .deps import AppDeps
from .errors import install_error_handler
from .routers import ask, evidence, governance, ops, review
from .runtime import SharedFactStore, SlowOnlySemantic, spec_from_sem
from .settings import Settings, load_settings


def latest_snapshot(snapshot_dir: Path) -> tuple[pd.DataFrame, Manifest]:
    """取最新的快照（按 data_as_of 排序）；没有就显式失败，不用裸数据顶替"""
    manifests = sorted(snapshot_dir.glob("*.manifest.json"))
    if not manifests:
        raise RuntimeError(
            f"未找到快照 manifest：{snapshot_dir}。正式数字必须基于快照（P-12），"
            "请先运行 `python -m riskqa.data.cli snapshot` 生成"
        )
    errors: list[str] = []
    best: tuple[pd.DataFrame, Manifest] | None = None
    for path in manifests:
        try:
            loaded = load_snapshot_file(path)
        except Exception as e:  # noqa: BLE001  # 逐个探测，最终整体报错
            errors.append(f"{path.name}: {e}")
            continue
        if best is None or loaded[1].data_as_of >= best[1].data_as_of:
            best = loaded
    if best is None:
        raise RuntimeError("全部快照加载失败：" + "；".join(errors))
    return best


def _load_deps(st: Settings) -> AppDeps:
    sem = load_semantic(st.semantic_path)
    governance = load_governance_file(st.governance_path)

    st.ops_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(st.ops_db_path)
    try:
        init_db(conn)
        db_errors = verify_schema(conn)
    finally:
        conn.close()
    if db_errors:
        raise RuntimeError("ops.db 结构不完整：" + "；".join(db_errors))

    df, manifest = latest_snapshot(st.snapshot_dir)
    return AppDeps(
        sem=sem,
        df=df,
        governance=governance,
        db_path=st.ops_db_path,
        manifest=manifest,
        llm_factory=lambda: FakeLLM(script=[]),
    )


def create_app(deps: AppDeps | None = None, settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st = settings or load_settings()
        app.state.settings = st
        app.state.deps = deps or _load_deps(st)
        d = app.state.deps
        # 图只建一次（interrupt 续跑要求同一 checkpointer 实例），事实走共享代理
        obs = Observer()
        facts = SharedFactStore()
        spec = spec_from_sem(d.sem)
        app.state.graph_ask = build_qa_graph(d.sem, d.df, facts, d.llm_factory(), obs, spec)
        app.state.graph_explore = build_qa_graph(
            SlowOnlySemantic(d.sem), d.df, facts, d.llm_factory(), obs, spec
        )
        yield

    app = FastAPI(
        title="风控问数系统",
        version="1.0.0",
        description="语义层驱动的风控指标问数引擎 · REST API v1",
        lifespan=lifespan,
    )
    install_error_handler(app)

    @app.middleware("http")
    async def add_ai_headers(request, call_next):
        """P-16：所有出口（含错误响应）带 AI 标识与数据版本"""
        response = await call_next(request)
        app_deps = getattr(request.app.state, "deps", None)
        manifest = getattr(app_deps, "manifest", None)
        response.headers["X-AI-Disclosure"] = "true"
        response.headers["X-Data-As-Of"] = (
            manifest.data_as_of if manifest is not None else "unavailable"
        )
        return response

    app.include_router(ops.router, prefix="/api/v1")
    app.include_router(ask.router, prefix="/api/v1")
    app.include_router(evidence.router, prefix="/api/v1")
    app.include_router(review.router, prefix="/api/v1")
    app.include_router(governance.router, prefix="/api/v1")
    return app


app = create_app()
