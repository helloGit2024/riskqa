# -*- coding: utf-8 -*-
"""语义层：YAML 外置 + 指标卡 + 签字闸（口径唯一来源）。"""

from __future__ import annotations

from pathlib import Path

import yaml


class UnregisteredMetricError(Exception):
    """模型或不登记的口径——拒绝执行，不猜不填"""


class UnsignedMetricError(Exception):
    """指标缺少 Owner 签字——禁止合入正式语义层"""


class SemanticLayer:
    """语义层唯一入口：指标 / 表白名单 / 行级权限都从这里出"""

    def __init__(self, yaml_text: str):
        cfg = yaml.safe_load(yaml_text)
        self.version: str = cfg["version"]
        self.metrics: dict[str, dict] = {m["name"]: m for m in cfg["metrics"]}
        self.tables: dict[str, dict] = {t["name"]: t for t in cfg["tables"]}
        self.row_policies: dict[str, dict] = cfg.get("row_policies", {})

    def match_metric(self, question: str) -> str | None:
        """入口路由的命中判定：指标名 + 别名（业务口语"首期逾期"也要能命中）"""
        q = question.lower()
        for name, m in self.metrics.items():
            candidates = [name] + m.get("aliases", [])
            if any(c.lower() in q for c in candidates):
                return name
        return None

    # ---- 派生：FC enum 的唯一来源（新增指标自动进工具 schema）----
    @property
    def metric_enum(self) -> list[str]:
        return sorted(self.metrics)

    def alias_index(self) -> dict[str, str]:
        """别名 → 正式指标名。晋升时把问法聚类回填到这里"""
        idx: dict[str, str] = {}
        for name, m in self.metrics.items():
            idx[name.lower()] = name
            for a in m.get("aliases", []):
                idx[a.lower()] = name
        return idx

    def resolve_alias(self, token: str) -> str | None:
        return self.alias_index().get(token.strip().lower())

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            {"version": self.version,
             "metrics": list(self.metrics.values()),
             "tables": list(self.tables.values()),
             "row_policies": self.row_policies},
            allow_unicode=True, sort_keys=False)

    @property
    def dim_enum(self) -> list[str]:
        return sorted({d for m in self.metrics.values() for d in m["dims"]})

    @property
    def table_enum(self) -> list[str]:
        return sorted(self.tables)

    def metric_desc(self, name: str) -> str:
        if name not in self.metrics:
            raise UnregisteredMetricError(f"指标 {name!r} 未登记，已登记：{self.metric_enum}")
        return self.metrics[name]["desc"]

    def row_filter(self, role: str, table: str) -> str | None:
        """行级权限：返回该角色在该表上的注入条件；None = 不限"""
        return self.row_policies.get(role, {}).get(table)


def load_semantic(path: Path) -> SemanticLayer:
    """从磁盘加载 YAML——生产形态：Git 管理 + MR 评审 + 签字闸"""
    return SemanticLayer(path.read_text(encoding="utf-8"))
