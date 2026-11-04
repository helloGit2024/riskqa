# -*- coding: utf-8 -*-
"""
问数 Agent · 金融风控落地版（生产骨架）
=================================================================
运行： python 问数Agent_金融风控落地.py
依赖： pandas、numpy（无需数据库、无需 LLM API key，用 FakeLLM 驱动）

这是《问数Agent_初学者最小闭环.py》的生产形态，补齐五件事：
  ① 语义层带"指标卡"：Owner 签字 + 变更历史，口径变更走评审（监管可解释）
  ② 数据走快照 + manifest：血缘可查、同 spec 同快照产物字节级一致
  ③ FC schema 从语义层自动生成：新增指标不改工具代码
  ④ fact_id 机制：全文唯一数字来源，模型禁写裸数字只许引用
  ⑤ 三重校验闸：裸数字扫描 / 编造引用检测 / Python 独立重算比对
     —— 任何一道不过，整段回退规则模板，绝不交付半成品

架构分层（对应方案文档 L0-L4）：
  M1 语义层   SEMANTIC + MetricCard + tool_schema 自动生成
  M2 数据层   load_snapshot() + Manifest + 缺失值归一（'' / 'unknown' / -999 → NaN）
  M3 计算层   纯函数指标（fpd30 / ks / auc / psi）+ recompute_all 独立重算入口
  M4 事实层   FactStore：put/get/digest/manifest
  M5 工具层   build_tools() + dispatch() + pre/post gate
  M6 校验层   verify()：三重检查
  M7 编排层   run() 主循环 + 三场景（问数 / 报告 / 监控归因）
  M8 测试层   FakeLLM 驱动的失败场景复现（不花 token、结果可复现）
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

import numpy as np
import pandas as pd

# ============================================================
# M1 语义层：指标的唯一登记处
# ============================================================
# 生产形态：本 dict 等价于一份 semantic_view.yaml，由业务 Owner 逐条
# 签字后入库；口径变更必须重走评审并写 changelog，不许直接改。
# 这里的 expr 为"口径描述"，真实计算在 M3 的纯函数里，由函数名绑定。
SEMANTIC: dict = {
    "fpd30_rate": {
        "desc": "首期逾期率：放款客户中首期 DPD30+ 的占比",
        "unit": "ratio",
        "dims": ["channel", "product", "vintage"],
        "calc": "fpd30_rate",                 # 绑定 M3 的纯函数名
        "owner": "风控策略组",
        "signed_at": "2026-09-30",
        "changelog": [("2026-09-30", "v1.0", "初版：放款后 30 天 DPD30+，宽限期 3 天")],
    },
    "ks": {
        "desc": "KS：好坏样本累计分布差的最大值（按 score 降序）",
        "unit": "ratio",
        "dims": ["vintage"],
        "calc": "ks",
        "owner": "模型组",
        "signed_at": "2026-09-30",
        "changelog": [("2026-09-30", "v1.0", "初版：OOT 样本上计算")],
    },
    "auc": {
        "desc": "AUC：ROC 曲线下面积",
        "unit": "ratio",
        "dims": ["vintage"],
        "calc": "auc",
        "owner": "模型组",
        "signed_at": "2026-09-30",
        "changelog": [],
    },
    "psi": {
        "desc": "PSI：分数分布稳定性（期望 vs 实际，10 等宽分箱）",
        "unit": "ratio",
        "dims": ["vintage"],
        "calc": "psi",
        "owner": "模型组",
        "signed_at": "2026-09-30",
        "changelog": [],
    },
}

METRIC_ENUM = sorted(SEMANTIC)                  # 工具 enum 的唯一来源
DIM_ENUM = sorted({d for s in SEMANTIC.values() for d in s["dims"]})


class UnregisteredMetricError(Exception):
    """模型或不登记的口径——拒绝执行，不猜不填"""


# ============================================================
# M2 数据层：快照 + manifest（血缘）+ 缺失值归一
# ============================================================
@dataclass(frozen=True)
class Manifest:
    """血缘凭证：报告首页必须印出 data_as_of；同 spec + 同快照 → 产物一致"""
    source: str
    locator: str
    data_as_of: str
    rows: int
    data_hash: str


def normalize_missing(df: pd.DataFrame) -> pd.DataFrame:
    """入口只做一次：'' / 'unknown' / -999 一律归一为 NaN。
    绝不下游各自理解——这是两份报告数字对不上的常见根因。"""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].replace({"": np.nan, "unknown": np.nan, "Unknown": np.nan})
    return out.replace(-999, np.nan)


def load_snapshot(df: pd.DataFrame, source: str, locator: str, data_as_of: str):
    """生产里 locator 是 parquet 路径；这里直接吃内存 DataFrame。
    返回 (归一后的 df, manifest)——上层计算层只认这个二元组。"""
    norm = normalize_missing(df)
    digest = hashlib.sha256(
        pd.util.hash_pandas_object(norm, index=True).values.tobytes()).hexdigest()[:16]
    return norm, Manifest(source=source, locator=locator,
                          data_as_of=data_as_of, rows=len(norm), data_hash=digest)

# ============================================================
# M3 计算层：纯函数指标（LLM 禁入，测试覆盖率要求 100%）
# ============================================================
def _ks(y: pd.Series, score: pd.Series) -> float:
    d = pd.DataFrame({"y": y, "s": score}).dropna().sort_values("s", ascending=False)
    pos, neg = (d.y == 1).cumsum() / max((d.y == 1).sum(), 1), (d.y == 0).cumsum() / max((d.y == 0).sum(), 1)
    return float((pos - neg).abs().max())


def _auc(y: pd.Series, score: pd.Series) -> float:
    d = pd.DataFrame({"y": y, "s": score}).dropna()
    n_pos, n_neg = int((d.y == 1).sum()), int((d.y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    r = d["s"].rank()
    return float((r[d.y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    cuts = np.linspace(0, 1, bins + 1)
    lo, hi = min(expected.min(), actual.min()), max(expected.max(), actual.max())
    edges = [lo + (hi - lo) * c for c in cuts]
    e = np.histogram(expected, bins=edges)[0] / max(len(expected), 1)
    a = np.histogram(actual, bins=edges)[0] / max(len(actual), 1)
    e, a = np.clip(e, 1e-6, None), np.clip(a, 1e-6, None)   # 防除零与 log(0)
    return float(((a - e) * np.log(a / e)).sum())


CALC: dict[str, Callable] = {
    "fpd30_rate": lambda d, seg: float(d.loc[seg, "y"].mean()) if len(d.loc[seg]) else float("nan"),
    "ks":         lambda d, seg: _ks(d.loc[seg, "y"], d.loc[seg, "score"]),
    "auc":        lambda d, seg: _auc(d.loc[seg, "y"], d.loc[seg, "score"]),
    "psi":        lambda d, seg: _psi(d["score"], d.loc[seg, "score"]),
}


def compute_metric(metric: str, df: pd.DataFrame, group_by: str = None) -> pd.DataFrame:
    """统一的取数入口：查登记 → 调纯函数。未登记指标直接抛错。"""
    if metric not in SEMANTIC:
        raise UnregisteredMetricError(f"{metric!r} 未登记，已登记：{METRIC_ENUM}")
    fn = CALC[SEMANTIC[metric]["calc"]]
    if group_by is None:
        return pd.DataFrame({"value": [fn(df, df.index)], "n": [len(df)]})
    rows = [{"dim": k, "value": fn(df, df[group_by] == k), "n": int((df[group_by] == k).sum())}
            for k in sorted(df[group_by].dropna().unique())]
    return pd.DataFrame(rows)


def recompute_all(spec: dict, df: pd.DataFrame) -> dict:
    """校验闸专用：与主流水线完全独立的 Python 重算入口。
    不信任模型，也不信任自己的流水线——重算一遍再比对。"""
    out = {}
    for sheet in spec["sheets"]:
        mod, params = sheet["module"], sheet.get("params", {})
        if mod == "overall_metrics":
            for m in params["metrics"]:
                out[m] = compute_metric(m, df)["value"][0]
        elif mod == "by_dimension":
            for m in params["metrics"]:
                for _, r in compute_metric(m, df, params["dimension"]).iterrows():
                    out[f"{m}@{params['dimension']}={r['dim']}"] = r["value"]
    return out

# ============================================================
# M4 事实层：fact_id——全文唯一数字来源
# ============================================================
@dataclass(frozen=True)
class Fact:
    fid: str
    value: object
    unit: str
    metric: str
    source: str
    segment: str = ""        # 拆解维度定位，如 "channel=渠道A"；整体指标留空


class UnknownFactError(Exception):
    """模型引用了不存在的 fact_id——编造，直接抛"""


class FactStore:
    def __init__(self):
        self._facts: dict[str, Fact] = {}
        self._seq = 0

    def put(self, value, unit: str, metric: str, source: str, segment: str = "") -> str:
        self._seq += 1
        fid = f"F{self._seq:04d}"
        self._facts[fid] = Fact(fid, value, unit, metric, source, segment)
        return fid

    def get(self, fid: str) -> Fact:
        try:
            return self._facts[fid]
        except KeyError:
            raise UnknownFactError(f"{fid} 不存在——模型编造了引用")

    def digest(self) -> list[dict]:
        """注入上下文：模型需要知道有哪些数可用、各是多少，才能写叙事"""
        return [asdict(f) for f in self._facts.values()]

    def manifest(self) -> dict:
        return {"count": len(self._facts),
                "sha256": hashlib.sha256(json.dumps(
                    [asdict(f) for f in self._facts.values()],
                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}

# ============================================================
# M5 工具层：FC schema（enum 从语义层来）+ dispatch + 前后闸
# ============================================================
def build_tools() -> list[dict]:
    """新增指标只改 SEMANTIC，工具 schema 自动跟上——单一事实源"""
    return [
        {"name": "query_metric",
         "description": "查询已登记指标。只返回数值与 fact_id，不返回解释、不返回结论。",
         "input_schema": {"type": "object", "properties": {
             "metric": {"type": "string", "enum": METRIC_ENUM},
             "group_by": {"type": "string", "enum": DIM_ENUM}},
             "required": ["metric"]}},
        {"name": "finish", "description": "完成当前任务",
         "input_schema": {"type": "object", "properties": {}}},
    ]


@dataclass
class Gate:
    ok: bool
    reason: str = ""


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
        if "group_by" in args and args["group_by"]:
            fids = [facts.put(float(r["value"]), SEMANTIC[args["metric"]]["unit"],
                              args["metric"], f"by {args['group_by']}",
                              segment=f"{args['group_by']}={r['dim']}")
                    for _, r in res.iterrows()]
            return {"fids": fids, "table": res.to_dict("records")}
        fid = facts.put(float(res["value"][0]), SEMANTIC[args["metric"]]["unit"],
                        args["metric"], "overall")
        return {"fid": fid, "value": float(res["value"][0])}
    return {"ok": True}

# ============================================================
# M6 校验层：三重检查——整个方案的安全底线
# ============================================================
FACT_REF = re.compile(r"\{\{(F\d{4})\}\}")
BARE_NUMBER = re.compile(r"(?<!\{)\b\d+\.\d{1,4}\b(?!\})")   # 0.35 这种裸小数


@dataclass
class Verdict:
    passed: bool
    failures: list = field(default_factory=list)


def verify_report(text: str, facts: FactStore, spec: dict, df: pd.DataFrame) -> Verdict:
    failures = []

    # 检查 1：叙事层不许出现裸数字，必须在 {{F0001}} 里
    for hit in BARE_NUMBER.findall(text):
        failures.append(("bare_number", hit))

    # 检查 2：所有引用必须存在（抓编造）
    for fid in FACT_REF.findall(text):
        try:
            facts.get(fid)
        except UnknownFactError as e:
            failures.append(("fabricated_ref", str(e)))

    # 检查 3：渲染一致性——Python 独立重算，不经 LLM、不经流水线
    # 匹配规则：metric + segment 双重精确定位，防止把整体值误配到拆解值上
    for key, expect in recompute_all(spec, df).items():
        metric, _, seg = key.partition("@")          # seg 形如 "channel=渠道A" 或 ""
        match = [f for f in facts.digest()
                 if f["metric"] == metric and f.get("segment", "") == seg]
        if not match:
            failures.append(("missing_fact", key))
        elif not np.isclose(float(match[0]["value"]), float(expect), rtol=1e-6, equal_nan=True):
            failures.append(("render_mismatch", key,
                             f"报告 {match[0]['value']} vs 重算 {expect}"))
    return Verdict(passed=not failures, failures=failures)


def fallback_to_template(spec: dict, facts: FactStore, reason: str) -> str:
    """整段回退规则模板：可用性让位一致性，绝不交付没穿盔甲的数字"""
    lines = [f"[规则模板回退] 原因：{reason}"]
    for f in facts.digest():
        lines.append(f"  {f['metric']} = {f['value']}（{f['source']}，口径见语义层）")
    return "\n".join(lines)

# ============================================================
# M7 编排层：主循环 + 三场景
# ============================================================
class FakeLLM:
    """按脚本返回动作。测编排层和闸门：不花 token、不受网络影响、可复现"""
    def __init__(self, script: list):
        self._script = list(script)
        self.calls: list[list] = []

    def chat(self, messages, tools, **kw) -> dict:
        self.calls.append(messages)
        return self._script.pop(0) if self._script else {"name": "finish", "args": {}}


def run_agent(spec: dict, df: pd.DataFrame, llm, max_steps: int = 20):
    """主循环：组装 → 决策 → 前闸 → 执行 → 后检 → 收敛 → 终检 → 交付/回退"""
    facts = FactStore()
    trace = []

    for step in range(1, max_steps + 1):
        messages = [{"role": "system", "content": "只许引用 {{fid}}，禁写裸数字"},
                    {"role": "user", "content": json.dumps(spec, ensure_ascii=False)},
                    {"role": "user", "content": json.dumps(facts.digest(), ensure_ascii=False)}]
        resp = llm.chat(messages, build_tools())
        action = {"name": resp.get("name"), "args": resp.get("args", {})}

        gate = pre_tool_gate(action, facts)              # Sensor：硬阻断
        trace.append({"step": step, "action": action["name"], "gate": "pass" if gate.ok else gate.reason})
        if not gate.ok:
            continue                                     # 反馈进下一轮 messages

        if action["name"] == "finish":
            break

        obs = dispatch(action, df, facts)                # 结果进 FactStore
        trace.append({"step": step, "obs": obs})
    else:
        return None, facts, trace, f"{max_steps} 步未收敛，拒绝产出半成品"

    # 叙事层：真实系统在这里调 LLM 写文本；演示用带 fid 的固定文本
    narrative = spec.get("narrative", "")
    verdict = verify_report(narrative, facts, spec, df)
    if not verdict.passed:
        return None, facts, trace, fallback_to_template(spec, facts, str(verdict.failures))
    return narrative, facts, trace, None


# ---------- 场景 A：单指标问数 ----------
def scenario_ask(df):
    spec = {"sheets": [{"module": "overall_metrics",
                        "params": {"metrics": ["fpd30_rate"]}}]}
    llm = FakeLLM([{"name": "query_metric", "args": {"metric": "fpd30_rate"}},
                   {"name": "finish", "args": {}}])
    narrative, facts, trace, err = run_agent(spec, df, llm)
    fid = facts.digest()[0]["fid"]
    ans = "整体 FPD30 = {{" + fid + "}}（口径：" + SEMANTIC["fpd30_rate"]["desc"] + "）"
    return ans, facts, err


# ---------- 场景 B：报告批量化（固定 DAG + 叙事层） ----------
def scenario_report(df):
    spec = {"report_id": "FPD30_score1_月度",
            "sheets": [{"module": "overall_metrics",
                        "params": {"metrics": ["fpd30_rate", "ks", "auc"]}},
                       {"module": "by_dimension",
                        "params": {"dimension": "channel", "metrics": ["fpd30_rate"]}}],
            "narrative": "本月模型效果：整体 FPD30 为 {{F0001}}，KS 为 {{F0002}}，AUC 为 {{F0003}}。"}
    llm = FakeLLM([
        {"name": "query_metric", "args": {"metric": "fpd30_rate"}},
        {"name": "query_metric", "args": {"metric": "ks"}},
        {"name": "query_metric", "args": {"metric": "auc"}},
        {"name": "query_metric", "args": {"metric": "fpd30_rate", "group_by": "channel"}},
        {"name": "finish", "args": {}}])
    narrative, facts, trace, err = run_agent(spec, df, llm)
    return narrative, facts, err


# ---------- 场景 C：异常监控 + 归因下钻（ReAct 主战场） ----------
def scenario_monitor(df, threshold: float = 0.40):
    """规则检测（确定）+ 归因下钻（循环）+ 结论必须人工确认"""
    overall = compute_metric("fpd30_rate", df)["value"][0]
    if overall <= threshold:
        return f"FPD30 {overall:.4f} 未超阈值 {threshold}，无需告警"

    # 归因：按渠道下钻，找贡献最大的渠道（假设→验证→换假设的雏形）
    by_ch = compute_metric("fpd30_rate", df, "channel").sort_values("value", ascending=False)
    worst = by_ch.iloc[0]
    return (f"[告警] 整体 FPD30 {overall:.4f} 超阈值 {threshold}\n"
            f"  归因假设：{worst['dim']} 渠道异常（{worst['value']:.4f}，n={int(worst['n'])}）\n"
            f"  状态：待人工确认——归因结论未经 Owner 确认不得标记'已定位'")


# ============================================================
# M8 测试层：失败场景可复现（pytest 或直接运行均可）
# ============================================================
def test_unknown_metric_blocked():
    df, _ = load_snapshot(make_demo_data(), "demo", "mem://demo", "2026-09-30")
    llm = FakeLLM([{"name": "query_metric", "args": {"metric": "fpd99"}},
                   {"name": "finish", "args": {}}])
    spec = {"sheets": [{"module": "overall_metrics", "params": {"metrics": ["fpd30_rate"]}}]}
    _, facts, trace, _ = run_agent(spec, df, llm)
    assert any("未登记" in str(t.get("gate", "")) for t in trace), "未登记指标必须被前闸拦截"
    assert facts._facts == {}, "被拦截的调用不许留下任何事实"


def test_fabricated_ref_caught():
    df, _ = load_snapshot(make_demo_data(), "demo", "mem://demo", "2026-09-30")
    facts = FactStore()
    facts.put(0.35, "ratio", "fpd30_rate", "overall")
    spec = {"sheets": [{"module": "overall_metrics", "params": {"metrics": ["fpd30_rate"]}}]}
    verdict = verify_report("模型 KS 达到 {{F9999}}", facts, spec, df)
    assert not verdict.passed and any(f[0] == "fabricated_ref" for f in verdict.failures)


def test_bare_number_caught():
    df, _ = load_snapshot(make_demo_data(), "demo", "mem://demo", "2026-09-30")
    facts = FactStore()
    facts.put(0.35, "ratio", "fpd30_rate", "overall")
    spec = {"sheets": [{"module": "overall_metrics", "params": {"metrics": ["fpd30_rate"]}}]}
    verdict = verify_report("本月 FPD30 为 0.35，表现良好", facts, spec, df)
    assert not verdict.passed and any(f[0] == "bare_number" for f in verdict.failures)


def test_recompute_mismatch_caught():
    """流水线算错 vs 独立重算——检查 3 是最后一道，也是最要紧的一道"""
    df, _ = load_snapshot(make_demo_data(), "demo", "mem://demo", "2026-09-30")
    facts = FactStore()
    facts.put(0.99, "ratio", "fpd30_rate", "overall")     # 故意放一个错值
    spec = {"sheets": [{"module": "overall_metrics", "params": {"metrics": ["fpd30_rate"]}}]}
    verdict = verify_report("", facts, spec, df)
    assert not verdict.passed and any(f[0] == "render_mismatch" for f in verdict.failures)


def make_demo_data(n: int = 200) -> pd.DataFrame:
    return pd.DataFrame({
        "apply_id": [f"A{i:04d}" for i in range(n)],
        "channel":  pd.Series(["自然流量", "渠道A", "渠道B"] * 67).sample(n, random_state=7).values,
        "product":  pd.Series(["现金贷", "消费分期"] * 100).sample(n, random_state=7).values,
        "vintage":  pd.Series(["2026-07", "2026-08", "2026-09"] * 67).sample(n, random_state=7).values,
        "score":    pd.Series(range(500, 900)).sample(n, random_state=11).values.astype(float),
        "y":        pd.Series([0, 1, 0, 0, 1] * 40).sample(n, random_state=13).values,
    })


# ============================================================
# 演示主入口
# ============================================================
if __name__ == "__main__":
    df, manifest = load_snapshot(make_demo_data(), "model_sample", "mem://demo", "2026-09-30")
    print(f"[manifest] as_of={manifest.data_as_of} rows={manifest.rows} hash={manifest.data_hash}")

    print("\n── 场景 A：单指标问数 ──")
    ans, facts, err = scenario_ask(df)
    print(ans if not err else err)

    print("\n── 场景 B：模型报告（固定 DAG + 叙事层过三重闸） ──")
    narrative, facts, err = scenario_report(df)
    if err:
        print(err)
    else:
        resolved = FACT_REF.sub(lambda m: f"{facts.get(m.group(1)).value:.4f}", narrative)
        print(resolved)
        print(f"[facts manifest] {facts.manifest()}")

    print("\n── 场景 C：异常监控 + 归因下钻 ──")
    print(scenario_monitor(df, threshold=0.35))

    print("\n── M8 测试 ──")
    for fn in [test_unknown_metric_blocked, test_fabricated_ref_caught,
               test_bare_number_caught, test_recompute_mismatch_caught]:
        fn()
        print(f"  PASS {fn.__name__}")
    print("\n全部测试通过。")
