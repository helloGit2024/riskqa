"""契约自检（api-contract §七）：openapi.yaml 的结构性断言。

只做文档级校验，不启动服务；后续每一笔会在此文件追加断言。
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI = REPO_ROOT / "docs" / "openapi.yaml"

EXPECTED_PATHS = {
    "/api/v1/ask",
    "/api/v1/explore",
    "/api/v1/facts/{fid}",
    "/api/v1/evidence/{qid}",
    "/api/v1/reviews",
    "/api/v1/reviews/{rid}/decision",
    "/api/v1/governance/candidates",
    "/api/v1/health",
}


def _doc() -> dict:
    return yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))


def test_exactly_eight_paths():
    assert set(_doc()["paths"]) == EXPECTED_PATHS


def test_every_path_has_operation_and_responses():
    for path, item in _doc()["paths"].items():
        ops = [k for k in item if k in ("get", "post", "put", "delete")]
        assert ops, f"{path} 没有 HTTP 方法"
        for op in ops:
            assert item[op].get("responses"), f"{path} {op} 没有 responses"


def test_no_placeholder_marker():
    assert "⚙️" not in OPENAPI.read_text(encoding="utf-8")


def test_all_local_refs_resolve():
    doc = _doc()

    def walk(node, where: str) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                assert ref.startswith("#/"), f"{where} 出现外部引用：{ref}"
                target = doc
                for part in ref[2:].split("/"):
                    assert part in target, f"{where} 的 $ref 悬空：{ref}"
                    target = target[part]
            for key, value in node.items():
                walk(value, f"{where}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{where}[{i}]")

    walk(doc, "$")


def test_health_is_public_and_token_scheme_exists():
    doc = _doc()
    assert doc["components"]["securitySchemes"]["RiskQAToken"]["in"] == "header"
    assert doc["paths"]["/api/v1/health"]["get"]["security"] == []
    assert doc["security"] == [{"RiskQAToken": []}]
