"""校验闸中间件（T-4.1.6）：编排层唯一入口，不过即整段回退规则模板。"""

from __future__ import annotations

import pandas as pd

from ..facts.store import FactStore
from .fallback import fallback_to_template
from .gates import verify_report


def scoped_df(df: pd.DataFrame, scope: dict | None) -> pd.DataFrame:
    """按快路 scope 重建重算数据：filters 逐条等值收窄（与计算前一致）。

    time_range 目前只随 scope 回传、不参与收窄——缺口登记在 OPEN-QUESTIONS #34。
    """
    work = df
    for key, value in (scope or {}).get("filters", {}).items():
        work = work[work[key] == value]
    return work


def run_verify_gate(
    *,
    narrative: str,
    facts: FactStore,
    df: pd.DataFrame,
    scope: dict | None,
    spec: dict,
    obs,
    question: str,
    role: str,
    route: str,
    model: str = "",
) -> dict:
    """执行三重校验；失败整段回退并把回退事件写入审计（回退率可审计统计）。"""
    verdict = verify_report(narrative, facts, scoped_df(df, scope))
    obs.log("merge_verify", passed=verdict.passed, failures=list(verdict.failures))
    if verdict.passed:
        return {"passed": True, "failures": [], "narrative": narrative, "fallback": False}

    reason = str(verdict.failures)
    text = fallback_to_template(spec, facts, reason)
    # 回退产物本身含裸数字，属 P-06 例外：只输出事实清单，不再进校验闸
    obs.audit_append(
        actor=role,
        question=question,
        route=route,
        sql=f"verify_gate failures={reason}",
        review_level="auto",
        human_action="verify_fallback",
        model=model,
    )
    return {
        "passed": False,
        "failures": list(verdict.failures),
        "narrative": text,
        "fallback": True,
    }
