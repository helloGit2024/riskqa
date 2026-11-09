"""pytest 公共夹具：路径注入、演示数据、配置、FakeLLM 与临时存储。

数据基线全部固定（seed 与日期），测试不依赖 datetime.now()：
- TODAY = 2026-10-30（治理配置临时调整生效日）
- AS_OF = 2026-09-30（指标数据截止日）
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from riskqa.facts.store import FactStore  # noqa: E402
from riskqa.governance.clustering import QueryLog  # noqa: E402
from riskqa.governance.config import load_governance  # noqa: E402
from riskqa.llm.fake import FakeLLM  # noqa: E402
from riskqa.orchestration.observer import Observer  # noqa: E402
from riskqa.semantic.layer import SemanticLayer  # noqa: E402

TODAY = "2026-10-30"
AS_OF = "2026-09-30"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def semantic() -> SemanticLayer:
    return SemanticLayer((REPO_ROOT / "config" / "semantic_view.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def governance_text() -> str:
    return (REPO_ROOT / "config" / "governance.yaml").read_text(encoding="utf-8")


@pytest.fixture
def governance_cfg(governance_text: str):
    return load_governance(governance_text, TODAY)


@pytest.fixture(scope="session")
def demo_df() -> pd.DataFrame:
    """申请样本：1200 行，固定 seed。

    来源：legacy/问数Agent_企业版V2.py L1069—L1091（build_demo_data），原文复制；
    基线 2026-11-04，pandas 2.2.3。
    """
    rng = np.random.default_rng(42)
    n = 1200
    channels = rng.choice(["A", "B", "C"], n, p=[0.5, 0.3, 0.2])
    products = rng.choice(["P1", "P2"], n, p=[0.6, 0.4])
    vintage = rng.choice(["2026-07", "2026-08"], n)
    is_pass = (rng.random(n) < 0.62).astype(int)
    score_v3 = np.clip(rng.normal(0.60, 0.15, n), 0.01, 0.99)
    score_v2 = np.clip(rng.normal(0.55, 0.18, n), 0.01, 0.99)
    y = (rng.random(n) < (0.38 - 0.32 * score_v3)).astype(int)
    bad_p = np.where(channels == "B", 0.45, 0.25)
    is_fpd30 = np.where(is_pass == 1, (rng.random(n) < bad_p).astype(int), 0)
    return pd.DataFrame(
        {
            "apply_id": [f"AP{i:05d}" for i in range(n)],
            "customer_id": [f"C{i:05d}" for i in range(n)],
            "channel": channels,
            "product": products,
            "vintage": vintage,
            "is_pass": is_pass,
            "is_fpd30": is_fpd30,
            "score": score_v3.round(4),
            "score_v3": score_v3.round(4),
            "score_v2": score_v2.round(4),
            "y": y,
        }
    )


def _gen_logs(n: int = 200) -> list[QueryLog]:
    """构造 6 类查询日志，固定 seed。

    来源：legacy/问数Agent_持续运营V3.py L539—L600（gen_logs），原文复制；
    实际产出 199 条（n=200 时全部返回）。基线 2026-11-04，pandas 2.2.3。
    """
    rng = random.Random(42)  # noqa: S311  # 测试数据固定 seed，非安全随机
    users = [f"u{i:02d}" for i in range(1, 11)]
    logs: list[QueryLog] = []
    qn = 0

    def add(q, sql, user, day, edited=False, conf=("u00",)):
        nonlocal qn
        qn += 1
        logs.append(
            QueryLog(f"Q{qn:04d}", q, sql, edited, {"value": 0.2}, user, "风险策略部", day, conf)
        )

    c1_questions = [
        "各渠道 FPD30 怎么样",
        "按渠道看首期逾期",
        "渠道维度逾期率",
        "各渠道 FPD30",
        "按渠道看首期逾期情况",
    ]
    for i in range(47):
        add(
            c1_questions[i % len(c1_questions)],
            "SELECT channel, AVG(is_fpd30) AS v FROM fact_application "
            "WHERE is_pass=1 GROUP BY channel LIMIT 10",
            users[i % 8],
            f"2026-10-{(i % 23) + 1:02d}",
            edited=(i % 11 == 0),
            conf=(users[(i + 1) % 8],),
        )
    for i in range(16):
        add(
            ["渠道逾期率看一下", "分渠道首期逾期"][i % 2],
            "SELECT channel, AVG(is_fpd30) AS v FROM fact_application GROUP BY channel LIMIT 10",
            users[8 + (i % 2)],
            f"2026-10-{(i % 20) + 3:02d}",
            conf=("u09",),
        )
    for i in range(30):
        add(
            "按产品看逾期",
            "SELECT product, AVG(is_fpd30) AS v FROM fact_application "
            "WHERE is_pass=1 GROUP BY product LIMIT 10",
            "u03" if i < 25 else users[(i + 3) % 8],
            f"2026-10-{(i % 28) + 1:02d}",
        )
    for i in range(12):
        add(
            "各渠道通过率",
            "SELECT channel, AVG(is_pass) AS v FROM fact_application GROUP BY channel LIMIT 10",
            users[i % 6],
            f"2026-10-{5 + (i % 2):02d}",
        )
    for i in range(2):
        add(
            "vintage 维度通过率",
            "SELECT vintage, AVG(is_pass) AS v FROM fact_application GROUP BY vintage LIMIT 10",
            users[i * 3],
            f"2026-10-{i * 9 + 1:02d}",
        )
    c6_products = ["A", "B", "C"]
    for i in range(92):
        p = c6_products[i % 3]
        tw = ["最近一个月", "最近一年"][i % 2]
        add(
            f"{p}产品放款量{tw}",
            f"SELECT product, SUM(loan_amt) AS v FROM fact_application "  # noqa: S608  # 测试夹具固定 SQL
            f"WHERE product='{p}' GROUP BY product LIMIT 10",
            users[(i + 2) % 9],
            f"2026-10-{(i % 25) + 1:02d}",
        )
    rng.shuffle(logs)
    return logs[:n] if n < len(logs) else logs


@pytest.fixture(scope="session")
def query_logs() -> list[QueryLog]:
    return _gen_logs(200)


@pytest.fixture
def fake_llm():
    """FakeLLM 脚本工厂：失败场景一律脚本化，不接真模型（P-17）。"""

    def _make(script: list[dict]) -> FakeLLM:
        return FakeLLM(script=script)

    return _make


@pytest.fixture
def facts() -> FactStore:
    return FactStore(data_as_of=AS_OF)


@pytest.fixture
def observer() -> Observer:
    return Observer()


@pytest.fixture
def spec(semantic: SemanticLayer) -> dict:
    return {"metrics": [{"name": m, "calc": m} for m in semantic.metric_enum]}


@pytest.fixture
def db_conn(tmp_path):
    from riskqa.store.db import connect
    from riskqa.store.schema import init_db

    conn = connect(tmp_path / "ops.db")
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def snapshot_root(tmp_path) -> Path:
    root = tmp_path / "snapshots"
    root.mkdir()
    return root


# ---------- API v1（T-4.1.5）新增夹具：只新增，不改动上面任何既有夹具 ----------


@pytest.fixture
def api_settings():
    from riskqa.api.settings import Settings, TokenIdentity

    return Settings(
        tokens={
            "tok-analyst": TokenIdentity(user="u01", dept="风险策略部", role="analyst"),
            "tok-owner": TokenIdentity(user="u02", dept="风险策略部", role="owner"),
            "tok-admin": TokenIdentity(user="u03", dept="风控中台", role="admin"),
        },
        data_as_of=AS_OF,
    )


@pytest.fixture
def api_manifest(demo_df):
    from riskqa.data.snapshot import Manifest

    return Manifest(
        source="memory",
        locator="memory",
        data_as_of=AS_OF,
        rows=len(demo_df),
        data_hash="testdatahash",
        file_hash="testfilehash",
    )


@pytest.fixture
def api_db_path(tmp_path) -> Path:
    """API 测试库：只给路径，连接由请求级 open_db 开（SQLite 不能跨线程复用）。"""
    from riskqa.store.db import connect
    from riskqa.store.schema import init_db

    path = tmp_path / "api_ops.db"
    conn = connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def api_deps(api_settings, semantic, demo_df, governance_cfg, api_db_path, api_manifest):
    from riskqa.api.deps import AppDeps

    return AppDeps(
        sem=semantic,
        df=demo_df,
        governance=governance_cfg,
        db_path=api_db_path,
        manifest=api_manifest,
        llm_factory=lambda: FakeLLM(script=[]),
    )


@pytest.fixture
def api_client(api_deps, api_settings):
    from fastapi.testclient import TestClient

    from riskqa.api.app import create_app

    with TestClient(create_app(deps=api_deps, settings=api_settings)) as client:
        yield client


@pytest.fixture
def api_client_factory(api_settings, semantic, demo_df, governance_cfg, api_db_path, api_manifest):
    """按脚本造 TestClient（T-4.1.5 第二笔）：脚本在建图时快照，每张图各持一份副本。

    用 `with api_client_factory(script) as client:` 触发 lifespan（建图 + checkpointer）。
    """
    from fastapi.testclient import TestClient

    from riskqa.api.app import create_app
    from riskqa.api.deps import AppDeps

    def _make(script: list[dict] | None = None) -> TestClient:
        deps = AppDeps(
            sem=semantic,
            df=demo_df,
            governance=governance_cfg,
            db_path=api_db_path,
            manifest=api_manifest,
            llm_factory=lambda: FakeLLM(script=list(script or [])),
        )
        return TestClient(create_app(deps=deps, settings=api_settings))

    return _make
