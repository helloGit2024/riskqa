"""同义词/别名归一：口语问法 → 标准指标名（索引只从语义层派生，P-08）。

术语约定：任务书称 synonyms，YAML 字段为 aliases（唯一事实源，不新增 YAML 字段）。
未命中一律返回 None，交由慢路提名，不猜不填（P-04）。
"""

from __future__ import annotations


def build_alias_index(metrics: dict[str, dict]) -> dict[str, str]:
    """别名 → 正式指标名。晋升时把问法聚类回填到这里"""
    idx: dict[str, str] = {}
    for name, m in metrics.items():
        idx[name.lower()] = name
        for a in m.get("aliases", []):
            idx[a.lower()] = name
    return idx


def resolve_token(index: dict[str, str], token: str) -> str | None:
    """整词归一：strip + lower 后查索引；未命中返回 None（进慢路提名）"""
    return index.get(token.strip().lower())


def match_question(metrics: dict[str, dict], question: str) -> str | None:
    """入口路由的命中判定：指标名 + 别名（业务口语"首期逾期"也要能命中）"""
    q = question.lower()
    for name, m in metrics.items():
        candidates = [name, *m.get("aliases", [])]
        if any(c.lower() in q for c in candidates):
            return name
    return None
