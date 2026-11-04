# -*- coding: utf-8 -*-
"""编排层：监控归因（LangGraph 子图）。"""

from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

import pandas as pd

from ..calc.metrics import METRIC_FUNCS
from ..llm.fake import FakeLLM
from ..semantic.layer import SemanticLayer
from ..tools.gates import check_sql, inject_row_filter
from .graph_qa import sql_execute
from .observer import Observer

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
    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError as e:
        raise RuntimeError("langgraph 未安装：见 tasks T-4.0.5") from e

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
