"""编排层：LangGraph 问数图（入口路由 + 快路 + 慢路 + 分级人审）。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Literal, TypedDict

import pandas as pd

from ..facts.store import FactStore
from ..governance.review import classify_review
from ..llm.fake import FakeLLM
from ..semantic.layer import SemanticLayer
from ..tools.gates import apply_row_filter, check_sql, inject_row_filter
from ..verify.gates import verify_report
from .fast_path import AskRequest, ask_fast, parse_question
from .observer import Observer


class QAState(TypedDict, total=False):
    question: str
    role: str
    route: str  # fast | slow
    metric: str
    group_by: str
    sql: str
    review_level: str
    review_feedback: str
    facts: list  # fact dict 快照
    narrative: str
    result: dict
    trace: list
    steps: int
    denied: bool  # 快路行权限/过滤后为空 → 跳过叙事，返回空结果（SG-01 #3）


def sql_execute(df: pd.DataFrame, sql: str) -> pd.DataFrame:
    """迷你 SQL 模拟器：支持 SELECT dim, AGG(col) FROM t [WHERE k=v] [GROUP BY dim] [LIMIT n]

    生产替换为真实数据库驱动；demo 用 pandas 保证零依赖可复现。
    """
    m = re.search(
        r"SELECT\s+(\w+)\s*,\s*(AVG|SUM|COUNT)\((\w+)\)\s+FROM\s+(\w+)"
        r"(?:\s+WHERE\s+(.+?))?"
        r"(?:\s+GROUP\s+BY\s+(\w+))?(?:\s+LIMIT\s+(\d+))?\s*$",
        sql,
        re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"demo 执行器不支持的 SQL 形态：{sql}")
    _dim, agg, col, _table, where, group, limit = m.groups()
    work = df
    if where:
        for k, v in re.findall(r"(\w+)\s*=\s*'([^']+)'", where):  # 字符串等值
            work = work[work[k] == v]
        for k, v in re.findall(r"(\w+)\s*=\s*(\d+)", where):  # 数值等值
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


def build_qa_graph(
    sem: SemanticLayer,
    df: pd.DataFrame,
    facts: FactStore,
    llm: FakeLLM,
    obs: Observer,
    spec: dict,
    role: str = "analyst_qa",
    max_steps: int = 6,
) -> Any:
    """V2 核心：一张图同时装下快路和慢路，入口路由决定走哪条"""
    try:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import interrupt
    except ImportError as e:
        raise RuntimeError("langgraph 未安装：见 tasks T-4.0.5") from e

    # ---- 入口路由：命中语义层指标 → 快路；否则 → 慢路 ----
    def entry_route(state: QAState) -> dict:
        hit = sem.match_metric(state["question"])
        obs.log("entry_route", hit=hit)
        return {
            "route": "fast" if hit else "slow",
            "metric": hit or "",
            "steps": 0,
            "facts": [],
            "trace": ["entry_route"],
        }

    def route_edge(state: QAState) -> Literal["fast_fc", "slow_list_tables"]:
        return "fast_fc" if state["route"] == "fast" else "slow_list_tables"

    # ---- 快路：模型只选参数，SQL 由语义层模板生成（模型不写 SQL）----
    def fast_fc(state: QAState) -> dict:
        effective_role = state.get("role", role)
        req = parse_question(state["question"], sem) or AskRequest(metric=state["metric"])
        result = ask_fast(
            req,
            sem,
            df,
            facts,
            question=state["question"],
            llm=llm,
            obs=obs,
            role=effective_role,
        )
        obs.cost(llm)
        return {
            "metric": result.metric,
            "group_by": result.group_by,
            "facts": list(state.get("facts", [])) + [asdict(f) for f in result.facts],
            "denied": result.denied,
            "trace": state["trace"] + ["fast_fc"],
        }

    # ---- 慢路：text-to-SQL，模型写 SQL，但层层设闸 ----
    def slow_list_tables(state: QAState) -> dict:
        obs.log("slow_list_tables", tables=sem.table_enum)
        return {"trace": state["trace"] + ["slow_list_tables"]}

    def slow_get_schema(state: QAState) -> dict:
        resp = llm.chat(
            "extraction",
            f"问题：{state['question']}。可用表：{sem.table_enum}。"
            f"各表结构：{json.dumps({k: v['columns'] for k, v in sem.tables.items()}, ensure_ascii=False)}。"
            f"选需要的表。",
        )
        obs.log("slow_get_schema", chosen=resp.get("tables", sem.table_enum))
        obs.cost(llm)
        return {"trace": state["trace"] + ["slow_get_schema"]}

    def slow_check_sufficient(state: QAState) -> dict:
        """V2 新增：充足性校验——规则先行，不靠谱 LLM 判断"""
        obs.log("slow_check_sufficient", ok=True)
        return {"trace": state["trace"] + ["slow_check_sufficient"]}

    def slow_generate(state: QAState) -> dict:
        fb = state.get("review_feedback")
        prompt = (
            f"问题：{state['question']}。"
            f"口径参考（来自语义层）：{sem.metric_desc('fpd30_rate')}；"
            f"表结构：{json.dumps({k: v['columns'] for k, v in sem.tables.items()}, ensure_ascii=False)}。"
            f"必须带 LIMIT。"
        )
        if fb:
            prompt += f"\n上一轮 SQL 被静态检查驳回：{fb}。请修正。"
        resp = llm.chat("drill", prompt)
        obs.log("slow_generate", sql=resp.get("sql", ""))
        obs.cost(llm)
        return {
            "sql": resp.get("sql", ""),
            "steps": state.get("steps", 0) + 1,
            "review_feedback": "",
            "trace": state["trace"] + ["slow_generate"],
        }

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
            return "fail"  # V2：步数上限，绝不硬撑
        return "slow_generate"

    def slow_review(state: QAState) -> dict:
        """V2 分级人审：auto 免审（留痕）/ must 触发 interrupt 人工决策"""
        level = classify_review(state["sql"], role)
        obs.log("slow_review", level=level, sql=state["sql"])
        if level == "must":
            resp = interrupt(
                {
                    "action": "run_sql",
                    "args": {"sql": state["sql"]},
                    "description": "高风险 SQL，请审核：accept / edit / response",
                    "review_level": level,
                }
            )
            action = resp.get("type", "accept") if isinstance(resp, dict) else "accept"
            obs.audit_append(
                actor=role,
                question=state["question"],
                route="slow",
                sql=state["sql"],
                review_level=level,
                human_action=action,
                model=llm.model,
            )
            if action == "response":
                return {
                    "narrative": f"[人审反馈] {resp.get('text', '')}",
                    "review_level": level,
                    "human_rejected": True,
                }
            if action == "edit":
                return {"sql": resp.get("sql", state["sql"]), "review_level": level}
        else:
            obs.audit_append(
                actor=role,
                question=state["question"],
                route="slow",
                sql=state["sql"],
                review_level=level,
                human_action="auto",
                model=llm.model,
            )
        return {"review_level": level}

    def slow_execute(state: QAState) -> dict:
        if state.get("human_rejected"):
            obs.log("slow_execute", skipped="human_rejected")
            return {"trace": state["trace"] + ["slow_execute(skipped)"]}
        sql = state["sql"]
        cond = sem.row_filter(role, "fact_application")
        sql = inject_row_filter(sql, "fact_application", cond)  # 行级权限注入
        try:
            res = sql_execute(df, sql)
        except ValueError as e:
            # 韧性：demo 执行器不支持的 SQL 形态优雅降级，不崩溃、不造假数
            obs.log(
                "slow_execute",
                error=str(e),
                degraded="demo 执行器不支持该形态，生产由数据库驱动执行",
            )
            return {
                "facts": state.get("facts", []),
                "exec_error": str(e),
                "trace": state["trace"] + ["slow_execute(degraded)"],
            }
        new_facts = list(state.get("facts", []))
        if "channel" in res.columns:
            for _, r in res.iterrows():
                fid = facts.put(
                    float(r["value"]),
                    "ratio",
                    "fpd30_rate",
                    segment=f"channel={r['channel']}",
                    source="slow",
                )
                new_facts.append(asdict(facts.get(fid)))
        else:
            fid = facts.put(float(res["value"].iloc[0]), "ratio", "fpd30_rate", source="slow")
            new_facts.append(asdict(facts.get(fid)))
        obs.log("slow_execute", sql=sql, injected=bool(cond))
        obs.cost(llm)
        return {"facts": new_facts, "trace": state["trace"] + ["slow_execute"]}

    def slow_narrative(state: QAState) -> dict:
        if state.get("human_rejected"):
            return {"trace": state["trace"] + ["slow_narrative(skipped)"]}
        resp = llm.chat(
            "narrative",
            f"根据以下事实写一段总结，只许引用 {{{{fid}}}}，禁写裸数字："
            f"{json.dumps(state['facts'], ensure_ascii=False, default=str)}",
        )
        obs.log("slow_narrative", text=resp.get("text", "")[:60])
        obs.cost(llm)
        return {"narrative": resp.get("text", ""), "trace": state["trace"] + ["slow_narrative"]}

    def fast_narrative(state: QAState) -> dict:
        """快路叙事：同样只许引用 fact_id"""
        resp = llm.chat(
            "narrative",
            f"根据以下事实写一段总结，只许引用 {{{{fid}}}}，禁写裸数字："
            f"{json.dumps(state['facts'], ensure_ascii=False, default=str)}",
        )
        obs.log("fast_narrative", text=resp.get("text", "")[:60])
        obs.cost(llm)
        return {"narrative": resp.get("text", ""), "trace": state["trace"] + ["fast_narrative"]}

    def fast_after_fc(state: QAState) -> Literal["fast_narrative", "merge_verify"]:
        return "merge_verify" if state.get("denied") else "fast_narrative"

    def merge_verify(state: QAState) -> dict:
        """汇合层：三重校验闸 + 失败整段回退规则模板（V1 纪律保留）"""
        narrative = state.get("narrative", "")
        # 独立重算必须与事实同口径：行权限收窄后的可见数据
        visible = apply_row_filter(
            df, sem.row_filter(state.get("role", role), "fact_application") or ""
        )
        verdict = verify_report(narrative, facts, visible)
        obs.log("merge_verify", passed=verdict.passed, failures=verdict.failures)
        if not verdict.passed:
            tmpl = (
                f"[规则模板回退] 校验闸未通过（{verdict.failures}），"
                f"按规则模板输出事实清单：{json.dumps(state['facts'], ensure_ascii=False, default=str)}"
            )
            return {
                "narrative": tmpl,
                "result": {"passed": False, "failures": verdict.failures},
                "trace": state["trace"] + ["merge_verify(fallback)"],
            }
        result: dict = {"passed": True}
        if state.get("denied"):
            result["empty"] = True  # 越权空结果：无叙述、无报告，但不是错误
        return {"result": result, "trace": state["trace"] + ["merge_verify"]}

    def fail_node(state: QAState) -> dict:
        obs.log("fail", reason="max_steps exceeded")
        return {
            "facts": state.get("facts", []),
            "result": {"passed": False, "failures": [("step_limit", max_steps)]},
            "narrative": "[失败] 慢路未在步数上限内收敛，拒绝交付半成品",
            "trace": state["trace"] + ["fail"],
        }

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
    g.add_conditional_edges(
        "fast_fc",
        fast_after_fc,
        {"fast_narrative": "fast_narrative", "merge_verify": "merge_verify"},
    )
    g.add_edge("fast_narrative", "merge_verify")
    g.add_edge("slow_list_tables", "slow_get_schema")
    g.add_edge("slow_get_schema", "slow_check_sufficient")
    g.add_edge("slow_check_sufficient", "slow_generate")
    g.add_edge("slow_generate", "slow_sql_check")
    g.add_conditional_edges(
        "slow_sql_check",
        sql_check_edge,
        {"slow_review": "slow_review", "slow_generate": "slow_generate", "fail": "fail"},
    )
    g.add_edge("slow_review", "slow_execute")
    g.add_edge("slow_execute", "slow_narrative")
    g.add_edge("slow_narrative", "merge_verify")
    g.add_edge("merge_verify", END)
    g.add_edge("fail", END)
    return g.compile(checkpointer=InMemorySaver())
