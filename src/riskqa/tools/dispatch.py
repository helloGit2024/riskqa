"""工具层：调用闸 + 执行分发（结果一律进 FactStore）。"""

from __future__ import annotations

import pandas as pd

from ..calc.metrics import compute_metric
from ..facts.store import FactStore
from .gates import Gate

# 由调用方注入当前语义层指标卡（{name: {...}}）；未注入时按 legacy 原行为空字典。
# 说明：legacy 的 pre_tool_gate/dispatch 直接引用模块级 SEMANTIC，为保持签名与逻辑
# 不变，这里保留同名模块级变量作为注入点，不做签名改造。
SEMANTIC: dict[str, dict] = {}


def pre_tool_gate(action: dict, facts: FactStore) -> Gate:
    """Sensor 1（调用前）：工具白名单 + 指标登记 + 无事实禁出报告"""
    name = action.get("name")
    if name not in {"query_metric", "finish"}:
        return Gate(False, f"工具 {name!r} 不在白名单")
    if name == "query_metric":
        args = action.get("args", {})
        if args.get("metric") not in SEMANTIC:
            return Gate(False, f"指标 {args.get('metric')!r} 未登记，拒绝执行")
        gb = args.get("group_by")
        if gb is not None and gb not in SEMANTIC[args["metric"]]["dims"]:
            return Gate(False, f"维度 {gb!r} 不允许用于 {args['metric']}")
    if name == "finish" and not facts._facts:
        return Gate(False, "尚无任何事实（fact）不允许结束——拒绝空报告")
    return Gate(True)


def dispatch(action: dict, df: pd.DataFrame, facts: FactStore) -> dict:
    """工具执行：结果一律进 FactStore，返回只带 fid——数字从此只有一处来源"""
    name, args = action["name"], action.get("args", {})
    if name == "query_metric":
        res = compute_metric(args["metric"], df, args.get("group_by"))
        if args.get("group_by"):
            fids = [
                facts.put(
                    float(r["value"]),
                    SEMANTIC[args["metric"]]["unit"],
                    args["metric"],
                    f"by {args['group_by']}",
                    segment=f"{args['group_by']}={r['dim']}",
                )
                for _, r in res.iterrows()
            ]
            return {"fids": fids, "table": res.to_dict("records")}
        fid = facts.put(
            float(res["value"][0]), SEMANTIC[args["metric"]]["unit"], args["metric"], "overall"
        )
        return {"fid": fid, "value": float(res["value"][0])}
    return {"ok": True}
