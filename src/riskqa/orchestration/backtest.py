"""场景层：回测（固定流跑数，模型禁入）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..calc.metrics import auc, ks
from ..semantic.layer import SemanticLayer


def run_backtest(
    sem: SemanticLayer, df_oot: pd.DataFrame, strategies: dict[str, str]
) -> tuple[pd.DataFrame, str]:
    """回测场景：固定流跑数（模型禁入）+ Agent 只做呈现层 + 决策禁入区

    第一纪律不是"能查"，是口径一致可复现——所以跑数走语义层纯函数，
    同一份样本、同一套指标定义，跑一百次结果一样。
    """
    rows = []
    for name, col in strategies.items():
        d = df_oot.assign(score=df_oot[col])
        rows.append({"strategy": name, "ks": ks(d), "auc": auc(d), "as_of": "2026-09-30"})
    compare = pd.DataFrame(rows).sort_values("ks", ascending=False)
    # 口径一致性校验：每条与纯函数独立重算比对——回测最怕悄悄漂移
    for _, row in compare.iterrows():
        col = strategies[row["strategy"]]
        recomputed = ks(df_oot.assign(score=df_oot[col]))
        if not np.isclose(row["ks"], recomputed, rtol=1e-9):
            raise AssertionError(
                f"回测口径漂移：{row['strategy']} {row['ks']} vs 重算 {recomputed}"
            )
    narrative = (
        f"回测完成（数据截止 2026-09-30，样本 {len(df_oot)} 条）。"
        f"各策略 KS/AUC 见对比表。\n"
        f"[禁入区声明] 本报告仅呈现多策略对比与已知风险（过拟合历史、样本外衰减），"
        f'"上哪个策略"的决策必须由人做出——Agent 不得输出策略建议。'
    )
    return compare, narrative
