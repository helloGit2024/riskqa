# -*- coding: utf-8 -*-
"""工具层：SQL 三闸（只读 / LIMIT / 注入检测）+ 行级权限注入 + 调用闸。"""

from __future__ import annotations

import re
from dataclasses import dataclass

DML_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b", re.I)


@dataclass(frozen=True)
class SQLVerdict:
    ok: bool
    violations: tuple[str, ...]


def check_sql(sql: str, require_limit: bool = True,
              max_tables: int = 3) -> SQLVerdict:
    """慢路 SQL 静态检查——规则失败必须硬阻断，不是"提醒重试"

    生产建议接 SQL AST（sqlglot），这里用正则演示规则集：
    DML 拦截 / select * / 无 limit / 笛卡尔积 / 大表全关联
    """
    v: list[str] = []
    if DML_PATTERN.search(sql):
        v.append(f"DML/DDL 语句拦截：{DML_PATTERN.search(sql).group(0)}")
    if re.search(r"SELECT\s+\*", sql, re.I):
        v.append("禁止 SELECT *（大宽表会打爆内存，且暴露无关字段）")
    if require_limit and not re.search(r"\bLIMIT\s+\d+", sql, re.I):
        v.append("缺少 LIMIT——全表结果集禁止直接返回")
    # 笛卡尔积启发：FROM a, b 形式且无 JOIN ON 也无 WHERE 关联
    m = re.search(r"FROM\s+(\w+)\s*,\s*(\w+)", sql, re.I)
    if m and not re.search(r"\bWHERE\b", sql, re.I):
        v.append(f"疑似笛卡尔积：FROM {m.group(1)}, {m.group(2)} 无 WHERE 关联")
    n_tables = len(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.I))
    if n_tables > max_tables and not re.search(r"\bWHERE\b", sql, re.I):
        v.append(f"大表全关联：{n_tables} 张表无 WHERE 过滤")
    return SQLVerdict(ok=not v, violations=tuple(v))


def inject_row_filter(sql: str, table: str, condition: str) -> str:
    """行级权限注入：在 WHERE 不存在时插入，存在时 AND 拼接

    生产必须用 SQL AST 改写（防注释/子查询绕过），demo 用正则。
    """
    if not condition:
        return sql
    if re.search(r"\bWHERE\b", sql, re.I):
        return re.sub(r"\bWHERE\b", f"WHERE ({condition}) AND", sql, count=1, flags=re.I)
    m = re.search(r"\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql, re.I)
    if m:
        i = m.start()
        return f"{sql[:i]}WHERE {condition} {sql[i:]}"
    return f"{sql} WHERE {condition}"


@dataclass
class Gate:
    ok: bool
    reason: str = ""
