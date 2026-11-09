"""响应装配：把图 state / DB 行映射成契约对象，并做失败 → 错误码的唯一转换。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from ..orchestration.graph_qa import metric_from_sql
from ..store.review import ReviewRepo
from .errors import ApiError
from .runtime import AI_DISCLOSURE, ENGINE_TO_CONTRACT, build_signature, public_fact

EMPTY_TEXT = "当前身份在该指标上无可见数据（行级权限收窄后为空），未生成结论。"
PENDING_TEXT = "高风险 SQL 已挂起，须 Owner 确认后方可引用。"

_FAILURE_CODES = {
    "timeout": ("E_SLA_TIMEOUT", "慢路超出时间预算，已熔断"),
    "step_limit": ("E_SLOW_UNCONVERGED", "慢路未在修正轮数内收敛"),
    "cross_check": ("E_RECOMPUTE_MISMATCH", "交叉验证不一致（两侧数字并列，不做平均）"),
    "bare_number": ("E_BARE_NUMBER", "叙事含未引用数字"),
    "illegal_ref": ("E_FABRICATED_REF", "叙事引用格式非法或不存在"),
    "fabricated_ref": ("E_FABRICATED_REF", "叙事引用了不存在的事实"),
    "unregistered_calc": ("E_CALC_NOT_REGISTERED", "事实对应指标未注册纯函数"),
    "render_mismatch": ("E_RECOMPUTE_MISMATCH", "引用值与独立重算不一致"),
}


def _fmt_failure(item) -> str:
    return " ".join(str(x) for x in item) if isinstance(item, tuple) else str(item)


def failures_to_strings(failures: list) -> list[str]:
    return [_fmt_failure(f) for f in failures]


def outcome_error(out: dict) -> ApiError | None:
    """图返回的失败 → 契约错误码；成功返回 None。

    `cross_fail` 的两侧数字放在 message 里作为诊断信息（与 T-4.1.3 的
    「双侧并列、不做平均」一致），不进入叙事层。
    """
    failures = (out.get("result") or {}).get("failures") or []
    if not failures:
        return None
    kinds = {f[0] for f in failures if isinstance(f, tuple)}
    detail = "；".join(failures_to_strings(failures))
    for kind in (
        "timeout",
        "step_limit",
        "cross_check",
        "bare_number",
        "illegal_ref",
        "fabricated_ref",
        "unregistered_calc",
        "render_mismatch",
    ):
        if kind in kinds:
            code, text = _FAILURE_CODES[kind]
            return ApiError(code, f"{text}：{detail}")
    return ApiError("E_RECOMPUTE_MISMATCH", f"结果未通过校验：{detail}")


def caliber(sem, metric: str) -> dict:
    meta = sem.metrics.get(metric) or {}
    return {
        "desc": meta.get("desc", ""),
        "owner": meta.get("owner", ""),
        "signed_at": meta.get("signed_at", ""),
    }


def review_level(engine_level: str | None) -> str:
    return ENGINE_TO_CONTRACT.get(engine_level or "", "none")


def ask_payload(out: dict, sem, time_range: str = "all") -> dict:
    # 续跑时若执行降级，state 没有 slow_metric：从 SQL 反推，避免 metric 留空
    metric = out.get("metric") or out.get("slow_metric") or metric_from_sql(out.get("sql") or "")
    signature = build_signature(metric, out.get("group_by", ""), out.get("scope"), time_range)
    if out.get("denied"):
        return {
            "route": out.get("route", "fast"),
            "metric": metric,
            "signature": signature,
            "answer_text": EMPTY_TEXT,
            "facts": [],
            "caliber": caliber(sem, metric),
            "review_level": "none",
            "ai_disclosure": AI_DISCLOSURE,
        }
    return {
        "route": out.get("route", "fast"),
        "metric": metric,
        "signature": signature,
        "answer_text": out.get("narrative", ""),
        "facts": [public_fact(f) for f in out.get("facts", [])],
        "caliber": caliber(sem, metric),
        "review_level": review_level(out.get("review_level")),
        "ai_disclosure": AI_DISCLOSURE,
    }


def explore_payload(out: dict, sem, review: dict) -> dict:
    result = out.get("result") or {}
    return {
        "sql": out.get("sql", ""),
        "verdict": {
            "passed": bool(result.get("passed", True)),
            "failures": failures_to_strings(result.get("failures") or []),
            "cross_check": out.get("cross_check") or {},
        },
        "review": review,
        "facts": [public_fact(f) for f in out.get("facts", [])],
    }


def review_payload(row: dict) -> dict:
    """ReviewRecord 白名单投影（material / 内部列不外泄）"""
    return {
        "rid": row["rid"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "level": row["level"],
        "state": row["state"],
        "assignee": row["assignee"],
        "decided_by": row.get("decided_by"),
        "decision": row.get("decision"),
        "decided_at": row.get("decided_at"),
    }


def sla_due(governance) -> str:
    return (datetime.now() + timedelta(hours=governance.review.sla_hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


def create_review(
    conn: sqlite3.Connection,
    governance,
    *,
    rid: str,
    subject_type: str,
    subject_id: str,
    engine_level: str,
    assignee: str,
    material: dict,
) -> dict:
    """落一条评审记录：auto 直接 signed（留痕），sample/must 挂 pending。"""
    level = review_level(engine_level)
    state = "signed" if level == "none" else "pending"
    repo = ReviewRepo(conn)
    repo.insert(
        rid=rid,
        subject_type=subject_type,
        subject_id=subject_id,
        level=level,
        assignee=assignee,
        sla_due=sla_due(governance),
        state=state,
        material=material,
    )
    return repo.get(rid)
