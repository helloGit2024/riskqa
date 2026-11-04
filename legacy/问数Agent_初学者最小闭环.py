# -*- coding: utf-8 -*-
"""
问数 Agent · 初学者最小闭环
=================================================================
运行：python 问数Agent_初学者最小闭环.py
依赖：只用 pandas（无需数据库、无需 LLM API key）

这个文件要让你跑通并看懂四件事：
  ① 语义层   —— "指标名 → 怎么算" 的唯一登记处。指标口径只在这里定义一次。
  ② FC schema —— 工具的参数契约。注意 enum 是从语义层自动生成的，
                 所以模型只能"点名"已登记指标，不能发明指标。
  ③ 模型只选参数，不算数 —— 计算全部由 Python 完成，模型只负责
     "问 fpd30、按 channel 拆" 这个决策。
  ④ 主循环   —— 决策 → 校验 → 执行 → 带出处返回，四步。

真实系统与这个最小版的差距只有三处（都在《金融风控落地.py》里展开）：
  数据来自快照而非内存 DataFrame；指标用 YAML 外置 + Owner 签字；
  多一层校验闸（裸数字扫描 / 编造引用检测 / Python 重算比对）。
"""

import pandas as pd

# ============================================================
# 第 1 步：造一份演示数据（100 笔申请）
# ============================================================
# 真实系统里这一步由"数据快照 + manifest"代替，见落地版 L1。
def make_demo_data(n: int = 100) -> pd.DataFrame:
    return pd.DataFrame({
        "apply_id":    [f"A{i:04d}" for i in range(n)],
        "channel":     pd.Series(["自然流量", "渠道A", "渠道B"] * 34).sample(n, random_state=7).values,
        "product":     pd.Series(["现金贷", "消费分期"] * 50).sample(n, random_state=7).values,
        "score":       pd.Series(range(500, 900)).sample(n, random_state=11).values.astype(float),
        "y":           pd.Series([0, 1, 0, 0, 1] * 20).sample(n, random_state=13).values,  # 1=逾期(坏人)
        "passed":      pd.Series([1, 1, 0, 1] * 25).sample(n, random_state=17).values,     # 1=审批通过
    })

# ============================================================
# 第 2 步：语义层 —— 全文件最重要的 20 行
# ============================================================
# 每个指标登记四样东西：说什么（desc）、怎么算（expr）、单位（unit）、
# 能按什么拆（dims）。团队口径争议的终点就是这张表——它取代了
# "散落在 30 个老脚本里的计算公式"。
#
# 注意 expr 是 df -> Series 的纯函数：给一行样本算一个值，
# 聚合（mean）由 compute() 统一做，指标作者不关心怎么分组。
SEMANTIC = {
    "fpd30": {
        "desc": "首期逾期率（放款客户中首期 DPD30+ 的占比）",
        "unit": "%",
        "expr": lambda d: d["y"],               # 演示简化：真实场景 y 由清洗层从逾期日期算出
        "dims": ["channel", "product"],
    },
    "pass_rate": {
        "desc": "审批通过率",
        "unit": "%",
        "expr": lambda d: d["passed"],
        "dims": ["channel", "product"],
    },
    "avg_score": {
        "desc": "平均信用分",
        "unit": "分",
        "expr": lambda d: d["score"],
        "dims": ["channel", "product"],
    },
}

# ============================================================
# 第 3 步：FC schema —— 工具参数契约，enum 从语义层生成
# ============================================================
# 这是"不许发明指标"的第一道闸：模型能填的 metric 值，
# 只有语义层里登记过的那几个。新增指标只需改 SEMANTIC，
# 工具 schema 自动跟上，不用动这里。
def build_tool_schema() -> dict:
    return {
        "name": "query_metric",
        "description": "查询一个已登记的风控指标。只返回数值，不返回解释。",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": sorted(SEMANTIC),      # ← 关键：单一事实源
                    "description": "指标名，必须是已登记指标",
                },
                "group_by": {
                    "type": "string",
                    "enum": sorted({d for s in SEMANTIC.values() for d in s["dims"]}),
                    "description": "按哪个维度拆解，不传则算整体",
                },
            },
            "required": ["metric"],
        },
    }

# ============================================================
# 第 4 步：计算层 —— 纯 Python，模型禁入
# ============================================================
def compute(metric: str, df: pd.DataFrame, group_by: str = None) -> pd.DataFrame:
    spec = SEMANTIC[metric]                      # 未登记指标在这里 KeyError，
    vals = spec["expr"](df)                      # 语义层 expr 算每行的值
    if group_by is None:
        return pd.DataFrame({"value": [vals.mean()], "n": [len(vals)]})
    g = pd.DataFrame({"dim": df[group_by], "value": vals})
    return g.groupby("dim")["value"].agg(["mean", "count"]).reset_index()

# ============================================================
# 第 5 步：FakeLLM —— 按脚本"表演"模型决策
# ============================================================
# 真实模型在这里读 input_schema，然后决定 metric / group_by 填什么。
# 换成 FakeLLM 是为了让你不花一分钱 API 费用、不受网络影响，
# 就能反复观察"决策 → 校验 → 执行"这条链路。
class FakeLLM:
    def __init__(self, script: list):
        self._script = list(script)
        self.calls = 0

    def chat(self, messages, tools, **kw) -> dict:
        self.calls += 1
        # 真模型此刻在"读" tools 参数；我们直接弹出预编动作
        if self._script:
            return self._script.pop(0)
        return {"type": "finish"}

# ============================================================
# 第 6 步：主循环 —— 四步：决策 → 校验 → 执行 → 带出处返回
# ============================================================
def ask(question: str, df: pd.DataFrame, llm) -> str:
    schema = build_tool_schema()

    # ① 决策：模型看 schema，决定调 query_metric 并填参数
    resp = llm.chat(messages=[{"role": "user", "content": question}],
                    tools=[schema])
    if resp.get("type") != "tool_call":
        return f"[{question}] 模型未调用工具"

    args = resp["args"]
    metric, group_by = args["metric"], args.get("group_by")

    # ② 校验：指标与维度必须在登记处（真实世界由 API 服务端强制，
    #    这里显式写出来让你看见闸门长什么样）
    if metric not in SEMANTIC:
        return f"[闸门拦截] 指标 {metric!r} 未登记，已登记：{sorted(SEMANTIC)}"
    if group_by is not None and group_by not in SEMANTIC[metric]["dims"]:
        return f"[闸门拦截] 维度 {group_by!r} 不允许用于 {metric}"

    # ③ 执行：Python 算数，模型不碰
    result = compute(metric, df, group_by)

    # ④ 带出处返回：口径来自哪，永远印在答案旁边
    head = f"Q: {question}\n口径: {SEMANTIC[metric]['desc']}（单位 {SEMANTIC[metric]['unit']}）\n"
    if group_by is None:
        return head + f"整体: {result['value'][0]:.4f}（n={result['n'][0]}）"
    lines = [f"  {row['dim']}: {row['mean']:.4f}（n={int(row['count'])}）"
             for _, row in result.iterrows()]
    return head + f"按 {group_by} 拆解:\n" + "\n".join(lines)


# ============================================================
# 演示：三个正常问题 + 一个失败场景
# ============================================================
if __name__ == "__main__":
    df = make_demo_data()

    print("=" * 62)
    print("场景 1：按渠道拆 FPD30（模型选指标 + 选维度）")
    print("=" * 62)
    llm = FakeLLM([{"type": "tool_call",
                    "args": {"metric": "fpd30", "group_by": "channel"}}])
    print(ask("各渠道的首期逾期率分别是多少", df, llm))

    print("\n" + "=" * 62)
    print("场景 2：整体通过率（模型不传 group_by）")
    print("=" * 62)
    llm = FakeLLM([{"type": "tool_call", "args": {"metric": "pass_rate"}}])
    print(ask("整体审批通过率是多少", df, llm))

    print("\n" + "=" * 62)
    print("场景 3：失败复现——模型'发明'了一个不存在的指标")
    print("=" * 62)
    llm = FakeLLM([{"type": "tool_call", "args": {"metric": "fpd99"}}])
    print(ask("帮我看看 fpd99", df, llm))

    print("\n" + "=" * 62)
    print("场景 4：失败复现——模型把 fpd30 按未登记的维度拆")
    print("=" * 62)
    llm = FakeLLM([{"type": "tool_call",
                    "args": {"metric": "fpd30", "group_by": "score"}}])
    print(ask("按分数段看看 fpd30", df, llm))

    print("\n" + "-" * 62)
    print("下一步：把 SEMANTIC 外置成 YAML、给指标加 Owner 签字、")
    print("数据换成快照+manifest，就是《问数Agent_金融风控落地.py》。")
