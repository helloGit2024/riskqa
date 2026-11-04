"""治理层：raw log → 意图签名 → 归并聚类 → 热度/防失真/冲突（V3 版）。"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import ClassVar

from ..semantic.layer import SemanticLayer
from .config import PromotionRule


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
    ts: str  # ISO date，热度时间分布靠它
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

    METRIC_PATTERNS: ClassVar[list[tuple[re.Pattern[str], str]]] = [
        (re.compile(r"AVG\(\s*is_fpd30\s*\)", re.IGNORECASE), "fpd30_rate"),
        (re.compile(r"AVG\(\s*is_pass\s*\)", re.IGNORECASE), "pass_rate"),
        (re.compile(r"SUM\(\s*loan_amt\s*\)", re.IGNORECASE), "loan_amt"),
    ]

    def extract(self, question: str, sql: str, sem: SemanticLayer) -> Signature:
        metric = "unknown"
        for pat, name in self.METRIC_PATTERNS:
            if pat.search(sql):
                metric = name
                break
        if metric == "unknown":  # SQL 认不出，才用问题文本猜
            for token in re.findall(r"[A-Za-z_一-龥]+", question.lower()):
                if sem.resolve_alias(token):
                    metric = sem.resolve_alias(token)
                    break
        gb = re.search(r"GROUP BY\s+(\w+)", sql, re.IGNORECASE)
        dims = tuple(sorted({gb.group(1)})) if gb else ()
        where = re.search(r"WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|$)", sql, re.IGNORECASE | re.DOTALL)
        filters: tuple[str, ...] = ()
        if where:
            filters = tuple(sorted(set(re.findall(r"(\w+)\s*=", where.group(1)))))
        tw = re.search(r"(\d+)\s*[dD]\b|最近\s*(\d+)\s*(天|月|年)", question)
        time_range = "all"
        if tw:
            n = int(tw.group(1) or tw.group(2))
            unit = (tw.group(3) or "d").lower()
            time_range = {"d": f"{n}d", "天": f"{n}d", "月": f"{n * 30}d", "年": f"{n * 365}d"}.get(
                unit, "all"
            )
        return Signature(metric=metric, dims=dims, filters=filters, time_range=time_range)


@dataclass
class Cluster:
    sig: Signature
    logs: list[QueryLog] = field(default_factory=list)
    variants: set[str] = field(default_factory=set)
    sql_variants: dict[str, int] = field(default_factory=dict)  # SQL → 次数
    conflicts: list[str] = field(default_factory=list)  # 冲突描述（给人看的）


def normalize_sql(sql: str) -> str:
    """口径归一化：WHERE/LIMIT 里的字面值替换为占位符。
    product='A' 与 product='B' 是同一口径的不同实例（D2），不是冲突。"""
    s = re.sub(r"'[^']*'", "?", sql)
    s = re.sub(r'"[^"]*"', "?", s)
    s = re.sub(r"\b\d+(\.\d+)?\b", "?", s)
    return re.sub(r"\s+", " ", s).strip()


def cluster_logs(
    logs: list[QueryLog], sem: SemanticLayer, extractor: RuleExtractor
) -> dict[str, Cluster]:
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
            c.conflicts = [
                f"同一签名下发现 {len(c.sql_variants)} 种口径："
                + " | ".join(f"[{n}次] {s[:60]}..." for s, n in c.sql_variants.items())
            ]
    return clusters


def caliber_fingerprint(sql: str) -> str:
    """口径指纹：聚合表达式 + WHERE 条件（字面值归一化后）。
    GROUP BY 维度差异是同一指标的不同切法（签名已区分），不算口径冲突；
    分母、过滤条件、聚合逻辑不同才是真冲突。"""
    agg = re.search(r"(AVG|SUM|COUNT)\([^)]*\)", sql, re.IGNORECASE)
    where = re.search(r"WHERE\s+(.+?)(?:GROUP|ORDER|LIMIT|$)", sql, re.IGNORECASE | re.DOTALL)
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
        fingerprints: dict[str, list] = {}  # 指纹 → [(集群, SQL)]
        for _, c in cs:
            for sql, n in c.sql_variants.items():
                fingerprints.setdefault(caliber_fingerprint(sql), []).append((c, sql, n))
        if len(fingerprints) > 1:
            out.append(
                {
                    "metric": metric,
                    "versions": {fp: sum(n for _, _, n in lst) for fp, lst in fingerprints.items()},
                    "groups": fingerprints,
                    "n_queries": sum(len(c.logs) for _, c in cs),
                }
            )
    return out


def heat(cluster: Cluster, today: str = "2026-10-30") -> dict:
    """热度三维度：独立用户 / 时间分布 / 集中度——任一形态异常都要看得见"""
    win_start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
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
        "concentrated": len(days) <= 2 and len(logs) > 3,  # 会议批量查询
        "edited_ratio": round(sum(lg.sql_edited for lg in logs) / len(logs), 3) if logs else 0.0,
    }


def nominate(cluster: Cluster, rule: PromotionRule, today: str = "2026-10-30") -> tuple[bool, str]:
    """D5：热度只决定是否进评审队列（优先级），不决定口径正确性"""
    h = heat(cluster, today)
    if h["concentrated"]:
        return False, f"查询集中在 {h['n_days']} 个自然日，疑似会议批量，不计热度"
    if h["top_user_share"] > rule.max_top_user_share:
        return False, f"单人占比 {h['top_user_share']:.0%} 超上限，疑似日报刷量"
    if h["n_users"] >= rule.min_users or (
        h["n_queries"] >= rule.min_queries and h["n_days"] >= rule.min_days
    ):
        return True, f"达标：{h['n_users']} 用户 / {h['n_queries']} 次 / {h['n_days']} 天"
    return False, f"未达标：{h['n_users']} 用户 / {h['n_queries']} 次 / {h['n_days']} 天"


def build_review_material(
    metric: str, clusters: list[Cluster], sem: SemanticLayer, today: str = "2026-10-30"
) -> str:
    """Owner 视角材料：按签名分组呈现——先看全景，再看每个口径的用的人和 SQL，
    最后只回答待裁问题。十分钟签字，不碰 YAML。"""
    logs = [lg for c in clusters for lg in c.logs]
    n_users = len({lg.user for lg in logs})
    n_days = len({lg.ts for lg in logs})
    variants = sorted({q for c in clusters for q in c.variants})
    fps = {caliber_fingerprint(s) for c in clusters for s in c.sql_variants}
    fp_counts = Counter(caliber_fingerprint(next(iter(c.sql_variants))) for c in clusters)
    main_fp = fp_counts.most_common(1)[0][0]  # 多数口径，视为基准
    lines = [
        f"# 待评审指标：{metric}",
        (
            f"## 全景（{len(logs)} 次查询，{n_users} 位用户，{n_days} 天，"
            f"{len(variants)} 种问法，{len(clusters)} 个签名，{len(fps)} 种口径）"
        ),
    ]
    for cid, c in sorted((c.sig.key(), c) for c in clusters):
        h = heat(c, today)
        sql = next(iter(c.sql_variants))
        same = caliber_fingerprint(sql) == main_fp
        warn = "" if same or len(fps) == 1 else "  ⚠️ 口径与多数签名不一致"
        lines += [
            f"## 签名 {cid}（{h['n_queries']} 次，{h['n_users']} 用户）{warn}",
            (f"- 问法：{'、'.join(sorted(c.variants)[:4])}{' …' if len(c.variants) > 4 else ''}"),
            f"```sql\n{sql}\n```",
        ]
    if len(fps) > 1:
        lines += [
            "## 需要你裁决的问题",
            (
                "1. 上述签名中存在口径不一致（过滤条件/分母不同），以哪个为正确定义？"
                "（多口径并存 = 两份报告数字对不上，这正是本机制要拦死的事故）"
            ),
        ]
    else:
        lines += [
            "## 需要你确认的问题",
            "1. 该口径是否符合指标定义？边界（分母、宽限期、观察期）是否明确？",
        ]
    lines += [
        f"2. 是否需要补充维度（{len(variants)} 种问法里未出现的维度不默认加）",
        (
            f"## 证据链\n- 查询记录 QID：{', '.join(lg.qid for lg in logs[:8])}"
            f"{' …' if len(logs) > 8 else ''}（每条可打开原始 SQL 核对）"
        ),
    ]
    return "\n".join(lines)
