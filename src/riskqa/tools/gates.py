"""工具层：SQL 三闸（只读 / LIMIT / 注入检测）+ 行级权限注入 + 调用闸。"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

DML_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b", re.IGNORECASE
)

# 闸①：只允许 SELECT / WITH 开头；其余只读但非查询的语句也拒
NON_SELECT_PATTERN = re.compile(r"\b(PRAGMA|ATTACH|DETACH|VACUUM|EXPLAIN|REPLACE)\b", re.IGNORECASE)
SELECT_OR_WITH = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

# 闸③：注入特征（security §三）；UNION 一律拒（SG-01 #4）
INJECTION_PATTERNS = (
    (re.compile(r"\bUNION\b", re.IGNORECASE), "UNION"),
    (re.compile(r";"), "分号（多语句）"),
    (re.compile(r"--"), "行注释"),
    (re.compile(r"/\*"), "块注释"),
    (re.compile(r"\bxp_\w+", re.IGNORECASE), "xp_ 扩展过程"),
    (re.compile(r"\bINTO\s+OUTFILE\b", re.IGNORECASE), "INTO OUTFILE"),
    (re.compile(r"\bLOAD_FILE\b", re.IGNORECASE), "LOAD_FILE"),
)


class RowFilterParseError(Exception):
    """行权限条件不在快路支持的受限语法内——必须显式失败，禁止静默跳过（R14）"""


# 快路 df 过滤只支持等值/IN + AND，与 config 里的 row_policies 写法对齐
_ROW_FILTER_EQ = re.compile(r"^\s*(\w+)\s*=\s*(?:'([^']*)'|(-?\d+(?:\.\d+)?))\s*$")
_ROW_FILTER_IN = re.compile(r"^\s*(\w+)\s+IN\s*\(([^)]*)\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class SQLVerdict:
    ok: bool
    violations: tuple[str, ...]


def check_sql(sql: str, require_limit: bool = True, max_tables: int = 3) -> SQLVerdict:
    """慢路 SQL 静态检查——规则失败必须硬阻断，不是"提醒重试"

    生产建议接 SQL AST（sqlglot），这里用正则演示规则集：
    SELECT 白名单 / DML 拦截 / select * / 无 limit / 笛卡尔积 / 大表全关联 / 注入特征
    """
    v: list[str] = []
    if DML_PATTERN.search(sql):
        v.append(f"DML/DDL 语句拦截：{DML_PATTERN.search(sql).group(0)}")
    if not SELECT_OR_WITH.match(sql):
        v.append("只允许 SELECT / WITH 查询语句")
    if NON_SELECT_PATTERN.search(sql):
        v.append(f"非查询语句拦截：{NON_SELECT_PATTERN.search(sql).group(0)}")
    for pattern, name in INJECTION_PATTERNS:
        if pattern.search(sql):
            v.append(f"注入特征拦截：{name}")
    if re.search(r"SELECT\s+\*", sql, re.IGNORECASE):
        v.append("禁止 SELECT *（大宽表会打爆内存，且暴露无关字段）")
    if require_limit and not re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
        v.append("缺少 LIMIT——全表结果集禁止直接返回")
    # 笛卡尔积启发：FROM a, b 形式且无 JOIN ON 也无 WHERE 关联
    m = re.search(r"FROM\s+(\w+)\s*,\s*(\w+)", sql, re.IGNORECASE)
    if m and not re.search(r"\bWHERE\b", sql, re.IGNORECASE):
        v.append(f"疑似笛卡尔积：FROM {m.group(1)}, {m.group(2)} 无 WHERE 关联")
    n_tables = len(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE))
    if n_tables > max_tables and not re.search(r"\bWHERE\b", sql, re.IGNORECASE):
        v.append(f"大表全关联：{n_tables} 张表无 WHERE 过滤")
    return SQLVerdict(ok=not v, violations=tuple(v))


def inject_row_filter(sql: str, table: str, condition: str) -> str:
    """行级权限注入：在 WHERE 不存在时插入，存在时 AND 拼接

    生产必须用 SQL AST 改写（防注释/子查询绕过），demo 用正则。
    """
    if not condition:
        return sql
    if re.search(r"\bWHERE\b", sql, re.IGNORECASE):
        return re.sub(r"\bWHERE\b", f"WHERE ({condition}) AND", sql, count=1, flags=re.IGNORECASE)
    m = re.search(r"\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b", sql, re.IGNORECASE)
    if m:
        i = m.start()
        return f"{sql[:i]}WHERE {condition} {sql[i:]}"
    return f"{sql} WHERE {condition}"


def _parse_scalar(raw: str) -> str | int | float:
    token = raw.strip()
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1]
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)
    raise RowFilterParseError(f"行权限条件取值不支持：{raw!r}")


def apply_row_filter(df: pd.DataFrame, condition: str) -> pd.DataFrame:
    """快路行级权限：在计算前对 df 收窄（等价 WHERE，禁止聚合后再过滤）

    只支持 `col = 字面量` / `col IN (...)` 与 AND 组合；其他语法显式拒绝，
    不静默放过（R14）。生产同样应改为 AST 改写。
    """
    if not condition:
        return df
    work = df
    for clause in re.split(r"\s+AND\s+", condition, flags=re.IGNORECASE):
        eq = _ROW_FILTER_EQ.match(clause)
        if eq:
            col, quoted, numeric = eq.groups()
            if col not in work.columns:
                raise RowFilterParseError(f"行权限字段 {col!r} 不在数据列中")
            value = quoted if quoted is not None else _parse_scalar(numeric)
            work = work[work[col] == value]
            continue
        in_match = _ROW_FILTER_IN.match(clause)
        if in_match:
            col, raw_values = in_match.groups()
            if col not in work.columns:
                raise RowFilterParseError(f"行权限字段 {col!r} 不在数据列中")
            values = [_parse_scalar(v) for v in raw_values.split(",") if v.strip()]
            work = work[work[col].isin(values)]
            continue
        raise RowFilterParseError(f"行权限条件不在受限语法内：{clause.strip()!r}")
    return work


@dataclass
class Gate:
    ok: bool
    reason: str = ""
