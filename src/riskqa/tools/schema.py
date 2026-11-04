# -*- coding: utf-8 -*-
"""工具层：FC 工具定义（enum 从语义层自动生成，P-08）。"""

from __future__ import annotations

from ..semantic.layer import SemanticLayer


def build_tools(sem: SemanticLayer) -> list[dict]:
    """V2：FC schema 的 enum 全部来自语义层——新增指标不改工具代码"""
    return [
        {"name": "query_metric",
         "description": "计算已登记指标。只返回数值与 fact_id，不返回解释、不返回结论。",
         "input_schema": {"type": "object", "properties": {
             "metric": {"type": "string", "enum": sem.metric_enum},   # 收窄：不能发明指标
             "group_by": {"type": "string", "enum": sem.dim_enum}},
             "required": ["metric"]}},
        {"name": "list_tables",
         "description": "列出慢路可用表白名单（来自语义层）。",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "get_schema",
         "description": "获取白名单内表的列结构。",
         "input_schema": {"type": "object", "properties": {
             "table": {"type": "string", "enum": sem.table_enum}},
             "required": ["table"]}},
        {"name": "run_sql",
         "description": "执行 SQL（慢路专用）。必须已通过静态检查与人审分级。",
         "input_schema": {"type": "object", "properties": {
             "sql": {"type": "string"}, "purpose": {"type": "string"}},
             "required": ["sql"]}},
    ]
