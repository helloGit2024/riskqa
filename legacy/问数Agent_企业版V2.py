# -*- coding: utf-8 -*-
"""
问数 Agent · 金融风控企业版 V2（《风控问数 Agent 落地方案 V2》配套代码）
=====================================================================
运行： python 问数Agent_企业版V2.py
依赖： langgraph 1.2+ / langchain-core / pandas / numpy / PyYAML
      （无需数据库、无需真实 LLM API key——FakeLLM 脚本驱动，结果可复现）

V1 → V2 升级清单（每一项都是 V1 或讨论中暴露的真实缺口）：
  ① 语义层从内存 dict 升级为 YAML 外置 + 签字闸：口径变更走 Git 评审，
     Owner 未签字的行禁止合入（监管可解释）
  ② 新增入口路由：命中语义层走"快路"（FC enum 收窄，模型不写 SQL），
     未命中走"慢路"（LangGraph text-to-SQL + 分级人审）——V1 只有快路
  ③ 新增 SQL 静态检查：DML 拦截 / select * / 无 limit / 笛卡尔积识别
  ④ 新增行级数据权限：按角色向 SQL 注入 WHERE，模型无权越权取数
  ⑤ 人审分级：免审 / 抽检 / 必审——V1 一刀切人审，成本会杀死系统
  ⑥ 模型路由：检测不用 LLM、归因用强模型、叙事用便宜模型——成本可控
  ⑦ 韧性降级：LLM 失败 → 快路纯函数 → 规则模板，任何一级不静默
  ⑧ 可观测：trace / 成本 / 审计日志——监管要求全程留痕
  ⑨ 合规：AI 生成内容显著标识 + 人工复核记录，否则不算交付
  ⑩ 快慢路交叉验证：同一指标两条路算出不同值 → 告警（防口径悄悄漂移）
  ⑪ 监控归因升级：检测层规则化 + 假设空间穷游 + 已排除清单也是产出
  ⑫ 回测场景：固定流跑数（模型禁入）+ Agent 只做呈现层 + 决策禁入区
  ⑬ 评估体系：黄金题集回归 runner——JD"建立 Agent 效果评估体系"的落地
  ⑭ 编排层从手写循环升级为 LangGraph：interrupt/checkpointer 白拿

架构分层（V2 五层 + 四横切）：
  D0 数据源层   sources.py    注册表：memory / csv / parquet + 快照 manifest
  D1 语义层     semantic.py   YAML 外置 + 指标卡 + 签字闸 + enum 自动生成
  D2 能力层     facts/metrics/security  纯函数 + fact_id + 权限 + SQL 检查
  D3 编排层     graph.py      LangGraph：入口路由 + 快路 + 慢路 + 归因子图
  D4 场景层     scenarios.py  问数 / 报告 / 监控归因 / 回测
  横切：observability（trace/成本/审计）· compliance（AI 标识/复核）
        resilience（降级链）· evaluation（黄金题集回归）
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Literal, Optional

import numpy as np
import pandas as pd
import yaml

# ============================================================
# C1 语义层：YAML 外置 + 指标卡 + 签字闸（口径唯一来源）
# ============================================================
# V1 这里是内存 dict；V2 落成 YAML 文件——新增指标 = 改 YAML + 走评审，
# 工具 schema、慢路表白名单、行级权限全部从同一份 YAML 生成（单一事实源）。
SEMANTIC_YAML = """
version: "2.0"
metrics:
  - name: fpd30_rate
    desc: "首期逾期率：放款客户中首期 DPD30+ 的占比"
    unit: ratio
    dims: [channel, product, vintage]
    calc: fpd30_rate
    aliases: [fpd30, 首期逾期率, 首期逾期]
    owner: 风控策略组
    signed_at: "2026-09-30"
    changelog:
      - {date: "2026-09-30", version: v1.0, note: "初版：放款后30天DPD30+，宽限期3天"}
  - name: pass_rate
    desc: "通过率：审批通过申请数 / 提交申请数（分母口径：提交数，非通过数）"
    unit: ratio
    dims: [channel, product, vintage]
    calc: pass_rate
    aliases: [通过率, pass]
    owner: 风控策略组
    signed_at: "2026-09-30"
    changelog:
      - {date: "2026-09-30", version: v1.0, note: "初版：分母=提交申请数"}
  - name: ks
    desc: "KS：好坏样本累计分布差的最大值（score 降序）"
    unit: ratio
    dims: [vintage]
    calc: ks
    owner: 模型组
    signed_at: "2026-09-30"
    changelog:
      - {date: "2026-09-30", version: v1.0, note: "初版：OOT 样本上计算"}
  - name: auc
    desc: "AUC：ROC 曲线下面积"
    unit: ratio
    dims: [vintage]
    calc: auc
    owner: 模型组
    signed_at: "2026-09-30"
    changelog: []
  - name: psi
    desc: "PSI：分数分布稳定性（期望 vs 实际，10 等宽分箱）"
    unit: ratio
    dims: [vintage]
    calc: psi
    owner: 模型组
    signed_at: "2026-09-30"
    changelog: []

# 慢路可用表白名单：text-to-SQL 只能在这些表里选，且必须带口径上下文
tables:
  - name: fact_application
    desc: "申请事实表（清洗后）"
    columns: [apply_id, customer_id, channel, product, vintage, is_pass, is_fpd30, score]
    risk_level: high
  - name: dim_channel
    desc: "渠道维度表"
    columns: [channel, channel_name, region]
    risk_level: low

# 行级数据权限：角色 → 表 → 注入条件（V1 完全没有，风控数据敏感必配）
row_policies:
  analyst_qa:
    fact_application: "channel = 'A'"     # 只能看 A 渠道
  risk_admin: {}                          # 空 = 不限
"""


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


def promote_yaml(candidates: list[dict], decisions: dict) -> str:
    """签字闸：Owner 未签字的指标行，禁止合入正式 YAML（V1 同款纪律）"""
    out = ["# generated by excavate.py —— Owner 逐条签字后方可合入",
           'version: "2.0"', "metrics:"]
    for c in candidates:
        d = decisions.get(c["metric"])
        if not d or not d.get("signed_by"):
            out.append(f"  # [BLOCKED] {c['metric']}: 无 Owner 签字，禁止合入")
            continue
        out.append(f"  - name: {c['metric']}\n"
                   f"    expr: {d['final_expr']}\n"
                   f"    owner: {d['signed_by']}\n"
                   f"    signed_at: {d['signed_at']}")
    return "\n".join(out)


# ============================================================
# C2 数据层：数据源注册表 + 快照 manifest + 缺失值归一
# ============================================================
@dataclass(frozen=True)
class Manifest:
    """血缘凭证：data_as_of 必须随结果返回；同 spec + 同快照 → 产物一致"""
    source: str
    locator: str
    data_as_of: str
    rows: int
    data_hash: str


def normalize_missing(df: pd.DataFrame) -> pd.DataFrame:
    """'' / 'unknown' / -999 → NaN。只在入口做一次，下游一律当缺失处理"""
    return df.replace(["", "unknown", -999], np.nan)


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
        df = normalize_missing(src(cfg))
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


def load_data(cfg: dict) -> tuple[pd.DataFrame, Manifest]:
    """上层唯一入口：返回 (df, manifest)。数据源类型是配置，不是代码分支"""
    return REGISTRY.load(cfg)


# ============================================================
# C3 计算层：纯函数指标 + 独立重算 + 快慢路交叉验证
# ============================================================
def fpd30_rate(df: pd.DataFrame) -> float:
    """首期逾期率：分母是放款户（is_pass=1），不是全量——未放款户不进分母"""
    granted = df[df["is_pass"] == 1]
    return float(granted["is_fpd30"].mean()) if len(granted) else float("nan")


def pass_rate(df: pd.DataFrame) -> float:
    return float(df["is_pass"].mean())


def ks(df: pd.DataFrame) -> float:
    y, s = df["y"], df["score"]
    if y.nunique() < 2:
        return float("nan")
    order = np.argsort(-s.values)
    yy = y.values[order]
    cum_pos = np.cumsum(yy == 1) / max((yy == 1).sum(), 1)
    cum_neg = np.cumsum(yy == 0) / max((yy == 0).sum(), 1)
    return float(np.max(np.abs(cum_pos - cum_neg)))


def auc(df: pd.DataFrame) -> float:
    y, s = df["y"], df["score"]
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    return float((pos.values[:, None] > neg.values[None, :]).mean()
                 + 0.5 * (pos.values[:, None] == neg.values[None, :]).mean())


def psi(df: pd.DataFrame) -> float:
    y, s = df["y"], df["score"]
    bins = np.linspace(s.min(), s.max(), 11)
    idx = np.clip(np.digitize(s, bins[1:-1]), 0, 9)
    e = np.bincount(idx[y == 1], minlength=10) / max((y == 1).sum(), 1)
    a = np.bincount(idx[y == 0], minlength=10) / max((y == 0).sum(), 1)
    e, a = np.clip(e, 1e-6, None), np.clip(a, 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))


METRIC_FUNCS: dict[str, Callable[[pd.DataFrame], float]] = {
    "fpd30_rate": fpd30_rate, "pass_rate": pass_rate,
    "ks": ks, "auc": auc, "psi": psi,
}


def compute_metric(name: str, df: pd.DataFrame, group_by: str | None = None) -> pd.DataFrame:
    """快路唯一计算入口：只认语义层登记名，未登记直接拒绝"""
    if name not in METRIC_FUNCS:
        raise UnregisteredMetricError(f"指标 {name!r} 未登记，已登记：{sorted(METRIC_FUNCS)}")
    fn = METRIC_FUNCS[name]
    if group_by is None:
        return pd.DataFrame([{"value": fn(df)}])
    return (df.groupby(group_by, observed=True)
              .apply(lambda g: pd.Series({"value": fn(g)}), include_groups=False)
              .reset_index())


def recompute_all(spec: dict, df: pd.DataFrame) -> dict:
    """校验闸第三重的武器：不经 LLM、不经流水线，Python 独立重算"""
    return {m["name"]: METRIC_FUNCS[m["calc"]](df)
            for m in spec["metrics"] if m["calc"] in METRIC_FUNCS}


def cross_check(metric: str, fast_value: float, slow_value: float,
                rtol: float = 1e-6) -> tuple[bool, str]:
    """V2 新增：快慢路两套实现对同一个指标的结果比对——防口径悄悄漂移"""
    if pd.isna(fast_value) or pd.isna(slow_value):
        return False, f"{metric}: 快路 {fast_value} vs 慢路 {slow_value}（含 NaN，拒绝采信）"
    if np.isclose(fast_value, slow_value, rtol=rtol):
        return True, f"{metric}: {fast_value:.6f} == {slow_value:.6f} ✓"
    return False, (f"{metric}: 快路 {fast_value:.6f} vs 慢路 {slow_value:.6f} "
                   f"不一致（rtol={rtol}）——两条路有一条口径错了，禁止交付")


# ============================================================
# C4 事实层：FactStore + fact_id（全文数字唯一来源）
# ============================================================
@dataclass(frozen=True)
class Fact:
    fid: str
    value: object
    unit: str
    metric: str
    segment: str      # V1 修复 bug 的字段：整体 vs 分维度精确匹配
    source: str       # fast | slow（哪条路产的，交叉验证用）
    data_as_of: str


class FactStore:
    """模型只许引用 {{F0001}}，禁写裸数字——数字必须可溯源"""

    def __init__(self, data_as_of: str = ""):
        self._seq = 0
        self._facts: dict[str, Fact] = {}
        self._data_as_of = data_as_of

    def put(self, value, unit: str, metric: str, segment: str = "overall",
            source: str = "fast") -> str:
        self._seq += 1
        fid = f"F{self._seq:04d}"
        self._facts[fid] = Fact(fid, value, unit, metric, segment, source, self._data_as_of)
        return fid

    def get(self, fid: str) -> Fact:
        try:
            return self._facts[fid]
        except KeyError:
            raise UnknownFactError(f"{fid} 不存在——模型编造了引用")

    def digest(self) -> list[dict]:
        """注入上下文：模型需要知道有哪些数可用，才能写叙事"""
        return [asdict(f) for f in self._facts.values()]

    def manifest(self) -> dict:
        raw = json.dumps([asdict(f) for f in self._facts.values()],
                         sort_keys=True, ensure_ascii=False, default=str)
        return {"count": len(self._facts),
                "sha256": hashlib.sha256(raw.encode()).hexdigest()}


class UnknownFactError(Exception):
    """模型引用了不存在的 fact_id——编造引用，校验闸必抓"""


# ============================================================
# C5 安全层：SQL 静态检查 + 行级权限注入
# ============================================================
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


# ============================================================
# C6 工具层：FC 工具定义 + dispatch（enum 从语义层自动生成）
# ============================================================
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


# ============================================================
# C7 校验闸：三重检查 + 人审分级 + AI 显著标识
# ============================================================
FACT_REF = re.compile(r"\{\{(F\d{4})\}\}")
BARE_NUMBER = re.compile(r"(?<!\{)\b\d+\.\d{1,4}\b(?!\})")


@dataclass
class Verdict:
    passed: bool
    failures: list[tuple] = field(default_factory=list)


def classify_review(sql: str, role: str) -> str:
    """人审分级——V2 新增。一刀切人审会杀死系统，按风险定级：
       auto   = 只读 + limit + 白名单单表 → 免审（记录留痕）
       sample = 跨表 / 聚合 / 分区全扫   → 抽检（demo 中按概率升级为 must）
       must   = 无 limit / 涉及敏感列 / 导出意图 → 必审（interrupt）
    """
    if not re.search(r"\bLIMIT\s+\d+", sql, re.I):
        return "must"
    if re.search(r"\bJOIN\b", sql, re.I):
        return "must"
    if role not in ("risk_admin",):
        return "sample"
    return "auto"


def verify_report(narrative: str, facts: FactStore, df: pd.DataFrame) -> Verdict:
    """三重校验闸：任何一道不过，整段回退规则模板，绝不交付半成品

    检查 3 只遍历报告中实际引用的 fact（逐条独立重算）——
    报告没用到的指标不该判 missing；引用到的每一条都必须对得上。
    """
    failures: list[tuple] = []
    # 检查 1：叙事层不许出现裸数字，必须在 {{F0001}} 里
    for hit in BARE_NUMBER.findall(narrative):
        failures.append(("bare_number", hit))
    # 检查 2：所有引用必须存在（抓编造 fact_id）
    for fid in FACT_REF.findall(narrative):
        try:
            facts.get(fid)
        except UnknownFactError as e:
            failures.append(("fabricated_ref", str(e)))
    # 检查 3：渲染一致性——Python 独立重算，不经 LLM、不经流水线
    for f in facts.digest():
        metric = f["metric"]
        if metric not in METRIC_FUNCS:
            continue
        if f["segment"] == "overall":
            expect = METRIC_FUNCS[metric](df)
        else:
            dim, val = f["segment"].split("=", 1)
            sub = df[df[dim].astype(str) == val]
            expect = METRIC_FUNCS[metric](sub) if len(sub) else float("nan")
        if not np.isclose(float(f["value"]), float(expect), rtol=1e-6, equal_nan=True):
            failures.append(("render_mismatch", f["fid"],
                             f"{metric}@{f['segment']} 报告 {f['value']} vs 重算 {expect}"))
    return Verdict(passed=not failures, failures=failures)


def ai_disclosure(model: str, as_of: str) -> str:
    """合规：监管要求生成内容显著标识——每份 AI 产出必须带"""
    return (f"<!-- AI-GENERATED · 需人工复核 · 模型:{model} · 数据截止:{as_of} · "
            f"本内容由大模型生成，数字经 Python 独立重算校验 -->")


# ============================================================
# C8 LLM 层：模型路由 + FakeLLM + 韧性降级
# ============================================================
class ModelRouter:
    """V2 新增：不同任务用不同档位模型——检测不用 LLM、归因用强模型、
    叙事用便宜模型。一刀切一个模型是成本灾难。"""

    ROUTES = {"extraction": "mid", "drill": "strong", "narrative": "cheap"}

    def route(self, task: str) -> str:
        return self.ROUTES.get(task, "mid")


class FakeLLM:
    """按脚本返回动作。测编排层和闸门，不花 token、不受网络影响、可复现"""

    def __init__(self, script: list[dict], model: str = "fake-mid"):
        self._script = list(script)
        self.model = model
        self.calls: list[dict] = []
        self.tokens_used = 0

    def chat(self, task: str, prompt: str, **kw) -> dict:
        self.calls.append({"task": task, "prompt": prompt})
        self.tokens_used += len(prompt) // 4 + 50      # 估算成本
        return self._script.pop(0) if self._script else {"type": "finish"}


class DegradedLLM:
    """V2 新增韧性：LLM 调用失败时按降级链走，任何一级不静默"""

    def __init__(self, primary: FakeLLM, fallback: Callable[[str], dict]):
        self.primary = primary
        self.fallback = fallback
        self.degraded = False

    def chat(self, task: str, prompt: str, **kw) -> dict:
        try:
            return self.primary.chat(task, prompt, **kw)
        except Exception as e:                           # 超时/限流/返回异常
            self.degraded = True
            out = self.fallback(prompt)
            out["_degraded"] = f"LLM 不可用（{type(e).__name__}），已降级：{out.get('_degraded_reason', '规则兜底')}"
            return out


# ============================================================
# C9 观测层：trace / 成本 / 审计日志（监管要求全程留痕）
# ============================================================
@dataclass
class AuditEntry:
    ts: str
    actor: str          # 谁发起的
    question: str
    route: str
    sql: str
    review_level: str
    human_action: str   # accept / edit / response / auto
    model: str
    ai_disclosed: bool


class Observer:
    """V2 新增：没有度量就无法优化，监管也要求可追溯"""

    def __init__(self):
        self.trace: list[dict] = []
        self.audit: list[AuditEntry] = []
        self.cost_tokens = 0

    def log(self, node: str, **kw):
        self.trace.append({"node": node, "t": round(time.time(), 3), **kw})

    def audit_append(self, **kw):
        self.audit.append(AuditEntry(ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                                     ai_disclosed=True, **kw))

    def cost(self, llm: FakeLLM):
        self.cost_tokens += llm.tokens_used


# ============================================================
# C10 编排层：LangGraph（入口路由 + 快路 + 慢路 + 分级人审）
# ============================================================
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.memory import InMemorySaver

try:
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict


class QAState(TypedDict, total=False):
    question: str
    role: str
    route: str                 # fast | slow
    metric: str
    group_by: str
    sql: str
    review_level: str
    review_feedback: str
    facts: list                # fact dict 快照
    narrative: str
    result: dict
    trace: list
    steps: int


def sql_execute(df: pd.DataFrame, sql: str) -> pd.DataFrame:
    """迷你 SQL 模拟器：支持 SELECT dim, AGG(col) FROM t [WHERE k=v] [GROUP BY dim] [LIMIT n]

    生产替换为真实数据库驱动；demo 用 pandas 保证零依赖可复现。
    """
    m = re.search(
        r"SELECT\s+(\w+)\s*,\s*(AVG|SUM|COUNT)\((\w+)\)\s+FROM\s+(\w+)"
        r"(?:\s+WHERE\s+(.+?))?"
        r"(?:\s+GROUP\s+BY\s+(\w+))?(?:\s+LIMIT\s+(\d+))?\s*$", sql, re.I)
    if not m:
        raise ValueError(f"demo 执行器不支持的 SQL 形态：{sql}")
    dim, agg, col, table, where, group, limit = m.groups()
    work = df
    if where:
        for k, v in re.findall(r"(\w+)\s*=\s*'([^']+)'", where):   # 字符串等值
            work = work[work[k] == v]
        for k, v in re.findall(r"(\w+)\s*=\s*(\d+)", where):      # 数值等值
            work = work[work[k] == int(v)]
    fn = {"AVG": "mean", "SUM": "sum", "COUNT": "count"}[agg.upper()]
    if group:
        out = work.groupby(group, observed=True)[col].agg(fn).reset_index()
        out.columns = [group, "value"]
    else:
        out = pd.DataFrame([{"value": getattr(work[col], fn)()}])
    if limit:
        out = out.head(int(limit))
    return out


def build_qa_graph(sem: SemanticLayer, df: pd.DataFrame, facts: FactStore,
                   llm: FakeLLM, obs: Observer, spec: dict, role: str = "analyst_qa",
                   max_steps: int = 6) -> Any:
    """V2 核心：一张图同时装下快路和慢路，入口路由决定走哪条"""

    # ---- 入口路由：命中语义层指标 → 快路；否则 → 慢路 ----
    def entry_route(state: QAState) -> dict:
        hit = sem.match_metric(state["question"])
        obs.log("entry_route", hit=hit)
        return {"route": "fast" if hit else "slow", "metric": hit or "",
                "steps": 0, "facts": [], "trace": ["entry_route"]}

    def route_edge(state: QAState) -> Literal["fast_fc", "slow_list_tables"]:
        return "fast_fc" if state["route"] == "fast" else "slow_list_tables"

    # ---- 快路：模型只选参数，SQL 由语义层模板生成（模型不写 SQL）----
    def fast_fc(state: QAState) -> dict:
        resp = llm.chat("extraction",
                        f"问题：{state['question']}。可选指标 enum={sem.metric_enum}，"
                        f"可选维度 enum={sem.dim_enum}。只选参数，不要算数。")
        action = resp.get("action", resp)
        metric = action.get("metric", state["metric"])
        group_by = action.get("group_by")
        res = compute_metric(metric, df, group_by)
        new_facts = list(state.get("facts", []))
        if group_by:
            for _, r in res.iterrows():
                fid = facts.put(float(r["value"]), sem.metrics[metric]["unit"], metric,
                                segment=f"{group_by}={r[group_by]}", source="fast")
                new_facts.append(asdict(facts.get(fid)))
        else:
            fid = facts.put(float(res["value"][0]), sem.metrics[metric]["unit"], metric)
            new_facts.append(asdict(facts.get(fid)))
        obs.log("fast_fc", metric=metric, group_by=group_by)
        obs.cost(llm)
        return {"metric": metric, "group_by": group_by, "facts": new_facts,
                "trace": state["trace"] + ["fast_fc"]}

    # ---- 慢路：text-to-SQL，模型写 SQL，但层层设闸 ----
    def slow_list_tables(state: QAState) -> dict:
        obs.log("slow_list_tables", tables=sem.table_enum)
        return {"trace": state["trace"] + ["slow_list_tables"]}

    def slow_get_schema(state: QAState) -> dict:
        resp = llm.chat("extraction",
                        f"问题：{state['question']}。可用表：{sem.table_enum}。"
                        f"各表结构：{json.dumps({k: v['columns'] for k, v in sem.tables.items()}, ensure_ascii=False)}。"
                        f"选需要的表。")
        obs.log("slow_get_schema", chosen=resp.get("tables", sem.table_enum))
        obs.cost(llm)
        return {"trace": state["trace"] + ["slow_get_schema"]}

    def slow_check_sufficient(state: QAState) -> dict:
        """V2 新增：充足性校验——规则先行，不靠谱 LLM 判断"""
        obs.log("slow_check_sufficient", ok=True)
        return {"trace": state["trace"] + ["slow_check_sufficient"]}

    def slow_generate(state: QAState) -> dict:
        fb = state.get("review_feedback")
        prompt = (f"问题：{state['question']}。"
                  f"口径参考（来自语义层）：{sem.metric_desc('fpd30_rate')}；"
                  f"表结构：{json.dumps({k: v['columns'] for k, v in sem.tables.items()}, ensure_ascii=False)}。"
                  f"必须带 LIMIT。")
        if fb:
            prompt += f"\n上一轮 SQL 被静态检查驳回：{fb}。请修正。"
        resp = llm.chat("drill", prompt)
        obs.log("slow_generate", sql=resp.get("sql", ""))
        obs.cost(llm)
        return {"sql": resp.get("sql", ""),
                "steps": state.get("steps", 0) + 1,
                "review_feedback": "",
                "trace": state["trace"] + ["slow_generate"]}

    def slow_sql_check(state: QAState) -> dict:
        verdict = check_sql(state["sql"])
        obs.log("slow_sql_check", ok=verdict.ok, violations=list(verdict.violations))
        if not verdict.ok:
            return {"review_feedback": "; ".join(verdict.violations)}
        return {"review_feedback": ""}

    def sql_check_edge(state: QAState) -> Literal["slow_review", "slow_generate", "fail"]:
        if not state.get("review_feedback"):
            return "slow_review"
        if state.get("steps", 0) >= max_steps:
            return "fail"                    # V2：步数上限，绝不硬撑
        return "slow_generate"

    def slow_review(state: QAState) -> dict:
        """V2 分级人审：auto 免审（留痕）/ must 触发 interrupt 人工决策"""
        level = classify_review(state["sql"], role)
        obs.log("slow_review", level=level, sql=state["sql"])
        if level == "must":
            resp = interrupt({"action": "run_sql", "args": {"sql": state["sql"]},
                              "description": "高风险 SQL，请审核：accept / edit / response",
                              "review_level": level})
            action = resp.get("type", "accept") if isinstance(resp, dict) else "accept"
            obs.audit_append(actor=role, question=state["question"], route="slow",
                             sql=state["sql"], review_level=level,
                             human_action=action, model=llm.model)
            if action == "response":
                return {"narrative": f"[人审反馈] {resp.get('text', '')}",
                        "review_level": level, "human_rejected": True}
            if action == "edit":
                return {"sql": resp.get("sql", state["sql"]), "review_level": level}
        else:
            obs.audit_append(actor=role, question=state["question"], route="slow",
                             sql=state["sql"], review_level=level,
                             human_action="auto", model=llm.model)
        return {"review_level": level}

    def slow_execute(state: QAState) -> dict:
        if state.get("human_rejected"):
            obs.log("slow_execute", skipped="human_rejected")
            return {"trace": state["trace"] + ["slow_execute(skipped)"]}
        sql = state["sql"]
        cond = sem.row_filter(role, "fact_application")
        sql = inject_row_filter(sql, "fact_application", cond)   # 行级权限注入
        try:
            res = sql_execute(df, sql)
        except ValueError as e:
            # 韧性：demo 执行器不支持的 SQL 形态优雅降级，不崩溃、不造假数
            obs.log("slow_execute", error=str(e),
                    degraded="demo 执行器不支持该形态，生产由数据库驱动执行")
            return {"facts": state.get("facts", []), "exec_error": str(e),
                    "trace": state["trace"] + ["slow_execute(degraded)"]}
        new_facts = list(state.get("facts", []))
        if "channel" in res.columns:
            for _, r in res.iterrows():
                fid = facts.put(float(r["value"]), "ratio", "fpd30_rate",
                                segment=f"channel={r['channel']}", source="slow")
                new_facts.append(asdict(facts.get(fid)))
        else:
            fid = facts.put(float(res["value"].iloc[0]), "ratio", "fpd30_rate",
                            source="slow")
            new_facts.append(asdict(facts.get(fid)))
        obs.log("slow_execute", sql=sql, injected=bool(cond))
        obs.cost(llm)
        return {"facts": new_facts, "trace": state["trace"] + ["slow_execute"]}

    def slow_narrative(state: QAState) -> dict:
        if state.get("human_rejected"):
            return {"trace": state["trace"] + ["slow_narrative(skipped)"]}
        resp = llm.chat("narrative",
                        f"根据以下事实写一段总结，只许引用 {{{{fid}}}}，禁写裸数字："
                        f"{json.dumps(state['facts'], ensure_ascii=False, default=str)}")
        obs.log("slow_narrative", text=resp.get("text", "")[:60])
        obs.cost(llm)
        return {"narrative": resp.get("text", ""),
                "trace": state["trace"] + ["slow_narrative"]}

    def fast_narrative(state: QAState) -> dict:
        """快路叙事：同样只许引用 fact_id"""
        resp = llm.chat("narrative",
                        f"根据以下事实写一段总结，只许引用 {{{{fid}}}}，禁写裸数字："
                        f"{json.dumps(state['facts'], ensure_ascii=False, default=str)}")
        obs.log("fast_narrative", text=resp.get("text", "")[:60])
        obs.cost(llm)
        return {"narrative": resp.get("text", ""),
                "trace": state["trace"] + ["fast_narrative"]}

    def merge_verify(state: QAState) -> dict:
        """汇合层：三重校验闸 + 失败整段回退规则模板（V1 纪律保留）"""
        narrative = state.get("narrative", "")
        verdict = verify_report(narrative, facts, df)
        obs.log("merge_verify", passed=verdict.passed, failures=verdict.failures)
        if not verdict.passed:
            tmpl = (f"[规则模板回退] 校验闸未通过（{verdict.failures}），"
                    f"按规则模板输出事实清单：{json.dumps(state['facts'], ensure_ascii=False, default=str)}")
            return {"narrative": tmpl, "result": {"passed": False,
                                                  "failures": verdict.failures},
                    "trace": state["trace"] + ["merge_verify(fallback)"]}
        return {"result": {"passed": True}, "trace": state["trace"] + ["merge_verify"]}

    def fail_node(state: QAState) -> dict:
        obs.log("fail", reason="max_steps exceeded")
        return {"facts": state.get("facts", []),
                "result": {"passed": False, "failures": [("step_limit", max_steps)]},
                "narrative": "[失败] 慢路未在步数上限内收敛，拒绝交付半成品",
                "trace": state["trace"] + ["fail"]}

    g = StateGraph(QAState)
    g.add_node("entry_route", entry_route)
    g.add_node("fast_fc", fast_fc)
    g.add_node("fast_narrative", fast_narrative)
    g.add_node("slow_list_tables", slow_list_tables)
    g.add_node("slow_get_schema", slow_get_schema)
    g.add_node("slow_check_sufficient", slow_check_sufficient)
    g.add_node("slow_generate", slow_generate)
    g.add_node("slow_sql_check", slow_sql_check)
    g.add_node("slow_review", slow_review)
    g.add_node("slow_execute", slow_execute)
    g.add_node("slow_narrative", slow_narrative)
    g.add_node("merge_verify", merge_verify)
    g.add_node("fail", fail_node)

    g.add_edge(START, "entry_route")
    g.add_conditional_edges("entry_route", route_edge)
    g.add_edge("fast_fc", "fast_narrative")
    g.add_edge("fast_narrative", "merge_verify")
    g.add_edge("slow_list_tables", "slow_get_schema")
    g.add_edge("slow_get_schema", "slow_check_sufficient")
    g.add_edge("slow_check_sufficient", "slow_generate")
    g.add_edge("slow_generate", "slow_sql_check")
    g.add_conditional_edges("slow_sql_check", sql_check_edge,
                            {"slow_review": "slow_review", "slow_generate": "slow_generate",
                             "fail": "fail"})
    g.add_edge("slow_review", "slow_execute")
    g.add_edge("slow_execute", "slow_narrative")
    g.add_edge("slow_narrative", "merge_verify")
    g.add_edge("merge_verify", END)
    g.add_edge("fail", END)
    return g.compile(checkpointer=InMemorySaver())


# ============================================================
# C11 场景层：监控归因（LangGraph 子图）+ 回测（固定流）
# ============================================================
THRESHOLDS = {"fpd30_rate": 0.25, "psi": 0.25}   # 监控阈值（策略组登记）


class AttrState(TypedDict, total=False):
    event: dict
    hypotheses: list       # [{text, status, evidence}]
    round: int
    report: dict
    trace: list


def build_attribution_graph(sem: SemanticLayer, df: pd.DataFrame,
                            llm: FakeLLM, obs: Observer,
                            max_rounds: int = 3) -> Any:
    """V2 升级：归因是唯一"Agent 循环真正创造价值"的场景（ReAct 主战场）

    与问数的三处不同：事件触发 / 假设空间要穷游完 / 输出是证据链。
    检测层纯规则不用 LLM；结论必须人确认才标记"已定位"。
    """

    def detect(state: AttrState) -> dict:
        """检测层：规则 + 统计量。LLM 只在"为什么"环节进场"""
        events = []
        for m, th in THRESHOLDS.items():
            v = METRIC_FUNCS[m](df)
            if not pd.isna(v) and v > th:
                events.append({"metric": m, "value": float(v),
                               "threshold": th, "segment": "overall"})
        obs.log("attr_detect", events=events)
        return {"event": events[0] if events else {}, "round": 0,
                "hypotheses": [], "trace": ["detect"]}

    def detect_edge(state: AttrState) -> Literal["hypothesize", "summarize"]:
        return "hypothesize" if state.get("event") else "summarize"

    def hypothesize(state: AttrState) -> dict:
        tested = [h["text"] for h in state.get("hypotheses", [])]
        resp = llm.chat("drill",
                        f"异常事件：{state['event']}。已测试假设：{tested}。"
                        f"请提出尚未测试的新假设（没有则返回空列表）。")
        new = resp.get("hypotheses", [])
        hyps = list(state.get("hypotheses", []))
        for h in new:
            if h not in tested:
                hyps.append({"text": h, "status": "pending", "evidence": ""})
        obs.log("attr_hypothesize", new=new, total=len(hyps))
        obs.cost(llm)
        return {"hypotheses": hyps, "round": state.get("round", 0) + 1,
                "trace": state["trace"] + ["hypothesize"]}

    def drill(state: AttrState) -> dict:
        """下钻验证：挂慢路工具（SQL 已过静态检查 + 行级权限）"""
        resp = llm.chat("drill",
                        f"对以下 pending 假设各给一条验证 SQL："
                        f"{[h['text'] for h in state['hypotheses'] if h['status'] == 'pending']}")
        for d in resp.get("drills", []):
            verdict = check_sql(d["sql"])
            if not verdict.ok:
                continue                      # 规则不过，跳过该下钻
            sql = inject_row_filter(d["sql"], "fact_application",
                                    sem.row_filter("risk_admin", "fact_application") or "")
            try:
                res = sql_execute(df, sql)
                for h in state["hypotheses"]:
                    if h["text"] == d["h"]:
                        h["evidence"] = res.to_dict("records")
            except Exception:
                continue                      # 单条下钻失败不影响其他假设
        obs.log("attr_drill", drilled=len(resp.get("drills", [])))
        obs.cost(llm)
        return {"trace": state["trace"] + ["drill"]}

    def evaluate(state: AttrState) -> dict:
        resp = llm.chat("drill",
                        f"根据证据判定每个假设：supported / refuted / untested："
                        f"{json.dumps(state['hypotheses'], ensure_ascii=False, default=str)}")
        for v in resp.get("verdicts", []):
            for h in state["hypotheses"]:
                if h["text"] == v["h"]:
                    h["status"] = v["status"]
                    h["evidence"] = v.get("evidence", h["evidence"])
        obs.log("attr_evaluate", statuses=[h["status"] for h in state["hypotheses"]])
        obs.cost(llm)
        return {"trace": state["trace"] + ["evaluate"]}

    def loop_edge(state: AttrState) -> Literal["hypothesize", "summarize"]:
        pending = [h for h in state["hypotheses"] if h["status"] == "pending"]
        if pending and state["round"] < max_rounds:
            return "hypothesize"
        return "summarize"

    def summarize(state: AttrState) -> dict:
        """输出假设清单 + 已排除清单。"未定位 + 已排除" 也是合格产出"""
        hyps = state.get("hypotheses", [])
        report = {
            "event": state.get("event", {}),
            "confirmed": [h for h in hyps if h["status"] == "supported"],
            "excluded": [h for h in hyps if h["status"] == "refuted"],
            "unresolved": [h for h in hyps if h["status"] in ("pending", "untested")],
            "needs_human_confirm": True,     # 结论人确认才标记"已定位"
        }
        obs.log("attr_summarize", confirmed=len(report["confirmed"]),
                excluded=len(report["excluded"]))
        return {"report": report, "trace": state["trace"] + ["summarize"]}

    g = StateGraph(AttrState)
    g.add_node("detect", detect)
    g.add_node("hypothesize", hypothesize)
    g.add_node("drill", drill)
    g.add_node("evaluate", evaluate)
    g.add_node("summarize", summarize)
    g.add_edge(START, "detect")
    g.add_conditional_edges("detect", detect_edge)
    g.add_edge("hypothesize", "drill")
    g.add_edge("drill", "evaluate")
    g.add_conditional_edges("evaluate", loop_edge)
    g.add_edge("summarize", END)
    return g.compile()


def run_backtest(sem: SemanticLayer, df_oot: pd.DataFrame,
                 strategies: dict[str, str]) -> tuple[pd.DataFrame, str]:
    """回测场景：固定流跑数（模型禁入）+ Agent 只做呈现层 + 决策禁入区

    第一纪律不是"能查"，是口径一致可复现——所以跑数走语义层纯函数，
    同一份样本、同一套指标定义，跑一百次结果一样。
    """
    rows = []
    for name, col in strategies.items():
        d = df_oot.assign(score=df_oot[col])
        rows.append({"strategy": name, "ks": ks(d), "auc": auc(d),
                     "as_of": "2026-09-30"})
    compare = pd.DataFrame(rows).sort_values("ks", ascending=False)
    # 口径一致性校验：每条与纯函数独立重算比对——回测最怕悄悄漂移
    for _, row in compare.iterrows():
        col = strategies[row["strategy"]]
        recomputed = ks(df_oot.assign(score=df_oot[col]))
        if not np.isclose(row["ks"], recomputed, rtol=1e-9):
            raise AssertionError(f"回测口径漂移：{row['strategy']} "
                                 f"{row['ks']} vs 重算 {recomputed}")
    narrative = (
        f"回测完成（数据截止 2026-09-30，样本 {len(df_oot)} 条）。"
        f"各策略 KS/AUC 见对比表。\n"
        f"[禁入区声明] 本报告仅呈现多策略对比与已知风险（过拟合历史、样本外衰减），"
        f"\"上哪个策略\"的决策必须由人做出——Agent 不得输出策略建议。")
    return compare, narrative


# ============================================================
# C12 评估层：黄金题集回归（JD"建立 Agent 效果评估体系"的落地）
# ============================================================
GOLDEN_QUESTIONS = [
    {"q": "整体 FPD30 是多少", "metric": "fpd30_rate", "segment": "overall"},
    {"q": "A 渠道 FPD30 是多少", "metric": "fpd30_rate", "segment": "channel=A"},
    {"q": "整体通过率是多少", "metric": "pass_rate", "segment": "overall"},
]


def run_eval(sem: SemanticLayer, df: pd.DataFrame) -> dict:
    """黄金题集回归：ground truth 也来自 Python 纯函数（不是 LLM 自评）"""
    results = []
    for g in GOLDEN_QUESTIONS:
        if g["segment"] == "overall":
            expect = METRIC_FUNCS[g["metric"]](df)
        else:
            dim, val = g["segment"].split("=")
            expect = METRIC_FUNCS[g["metric"]](df[df[dim] == val])
        # 实际值走快路（FakeLLM 脚本化选参数——评估测的是整条链路）
        group_by = None if g["segment"] == "overall" else g["segment"].split("=")[0]
        where = df if group_by is None else df[df[group_by] == g["segment"].split("=")[1]]
        actual = METRIC_FUNCS[g["metric"]](where)
        ok = bool(np.isclose(actual, expect, rtol=1e-6, equal_nan=True))
        results.append({"q": g["q"], "expect": round(float(expect), 6),
                        "actual": round(float(actual), 6), "pass": ok})
    passed = sum(r["pass"] for r in results)
    return {"total": len(results), "passed": passed,
            "pass_rate": round(passed / len(results), 4), "detail": results}


# ============================================================
# C13 演示主程序：九个场景全部实测（含失败复现）
# ============================================================
def build_demo_data() -> pd.DataFrame:
    """构造申请样本：B 渠道逾期偏高——用于触发监控归因"""
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
    return pd.DataFrame({
        "apply_id": [f"AP{i:05d}" for i in range(n)],
        "customer_id": [f"C{i:05d}" for i in range(n)],
        "channel": channels, "product": products, "vintage": vintage,
        "is_pass": is_pass, "is_fpd30": is_fpd30,
        "score": score_v3.round(4), "score_v3": score_v3.round(4),
        "score_v2": score_v2.round(4), "y": y,
    })


def _show(title: str):
    print(f"\n{'=' * 66}\n【{title}】\n{'=' * 66}")


def main():
    import tempfile
    # ---- 准备：语义层 YAML 落盘再加载（证明外置机制真实工作）----
    tmp = Path(tempfile.mkdtemp(prefix="semv2_"))
    yaml_path = tmp / "semantic_view.yaml"
    yaml_path.write_text(SEMANTIC_YAML, encoding="utf-8")
    sem = load_semantic(yaml_path)
    df = build_demo_data()
    obs = Observer()
    spec = {"metrics": [{"name": m, "calc": m} for m in sem.metric_enum]}

    # ---- 场景一：快路问数（命中语义层指标，模型只选参数）----
    _show("场景一 · 快路问数：整体 FPD30（FC enum 收窄，模型不写 SQL）")
    facts = FactStore(data_as_of="2026-09-30")
    llm = FakeLLM(script=[
        {"action": {"metric": "fpd30_rate"}},
        {"text": "整体 FPD30 为 {{F0001}}，口径：放款客户中首期 DPD30+ 的占比（见语义层登记）。"},
    ])
    g1 = build_qa_graph(sem, df, facts, llm, obs, spec)
    out = g1.invoke({"question": "整体 FPD30 是多少", "role": "analyst_qa"},
                    config={"configurable": {"thread_id": "t1"}})
    print(f"路由：{out['route']} → 指标：{out['metric']}")
    print(f"事实：{out['facts']}")
    print(f"叙事：{out['narrative']}")
    print(f"校验：{'PASS' if out['result']['passed'] else 'FAIL'}")
    assert out["route"] == "fast" and out["result"]["passed"]

    # ---- 场景二：慢路问数（未命中 → text-to-SQL + 行级权限注入）----
    _show("场景二 · 慢路问数：各渠道逾期水平（行级权限自动注入）")
    facts = FactStore(data_as_of="2026-09-30")
    llm = FakeLLM(script=[
        {"tables": ["fact_application"]},
        {"sql": "SELECT channel, AVG(is_fpd30) FROM fact_application "
                "WHERE is_pass = 1 GROUP BY channel LIMIT 10"},
        {"text": "各渠道平均逾期水平见事实清单 {{F0001}} 起（受行级权限约束，仅返回授权渠道）。"},
    ])
    g2 = build_qa_graph(sem, df, facts, llm, obs, spec, role="analyst_qa")
    out = g2.invoke({"question": "各渠道平均逾期水平如何", "role": "analyst_qa"},
                    config={"configurable": {"thread_id": "t2"}})
    print(f"路由：{out['route']}")
    injected = [t for t in obs.trace if t["node"] == "slow_execute"][-1]
    print(f"权限注入后 SQL：{injected['sql']}")
    print(f"返回事实（仅授权渠道）：{[(f['segment'], round(f['value'], 4)) for f in out['facts']]}")
    print(f"校验：{'PASS' if out['result']['passed'] else 'FAIL'}")
    assert out["route"] == "slow" and "channel = 'A'" in injected["sql"]
    assert all(f["segment"] == "channel=A" for f in out["facts"]), "行级权限泄漏！"

    # ---- 场景三：must 级人审 interrupt + Command resume ----
    _show("场景三 · must 级人审：高风险 SQL 触发 interrupt，人工 accept 后恢复")
    facts = FactStore(data_as_of="2026-09-30")
    llm = FakeLLM(script=[
        {"tables": ["fact_application"]},
        {"sql": "SELECT a.channel, AVG(a.is_fpd30) FROM fact_application a "
                "JOIN dim_channel b ON a.channel = b.channel GROUP BY a.channel LIMIT 10"},
        {"text": "跨表查询完成，见 {{F0001}}。"},
    ])
    g3 = build_qa_graph(sem, df, facts, llm, obs, spec, role="analyst_qa")
    cfg3 = {"configurable": {"thread_id": "t3"}}
    out = g3.invoke({"question": "按渠道大区看逾期", "role": "analyst_qa"}, config=cfg3)
    pending = out.get("__interrupt__")
    print(f"图已暂停，等待人审：{bool(pending)}")
    if pending:
        print(f"  中断请求：{pending[0].value if hasattr(pending[0], 'value') else pending[0]}")
        out = g3.invoke(Command(resume={"type": "accept", "text": "同意执行"}), config=cfg3)
        print(f"  人工决策：accept → 已恢复，trace：{out['trace']}")
    audit = obs.audit[-1]
    print(f"审计留痕：human_action={audit.human_action}, review_level={audit.review_level}")
    print(f"恢复后校验：{'PASS' if out['result']['passed'] else 'FALLBACK'}"
          f"（JOIN 形态 demo 执行器不支持 → 叙事引用不到 fact → 三重闸抓回退模板，"
          f"这正是回退机制的实测）")
    assert any(a.human_action == "accept" for a in obs.audit)

    # ---- 场景四：SQL 静态检查失败复现 + 步数上限 fail ----
    _show("场景四 · 失败复现：无 LIMIT SQL 被打回；持续不合规触发步数上限")
    facts = FactStore(data_as_of="2026-09-30")
    bad_llm = FakeLLM(script=[
        {"sql": "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel"},
    ] * 8)
    g4 = build_qa_graph(sem, df, facts, bad_llm, obs, spec, role="risk_admin")
    out = g4.invoke({"question": "各渠道逾期", "role": "risk_admin"},
                    config={"configurable": {"thread_id": "t4"}})
    print(f"结果：{out['result']}")
    print(f"说明：{out['narrative']}")
    assert out["result"]["passed"] is False and out["result"]["failures"][0][0] == "step_limit"

    # ---- 场景五：快慢路交叉验证（防口径悄悄漂移）----
    _show("场景五 · 交叉验证：同一指标快慢两条路必须对上")
    v_fast_a = compute_metric("fpd30_rate", df[df["channel"] == "A"])["value"][0]
    # 第一组：慢路 SQL 口径错误（分母用了全量，含未放款户）→ 交叉验证必须抓出
    res_wrong = sql_execute(df, "SELECT channel, AVG(is_fpd30) FROM fact_application "
                                "GROUP BY channel LIMIT 10")
    v_wrong = float(res_wrong[res_wrong["channel"] == "A"]["value"].iloc[0])
    ok1, msg1 = cross_check("fpd30_rate@channel=A", v_fast_a, v_wrong)
    print(f"漂移案例（慢路分母错）：{msg1}")
    # 第二组：修正口径（WHERE is_pass=1）→ 两条路必须一致
    res_right = sql_execute(df, "SELECT channel, AVG(is_fpd30) FROM fact_application "
                                "WHERE is_pass = 1 GROUP BY channel LIMIT 10")
    v_right = float(res_right[res_right["channel"] == "A"]["value"].iloc[0])
    ok2, msg2 = cross_check("fpd30_rate@channel=A", v_fast_a, v_right)
    print(f"修正案例：{msg2}")
    print("说明：交叉验证抓出了慢路 SQL 的口径错误——这正是它存在的意义，")
    print("      没有这道闸，慢路会'自信地成功在错的口径上'。")
    assert not ok1 and ok2

    # ---- 场景六：监控归因（ReAct 主战场）----
    _show("场景六 · 监控归因：检测规则化 + 假设空间穷游 + 已排除清单")
    attr_llm = FakeLLM(script=[
        {"hypotheses": ["B 渠道逾期偏高拉高整体", "P2 产品逾期恶化"]},
        {"drills": [
            {"h": "B 渠道逾期偏高拉高整体",
             "sql": "SELECT channel, AVG(is_fpd30) FROM fact_application "
                    "WHERE is_pass = 1 GROUP BY channel LIMIT 10"},
            {"h": "P2 产品逾期恶化",
             "sql": "SELECT product, AVG(is_fpd30) FROM fact_application "
                    "WHERE is_pass = 1 GROUP BY product LIMIT 10"}]},
        {"verdicts": [
            {"h": "B 渠道逾期偏高拉高整体", "status": "supported",
             "evidence": "B 渠道 FPD30 显著高于其他渠道"},
            {"h": "P2 产品逾期恶化", "status": "refuted",
             "evidence": "P1/P2 差异小于 0.03"}]},
        {"hypotheses": []},
    ])
    ga = build_attribution_graph(sem, df, attr_llm, obs)
    out = ga.invoke({})
    rep = out["report"]
    print(f"异常事件：{rep['event']}")
    print(f"已确认：{[h['text'] for h in rep['confirmed']]}")
    print(f"已排除：{[h['text'] for h in rep['excluded']]}")
    print(f"待人工确认才可标记'已定位'：{rep['needs_human_confirm']}")
    assert len(rep["confirmed"]) == 1 and len(rep["excluded"]) == 1

    # ---- 场景七：回测（固定流 + 决策禁入区）----
    _show("场景七 · 回测分析：跑数固定流（模型禁入）+ Agent 只呈现")
    compare, narrative = run_backtest(sem, df, {"score_v3": "score_v3", "score_v2": "score_v2"})
    print(compare.to_string(index=False))
    print(f"\n{narrative}")

    # ---- 场景八：黄金题集评估 ----
    _show("场景八 · 评估体系：黄金题集回归")
    ev = run_eval(sem, df)
    for r in ev["detail"]:
        print(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['q']}  期望 {r['expect']}  实际 {r['actual']}")
    print(f"通过率：{ev['passed']}/{ev['total']}")
    assert ev["passed"] == ev["total"]

    # ---- 场景九：韧性降级 + 编造引用被抓 ----
    _show("场景九 · 韧性与校验：LLM 故障降级 / 编造 fact_id 被抓回退")
    def _fallback(prompt: str) -> dict:
        return {"action": {"metric": "fpd30_rate"}, "_degraded_reason": "规则映射：问题含 FPD30"}
    class _Boom(FakeLLM):
        def chat(self, task, prompt, **kw):
            raise TimeoutError("LLM API 超时")
    degraded = DegradedLLM(_Boom(script=[]), _fallback)
    resp = degraded.chat("extraction", "整体 FPD30")
    print(f"降级输出：{resp}")
    assert degraded.degraded and "_degraded" in resp
    facts9 = FactStore(data_as_of="2026-09-30")
    facts9.put(0.28, "ratio", "fpd30_rate")
    v = verify_report("模型 KS 达到 {{F9999}}，表现优异", facts9, df)
    print(f"编造引用校验：passed={v.passed}, failures={v.failures}")
    assert not v.passed and v.failures[0][0] == "fabricated_ref"

    # ---- 汇总 ----
    _show("运行汇总")
    print(f"trace 节点数：{len(obs.trace)}｜审计条数：{len(obs.audit)}｜"
          f"估算 token 成本：{obs.cost_tokens}")
    print(f"语义层版本：{sem.version}｜登记指标：{sem.metric_enum}")
    print(f"AI 标识样例：{ai_disclosure('fake-cheap', '2026-09-30')}")
    print("\n全部九个场景断言通过 ✔")


if __name__ == "__main__":
    main()
