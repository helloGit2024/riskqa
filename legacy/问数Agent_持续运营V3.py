# -*- coding: utf-8 -*-
"""
风控问数 Agent · 持续运营机制 V3（企业版）
============================================
在 V2 底座（语义层 / 快慢双路 / 三重校验闸）之上，新增语义层持续运营闭环：
raw log → 意图抽取（SQL 锚点）→ 归并聚类 → 热度+防失真 → 冲突检测
→ 评审材料 → Owner 签字 → 晋升（evidence 快照固化 + alias 回填）

设计纪律（与 V2 一致，不可违反）：
  D1 意图抽取以 SQL 结构为主依据、自然语言为辅——SQL 没有歧义，问题文本有
  D2 filters 只记字段不记值——A 产品/B 产品是同一签名的不同实例，热度按签名聚合
  D3 LLM 只做翻译（SQL→签名）、提问（冲突清单）、汇编（材料）；判断与人审禁入
  D4 raw log 不可变；归一化算法可改进重跑，不动原始数据
  D5 晋升必须过 Owner 口径签字；热度只决定优先级，不决定正确性
  D6 治理参数三层（全局/域覆盖/临时），变更留痕，护栏非法即拒
  D7 evidence 快照自包含固化——raw log 按合规保留 1 年，删除后审计仍可回答
     “这个指标哪来的”

依赖：pandas、pyyaml（其余标准库）。生产环境把 RuleExtractor 换成真 LLM，
接口不变（extract(question, sql) -> Signature）。
"""
from __future__ import annotations

import re
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

# ============================================================
# 第 0 层 · 复用底座核心（精简自 V2，持续运营挂在同一套底座上）
# ============================================================

SEMANTIC_YAML = """
version: "2.0"
metrics:
  - name: fpd30_rate
    desc: "首期逾期率：放款客户中首期 DPD30+ 的占比（分母=放款户，宽限期 3 天）"
    unit: ratio
    dims: [channel, product, vintage]
    calc: fpd30_rate
    owner: 风控策略组
    signed_at: "2026-09-30"
    aliases: [fpd30, 首期逾期, 首期逾期率]
    changelog:
      - {date: "2026-09-30", version: v1.0, note: "初版"}
  - name: pass_rate
    desc: "通过率：审批通过申请数 / 提交申请数（分母口径：提交数）"
    unit: ratio
    dims: [channel, product, vintage]
    calc: pass_rate
    owner: 风控策略组
    signed_at: "2026-09-30"
    aliases: [通过率]
    changelog:
      - {date: "2026-09-30", version: v1.0, note: "初版"}
tables:
  - name: fact_application
    base_table: dwd.fact_application
row_policies:
  analyst_qa: "channel IN ('A','B','C')"
"""


class SemanticLayer:
    """语义层：指标定义的单一事实源。FC 的 enum、别名归一都从这里出。"""

    def __init__(self, yaml_text: str):
        cfg = yaml.safe_load(yaml_text)
        self.version: str = cfg["version"]
        self.metrics: dict[str, dict] = {m["name"]: m for m in cfg["metrics"]}
        self.tables: dict[str, dict] = {t["name"]: t for t in cfg["tables"]}
        self.row_policies: dict[str, dict] = cfg.get("row_policies", {})

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


def fpd30_rate(df: pd.DataFrame) -> float:
    """纯函数指标：分母=放款户（V2 实测修正过的口径）"""
    d = df[df["is_pass"] == 1]
    return float(d["is_fpd30"].mean()) if len(d) else 0.0


def pass_rate(df: pd.DataFrame) -> float:
    return float(df["is_pass"].mean()) if len(df) else 0.0


METRIC_FUNCS = {"fpd30_rate": fpd30_rate, "pass_rate": pass_rate}


def compute_metric(metric: str, df: pd.DataFrame) -> dict:
    if metric not in METRIC_FUNCS:
        raise ValueError(f"{metric} 未注册，拒绝静默跳过")
    return {"value": [METRIC_FUNCS[metric](df)]}


# ============================================================
# 第 1 层 · 治理配置（三层 + 护栏）
# ============================================================

GOVERNANCE_YAML = """
global:
  promotion:
    min_users: 3
    min_queries: 5
    min_days: 5
    max_top_user_share: 0.8
    max_active_days_gap: 2
  window_days: 30
  retention_days: 365
  review:
    sla_hours: 72
    escalate_after_sla: 2
    shelve_after_sla: 7
overrides:
  collection_ops:
    promotion: {min_users: 5}
temporary:
  - {param: global.promotion.min_users, value: 2,
     reason: "双十一期间临时放宽", by: "值班人·李四", expires: "2026-11-15"}
"""


@dataclass(frozen=True)
class PromotionRule:
    min_users: int
    min_queries: int
    min_days: int
    max_top_user_share: float
    max_active_days_gap: int


@dataclass(frozen=True)
class ReviewRule:
    sla_hours: int
    escalate_after_sla: int
    shelve_after_sla: int


@dataclass(frozen=True)
class GovernanceConfig:
    promotion: PromotionRule
    window_days: int
    retention_days: int
    review: ReviewRule

    def for_domain(self, domain: str, overrides: dict) -> PromotionRule:
        """第二层：主题域覆盖。返回该域生效的晋升规则"""
        ov = (overrides or {}).get(domain, {}).get("promotion")
        if not ov:
            return self.promotion
        merged = {**asdict(self.promotion), **ov}
        return PromotionRule(**merged)

    def apply_temporary(self, temporary: list[dict], today: str) -> "GovernanceConfig":
        """第三层：未过期的临时调整叠加生效；过期忽略"""
        import dataclasses
        cfg = self
        for t in temporary or []:
            if t.get("expires", "9999") >= today:
                cfg = dataclasses.replace(
                    cfg,
                    promotion=dataclasses.replace(
                        cfg.promotion,
                        **{t["param"].split(".")[-1]: t["value"]}))
        return cfg


def validate_governance(cfg: GovernanceConfig) -> list[str]:
    """护栏：非法配置拒绝加载，保持上一版，不让系统带病运行"""
    errs: list[str] = []
    p = cfg.promotion
    if p.min_users < 1:
        errs.append("min_users < 1：任何查询都能晋升，机制形同虚设")
    if p.min_queries < p.min_users:
        errs.append("min_queries < min_users：阈值自相矛盾")
    if p.min_days < 1:
        errs.append("min_days < 1：允许单日集中刷量晋升")
    if not 0.5 < p.max_top_user_share <= 1.0:
        errs.append("max_top_user_share 必须落在 (0.5, 1.0]")
    if cfg.window_days > cfg.retention_days:
        errs.append("热度窗口 > 保留期限：窗口内数据已被删除，热度永远算不出")
    if cfg.review.sla_hours < 24:
        errs.append("SLA < 24h：会把 Owner 变成瓶颈，评审队列必堆积")
    return errs


def load_governance(yaml_text: str, today: str = "2026-10-30") -> GovernanceConfig:
    raw = yaml.safe_load(yaml_text)
    g = raw["global"]
    cfg = GovernanceConfig(
        promotion=PromotionRule(**g["promotion"]),
        window_days=g["window_days"],
        retention_days=g["retention_days"],
        review=ReviewRule(**g["review"]))
    errs = validate_governance(cfg)
    if errs:
        raise GovernanceError("治理配置未过护栏，拒绝加载：" + "；".join(errs))
    return cfg.apply_temporary(raw.get("temporary"), today)


class GovernanceError(Exception):
    """治理配置非法——护栏拒绝"""


# ============================================================
# 第 2 层 · raw log 与意图签名
# ============================================================

@dataclass(frozen=True)
class QueryLog:
    """D4：raw log 不可变，唯一事实源；派生数据全部可重算"""
    qid: str
    question: str
    sql: str
    sql_edited: bool
    result_digest: dict
    user: str
    dept: str
    ts: str                    # ISO date，热度时间分布靠它
    confirmed_by: tuple[str, ...]


@dataclass(frozen=True)
class Signature:
    """D2：filters 只记字段不记值——参数变体是同一签名的实例"""
    metric: str
    dims: tuple[str, ...]
    filters: tuple[str, ...]
    time_range: str

    def key(self) -> str:
        return f"{self.metric}|{','.join(self.dims)}|{','.join(self.filters)}|{self.time_range}"


class RuleExtractor:
    """模拟 LLM 的意图抽取器：以 SQL 结构为主依据（D1）。
    生产环境替换为真 LLM（接口不变），此处用规则保证演示可复现。"""

    METRIC_PATTERNS = [
        (re.compile(r"AVG\(\s*is_fpd30\s*\)", re.I), "fpd30_rate"),
        (re.compile(r"AVG\(\s*is_pass\s*\)", re.I), "pass_rate"),
        (re.compile(r"SUM\(\s*loan_amt\s*\)", re.I), "loan_amt"),
    ]

    def extract(self, question: str, sql: str, sem: SemanticLayer) -> Signature:
        metric = "unknown"
        for pat, name in self.METRIC_PATTERNS:
            if pat.search(sql):
                metric = name
                break
        if metric == "unknown":                    # SQL 认不出，才用问题文本猜
            for token in re.findall(r"[A-Za-z_一-龥]+", question.lower()):
                if sem.resolve_alias(token):
                    metric = sem.resolve_alias(token)
                    break
        gb = re.search(r"GROUP BY\s+(\w+)", sql, re.I)
        dims = tuple(sorted({gb.group(1)})) if gb else ()
        where = re.search(r"WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|$)", sql, re.I | re.S)
        filters: tuple[str, ...] = ()
        if where:
            filters = tuple(sorted(set(
                re.findall(r"(\w+)\s*=", where.group(1)))))
        tw = re.search(r"(\d+)\s*[dD]\b|最近\s*(\d+)\s*(天|月|年)", question)
        time_range = "all"
        if tw:
            n = int(tw.group(1) or tw.group(2))
            unit = (tw.group(3) or "d").lower()
            time_range = {"d": f"{n}d", "天": f"{n}d", "月": f"{n*30}d",
                          "年": f"{n*365}d"}.get(unit, "all")
        return Signature(metric=metric, dims=dims, filters=filters,
                         time_range=time_range)


# ============================================================
# 第 3 层 · 归并聚类 · 热度 · 防失真 · 冲突检测
# ============================================================

@dataclass
class Cluster:
    sig: Signature
    logs: list[QueryLog] = field(default_factory=list)
    variants: set[str] = field(default_factory=set)
    sql_variants: dict[str, int] = field(default_factory=dict)   # SQL → 次数
    conflicts: list[str] = field(default_factory=list)           # 冲突描述（给人看的）


def normalize_sql(sql: str) -> str:
    """口径归一化：WHERE/LIMIT 里的字面值替换为占位符。
    product='A' 与 product='B' 是同一口径的不同实例（D2），不是冲突。"""
    s = re.sub(r"'[^']*'", "?", sql)
    s = re.sub(r'"[^"]*"', "?", s)
    s = re.sub(r"\b\d+(\.\d+)?\b", "?", s)
    return re.sub(r"\s+", " ", s).strip()


def cluster_logs(logs: list[QueryLog], sem: SemanticLayer,
                 extractor: RuleExtractor) -> dict[str, Cluster]:
    """代码做精确归并；SQL 口径差异在此暴露——这是机制最值钱的产出"""
    clusters: dict[str, Cluster] = {}
    for lg in logs:
        sig = extractor.extract(lg.question, lg.sql, sem)
        c = clusters.setdefault(sig.key(), Cluster(sig=sig))
        c.logs.append(lg)
        c.variants.add(lg.question)
        norm_sql = normalize_sql(lg.sql)
        c.sql_variants[norm_sql] = c.sql_variants.get(norm_sql, 0) + 1
    for c in clusters.values():
        if len(c.sql_variants) > 1:
            c.conflicts = [f"同一签名下发现 {len(c.sql_variants)} 种口径："
                           + " | ".join(f"[{n}次] {s[:60]}..."
                                        for s, n in c.sql_variants.items())]
    return clusters


def caliber_fingerprint(sql: str) -> str:
    """口径指纹：聚合表达式 + WHERE 条件（字面值归一化后）。
    GROUP BY 维度差异是同一指标的不同切法（签名已区分），不算口径冲突；
    分母、过滤条件、聚合逻辑不同才是真冲突。"""
    agg = re.search(r"(AVG|SUM|COUNT)\([^)]*\)", sql, re.I)
    where = re.search(r"WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|$)", sql, re.I | re.S)
    agg_s = normalize_sql(agg.group(0)) if agg else "NOAGG"
    where_s = normalize_sql(where.group(1)) if where else "NOWHERE"
    return f"{agg_s} # {where_s}"


def detect_metric_conflicts(clusters: dict[str, Cluster]) -> list[dict]:
    """跨签名的指标级冲突检测：同一 metric 的所有签名互相比对口径指纹。
    WHERE is_pass=1 与无 WHERE 签名不同，但业务上是同一指标的两种口径——
    只在同签名内检测，这类冲突永远抓不到（V3 实测补上的洞）。"""
    by_metric: dict[str, list[tuple[str, Cluster]]] = {}
    for cid, c in clusters.items():
        by_metric.setdefault(c.sig.metric, []).append((cid, c))
    out: list[dict] = []
    for metric, cs in by_metric.items():
        fingerprints: dict[str, list] = {}          # 指纹 → [(集群, SQL)]
        for cid, c in cs:
            for sql, n in c.sql_variants.items():
                fingerprints.setdefault(caliber_fingerprint(sql), []).append((c, sql, n))
        if len(fingerprints) > 1:
            out.append({"metric": metric,
                        "versions": {fp: sum(n for _, _, n in lst)
                                     for fp, lst in fingerprints.items()},
                        "groups": fingerprints,
                        "n_queries": sum(len(c.logs) for _, c in cs)})
    return out


def heat(cluster: Cluster, today: str = "2026-10-30") -> dict:
    """热度三维度：独立用户 / 时间分布 / 集中度——任一形态异常都要看得见"""
    win_start = (datetime.strptime(today, "%Y-%m-%d")
                 - timedelta(days=30)).strftime("%Y-%m-%d")
    logs = [lg for lg in cluster.logs if lg.ts >= win_start]
    users = {lg.user for lg in logs}
    days = {lg.ts for lg in logs}
    per_user = Counter(lg.user for lg in logs)
    top_share = (per_user.most_common(1)[0][1] / len(logs)) if logs else 1.0
    return {
        "n_queries": len(logs),
        "n_users": len(users),
        "n_days": len(days),
        "top_user_share": round(top_share, 3),
        "concentrated": len(days) <= 2 and len(logs) > 3,   # 会议批量查询
        "edited_ratio": round(sum(lg.sql_edited for lg in logs) / len(logs), 3)
        if logs else 0.0,
    }


def nominate(cluster: Cluster, rule: PromotionRule,
             today: str = "2026-10-30") -> tuple[bool, str]:
    """D5：热度只决定是否进评审队列（优先级），不决定口径正确性"""
    h = heat(cluster, today)
    if h["concentrated"]:
        return False, f"查询集中在 {h['n_days']} 个自然日，疑似会议批量，不计热度"
    if h["top_user_share"] > rule.max_top_user_share:
        return False, f"单人占比 {h['top_user_share']:.0%} 超上限，疑似日报刷量"
    if h["n_users"] >= rule.min_users or \
       (h["n_queries"] >= rule.min_queries and h["n_days"] >= rule.min_days):
        return True, f"达标：{h['n_users']} 用户 / {h['n_queries']} 次 / {h['n_days']} 天"
    return False, f"未达标：{h['n_users']} 用户 / {h['n_queries']} 次 / {h['n_days']} 天"


# ============================================================
# 第 4 层 · 评审材料（Owner 视角：十分钟看完，只回答问题和签字）
# ============================================================

def build_review_material(metric: str, clusters: list[Cluster], sem: SemanticLayer,
                          today: str = "2026-10-30") -> str:
    """Owner 视角材料：按签名分组呈现——先看全景，再看每个口径的用的人和 SQL，
    最后只回答待裁问题。十分钟签字，不碰 YAML。"""
    logs = [lg for c in clusters for lg in c.logs]
    n_users = len({lg.user for lg in logs})
    n_days = len({lg.ts for lg in logs})
    variants = sorted({q for c in clusters for q in c.variants})
    fps = {caliber_fingerprint(s) for c in clusters for s in c.sql_variants}
    fp_counts = Counter(caliber_fingerprint(next(iter(c.sql_variants)))
                        for c in clusters)
    main_fp = fp_counts.most_common(1)[0][0]     # 多数口径，视为基准
    lines = [
        f"# 待评审指标：{metric}",
        f"## 全景（{len(logs)} 次查询，{n_users} 位用户，{n_days} 天，"
        f"{len(variants)} 种问法，{len(clusters)} 个签名，{len(fps)} 种口径）",
    ]
    for cid, c in sorted((c.sig.key(), c) for c in clusters):
        h = heat(c, today)
        sql = next(iter(c.sql_variants))
        same = caliber_fingerprint(sql) == main_fp
        warn = "" if same or len(fps) == 1 else "  ⚠️ 口径与多数签名不一致"
        lines += [f"## 签名 {cid}（{h['n_queries']} 次，{h['n_users']} 用户）{warn}",
                  f"- 问法：{'、'.join(sorted(c.variants)[:4])}"
                  f"{' …' if len(c.variants) > 4 else ''}",
                  f"```sql\n{sql}\n```"]
    if len(fps) > 1:
        lines += ["## 需要你裁决的问题",
                  "1. 上述签名中存在口径不一致（过滤条件/分母不同），以哪个为正确定义？"
                  "（多口径并存 = 两份报告数字对不上，这正是本机制要拦死的事故）"]
    else:
        lines += ["## 需要你确认的问题",
                  "1. 该口径是否符合指标定义？边界（分母、宽限期、观察期）是否明确？"]
    lines += [f"2. 是否需要补充维度（{len(variants)} 种问法里未出现的维度不默认加）",
              f"## 证据链\n- 查询记录 QID：{', '.join(lg.qid for lg in logs[:8])}"
              f"{' …' if len(logs) > 8 else ''}（每条可打开原始 SQL 核对）"]
    return "\n".join(lines)


# ============================================================
# 第 5 层 · 晋升：Owner 签字 → evidence 快照固化 → alias 回填
# ============================================================

@dataclass(frozen=True)
class ReviewRecord:
    rid: str
    cid: str
    decided_by: str
    decision: str            # promote / reject / merge
    chosen_sql: str
    note: str
    decided_at: str


def promote(cluster: Cluster, rec: ReviewRecord, sem: SemanticLayer,
            today: str = "2026-10-30") -> str:
    """D7：evidence 快照自包含——raw log 一年后删除，审计仍可回答“指标哪来的”"""
    h = heat(cluster, today)
    if rec.decision != "promote":
        raise ValueError("只有 decision=promote 能晋升")
    name = cluster.sig.metric
    digest = hashlib.sha256(
        json.dumps(sorted(cluster.variants), ensure_ascii=False).encode()).hexdigest()[:12]
    entry = {
        "name": name,
        "desc": f"{name}（由持续运营机制晋升，签名 {cluster.sig.key()}）",
        "unit": "ratio",
        "dims": list(cluster.sig.dims) or ["channel"],
        "calc": name,
        "owner": rec.decided_by,
        "signed_at": rec.decided_at,
        "aliases": sorted(cluster.variants),          # 问法聚类回填 alias（D1 收益）
        "provenance": {                               # D7：自包含证据快照
            "promoted_at": rec.decided_at,
            "owner": rec.decided_by,
            "evidence_snapshot": {
                "n_queries": h["n_queries"], "n_users": h["n_users"],
                "window": f"{today} 前 30 天",
                "question_variants": sorted(cluster.variants),
                "sql_selected": rec.chosen_sql,
                "variants_digest": digest,
                "review_record": rec.rid,
            },
        },
        "changelog": [{"date": rec.decided_at, "version": "v1.0",
                       "note": f"持续运营晋升（{rec.rid}）：{rec.note}"}],
    }
    cfg = yaml.safe_load(sem.to_yaml())
    cfg["metrics"] = [m for m in cfg["metrics"] if m["name"] != name] + [entry]
    return yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)


# ============================================================
# 第 6 层 · 评审升级链（防队列堆积拖死机制）
# ============================================================

@dataclass
class ReviewState:
    cid: str
    status: str = "pending_review"      # pending / reminded / overdue / shelved / done
    entered_at: str = "2026-10-01"
    history: list[str] = field(default_factory=list)


def tick(state: ReviewState, now: str, rule: ReviewRule) -> ReviewState:
    """超时推进：提醒 → 升级 → 组织搁置（shelved ≠ rejected：是没人管，不是口径错）"""
    waited_h = (datetime.strptime(now, "%Y-%m-%d %H:%M")
                - datetime.strptime(state.entered_at + " 00:00", "%Y-%m-%d %H:%M")
                ).total_seconds() / 3600
    if state.status == "done":
        return state
    if waited_h >= rule.shelve_after_sla * rule.sla_hours:
        state.status = "shelved"
    elif waited_h >= rule.escalate_after_sla * rule.sla_hours:
        state.status = "overdue"
    elif waited_h >= rule.sla_hours:
        state.status = "reminded"
    state.history.append(f"{now} → {state.status}")
    return state


# ============================================================
# 演示：构造 200 条查询日志，跑完整闭环
# ============================================================

def gen_logs(n: int = 200) -> list[QueryLog]:
    """构造 6 类集群，覆盖全部防失真设计：
       C1 健康达标（fpd30 按渠道，8 用户 23 天）
       C2 口径冲突（fpd30 同签名下 2 种 SQL：分母=放款户 vs 全量）
       C3 单人刷量（单人 60%，应被 max_top_user_share 拦）
       C4 会议集中（全部压在 2 天，应被 concentrated 拦）
       C5 低频未达标（3 用户 3 次）
       C6 参数变体（A/B/C 产品 × 30d/365d，应与 C1 同理按签名聚合）"""
    import random
    rng = random.Random(42)
    users = [f"u{i:02d}" for i in range(1, 11)]
    logs: list[QueryLog] = []
    qn = 0

    def add(q, sql, user, day, edited=False, conf=("u00",)):
        nonlocal qn
        qn += 1
        logs.append(QueryLog(f"Q{qn:04d}", q, sql, edited,
                             {"value": 0.2}, user, "风险策略部", day, conf))

    # C1：健康集群（47 次，8 用户，23 天）
    c1_questions = ["各渠道 FPD30 怎么样", "按渠道看首期逾期", "渠道维度逾期率",
                    "各渠道 FPD30", "按渠道看首期逾期情况"]
    for i in range(47):
        add(c1_questions[i % len(c1_questions)],
            "SELECT channel, AVG(is_fpd30) AS v FROM fact_application "
            "WHERE is_pass=1 GROUP BY channel LIMIT 10",
            users[i % 8], f"2026-10-{(i % 23) + 1:02d}",
            edited=(i % 11 == 0), conf=(users[(i + 1) % 8],))
    # C2：同签名口径冲突（16 次，SQL 缺 WHERE is_pass=1）
    for i in range(16):
        add(["渠道逾期率看一下", "分渠道首期逾期"][i % 2],
            "SELECT channel, AVG(is_fpd30) AS v FROM fact_application "
            "GROUP BY channel LIMIT 10",
            users[8 + (i % 2)], f"2026-10-{(i % 20) + 3:02d}", conf=("u09",))
    # C3：单人刷量（30 次里 25 次是 u03，占比 83% > 80% 应被拦）
    for i in range(30):
        add("按产品看逾期", "SELECT product, AVG(is_fpd30) AS v FROM fact_application "
            "WHERE is_pass=1 GROUP BY product LIMIT 10",
            "u03" if i < 25 else users[(i + 3) % 8],
            f"2026-10-{(i % 28) + 1:02d}")
    # C4：会议集中（12 次全压在第 5、6 天）
    for i in range(12):
        add("各渠道通过率", "SELECT channel, AVG(is_pass) AS v FROM fact_application "
            "GROUP BY channel LIMIT 10",
            users[i % 6], f"2026-10-{5 + (i % 2):02d}")
    # C5：低频未达标（2 用户 2 次 2 天，任何维度都不达标）
    for i in range(2):
        add("vintage 维度通过率", "SELECT vintage, AVG(is_pass) AS v FROM fact_application "
            "GROUP BY vintage LIMIT 10",
            users[i * 3], f"2026-10-{i * 9 + 1:02d}")
    # C6：参数变体（A/B/C 产品 × 时间窗，签名应与各自等价聚合）
    c6_products = ["A", "B", "C"]
    for i in range(92):
        p = c6_products[i % 3]
        tw = ["最近一个月", "最近一年"][i % 2]
        add(f"{p}产品放款量{tw}",
            f"SELECT product, SUM(loan_amt) AS v FROM fact_application "
            f"WHERE product='{p}' GROUP BY product LIMIT 10",
            users[(i + 2) % 9], f"2026-10-{(i % 25) + 1:02d}")
    rng.shuffle(logs)
    return logs[:n] if n < len(logs) else logs


def main():
    print("=" * 72)
    print("风控问数 Agent · 持续运营机制 V3 —— 完整闭环演示")
    print("=" * 72)
    sem = SemanticLayer(SEMANTIC_YAML)
    today = "2026-10-30"

    # ---- 场景一：治理配置加载 + 护栏 ----
    print("\n── 场景一 · 治理配置三层加载与护栏 ──")
    gov = load_governance(GOVERNANCE_YAML, today)
    raw_global = yaml.safe_load(GOVERNANCE_YAML)["global"]
    ov = yaml.safe_load(GOVERNANCE_YAML)["overrides"]
    print(f"全局晋升阈值：min_users={raw_global['promotion']['min_users']}，"
          f"30 天窗口={gov.window_days} 天，保留={gov.retention_days} 天")
    print(f"临时调整生效（双十一）：min_users {raw_global['promotion']['min_users']} → "
          f"{gov.promotion.min_users}（到期自动失效）")
    print(f"主题域覆盖（催收团队）：min_users={gov.for_domain('collection_ops', ov).min_users}")
    bad = GOVERNANCE_YAML.replace("window_days: 30", "window_days: 400")
    try:
        load_governance(bad, today)
        print("护栏失效：window=400 > retention=365 竟然加载了")
    except GovernanceError as e:
        print(f"护栏拦截：{e}")

    # ---- 场景二：200 条日志 → 意图抽取 → 归并 ----
    print("\n── 场景二 · raw log → 意图抽取（SQL 锚点）→ 归并聚类 ──")
    logs = gen_logs(200)
    clusters = cluster_logs(logs, sem, RuleExtractor())
    print(f"原始查询 {len(logs)} 条 → 唯一签名 {len(clusters)} 个，"
          f"归一压缩比 {len(logs) / len(clusters):.1f}×")
    for cid, c in sorted(clusters.items(), key=lambda kv: -len(kv[1].logs)):
        print(f"  [{len(c.logs):3d} 次] {cid}  问法变体 {len(c.variants)} 种")

    # ---- 场景三：热度 + 防失真 ----
    print("\n── 场景三 · 热度统计与四类失真拦截 ──")
    for cid, c in sorted(clusters.items(), key=lambda kv: -len(kv[1].logs)):
        h, (ok, why) = heat(c, today), nominate(c, gov.promotion, today)
        flag = "✅提名" if ok else "⛔ 拦截"
        print(f"  {flag} {cid}")
        print(f"        {h['n_queries']} 次 / {h['n_users']} 用户 / {h['n_days']} 天 / "
              f"单人占比 {h['top_user_share']:.0%} → {why}")

    # ---- 场景四：冲突检测（口径指纹口径级，机制最值钱的产出）----
    print("\n── 场景四 · 冲突检测：同一指标多种口径 ──")
    metric_conflicts = detect_metric_conflicts(clusters)
    for mc in metric_conflicts:
        print(f"  ⚠️  指标 {mc['metric']}（合计 {mc['n_queries']} 次查询）"
              f"存在 {len(mc['versions'])} 种口径：")
        for fp, n in sorted(mc["versions"].items(), key=lambda kv: -kv[1]):
            print(f"        [{n:3d} 次在用] 口径指纹 {fp}")
        print("        → 拦在评审环节，“两份报告数字对不上”这类事故就此止步")
    assert metric_conflicts, "演示数据应触发跨签名冲突（is_pass 过滤 vs 无过滤）"
    no_conflict = [m for m in ("pass_rate", "loan_amt")
                   if m not in {mc["metric"] for mc in metric_conflicts}]
    print(f"  无误报验证：{no_conflict} 仅有维度切法差异，未误判为口径冲突")

    # ---- 场景五：评审材料（Owner 视角，按签名分组）----
    print("\n── 场景五 · 评审材料生成（Owner 只看这份，十分钟签字）──")
    fpd = [c for cid, c in clusters.items() if c.sig.metric == "fpd30_rate"]
    material = build_review_material("fpd30_rate", fpd, sem, today)
    print("\n".join("  " + ln for ln in material.splitlines()[:22]))

    # ---- 场景六：新指标完整晋升叙事（loan_amt：签字 → 快照 → alias → 纯函数注册）----
    print("\n── 场景六 · 新指标晋升：Owner 签字 → evidence 快照 → alias 回填 ──")
    loan = [c for cid, c in clusters.items() if c.sig.metric == "loan_amt"][0]
    rec = ReviewRecord("R-2026-090", loan.sig.key(), "风控策略组·王五",
                       "promote", next(iter(loan.sql_variants)),
                       "口径确认：放款量=SUM(loan_amt)，分母不适用，维度=产品", today)
    new_yaml = promote(loan, rec, sem, today)
    sem2 = SemanticLayer(new_yaml)
    m = sem2.metrics["loan_amt"]
    print(f"晋升成功：{m['name']}  owner={m['owner']}  dims={m['dims']}")
    print(f"alias 回填 {len(m['aliases'])} 个历史问法 → 下次同义提问直接命中快路")
    print(f"evidence 快照已固化（自包含，raw log 一年后删除仍可审计）")
    # 晋升 ≠ 快路可用：快路由纯函数服务，纯函数必须同步注册（计算层一毫米不让）
    try:
        compute_metric("loan_amt", pd.DataFrame({"loan_amt": [1.0], "is_pass": [1]}))
        print("纯函数已注册")
    except ValueError:
        print("⚠️  快路尚不可用：loan_amt 无纯函数实现。晋升的指标必须同步注册"
              "纯函数，否则快路拒绝服务——这正是“计算层一毫米不让”的纪律")

    def compute_loan_amt(df: pd.DataFrame) -> float:
        return float(df["loan_amt"].sum())

    METRIC_FUNCS["loan_amt"] = compute_loan_amt          # 同步注册后才可走快路
    demo_df = pd.DataFrame({"loan_amt": [120.5, 380.0, 95.5], "is_pass": [1, 1, 1],
                            "product": ["A", "B", "A"]})
    v = compute_metric("loan_amt", demo_df)["value"][0]
    print(f"✅ 纯函数注册后快路可用：loan_amt = {v}")
    assert abs(v - 596.0) < 1e-9

    # ---- 场景七：升级链（防队列堆积）----
    print("\n── 场景七 · Owner 超时升级链 ──")
    st = ReviewState("sig_stuck", entered_at="2026-10-01")
    for now in ["2026-10-03 09:00", "2026-10-05 09:00", "2026-10-09 09:00",
                "2026-10-25 09:00"]:
        tick(st, now, gov.review)
        print(f"  {now} → 状态 {st.status}")
    assert st.status == "shelved", "7×SLA 后应组织搁置"

    # ---- 场景八：晋升生效验证（alias 命中 → 快路可用）----
    print("\n── 场景八 · 晋升生效验证：问法聚类回填 alias，同义提问直达快路 ──")
    for q in ["A产品放款量最近一个月", "B产品放款量最近一年", "C产品放款量最近一个月"]:
        hit = sem2.resolve_alias(q)
        print(f"  「{q}」 → {'命中 ' + hit if hit else '未命中'}")
    assert sem2.resolve_alias("A产品放款量最近一个月") == "loan_amt", \
        "问法聚类应回填为 alias"
    print("\n" + "=" * 72)
    print("八个场景全部通过：护栏 / 归并 / 防失真 / 冲突 / 材料 / 晋升 / 升级 / 命中")
    print("=" * 72)


if __name__ == "__main__":
    main()
