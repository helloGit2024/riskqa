"""快路 ask 链路（T-4.1.2）：四元组入参 + 前闸 + 纯函数计算 + 事实登记。

边界（不是遗漏，是分工）：
- 数值只由 `calc/` 纯函数产出，本模块不调用 LLM 算任何数（P-03）。
- 行级权限（P-10）**不在本模块**：这里不对 df 做任何权限过滤，
  由 T-4.1.4（SQL 三闸与行级权限）收口；缺口登记在 OPEN-QUESTIONS #33。
  `role` 参数仅用于前闸留痕与调用方上下文，**不做数据过滤**。
- 语义来源：`config/semantic_view.yaml`（P-15），代码不内嵌任何口径。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

from ..calc.metrics import METRIC_FUNCS, compute_metric
from ..facts.store import Fact, FactStore
from ..semantic.layer import SemanticLayer, UnregisteredMetricError, UnsignedMetricError

FACT_TABLE = "fact_application"

# 中文问法 → 语义维度；只在这些词出现时才收窄维度
_DIM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "channel": ("渠道", "channel"),
    "product": ("产品", "product"),
    "vintage": ("账龄", "月份", "vintage", "放款月"),
}

_FILTER_RE = re.compile(r"(渠道|产品)\s*([A-C]|P[12])|([A-C])\s*渠道|(P[12])\s*产品")
_PERIOD_RE = re.compile(r"(20\d{2})-(\d{2})")


class DimensionNotAllowedError(Exception):
    """维度/字段超出该指标或该表白名单——乱拆维度直接拒服（P-08）"""


class CalcNotRegisteredError(Exception):
    """指标声明的纯函数未注册——能命中不能算，快路拒服（P-09）"""


class NoFactError(Exception):
    """计算后没有任何事实——无事实禁出报告（P-06）"""


@dataclass(frozen=True)
class AskRequest:
    """快路四元组：指标 + 维度 + 过滤 + 时间范围"""

    metric: str
    dims: tuple[str, ...] = ()
    filters: Mapping[str, str] = field(default_factory=dict)
    time_range: tuple[str, str] | None = None


@dataclass(frozen=True)
class AskResult:
    metric: str
    group_by: str | None
    facts: tuple[Fact, ...]
    data_as_of: str
    ai_disclosure: bool = True  # P-16：所有出口带 AI 标识
    degraded: bool = False


def build_ask_metric_schema(sem: SemanticLayer) -> dict:
    """FC 工具 schema：enum 一律从语义层生成，禁止手写（P-08）"""
    return {
        "name": "ask_metric",
        "description": "按已签字口径查指标；只选参数，不写 SQL、不算数",
        "parameters": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "enum": sem.metric_enum},
                "dims": {"type": "array", "items": {"type": "string", "enum": sem.dim_enum}},
                "filters": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["metric"],
        },
    }


def parse_question(question: str, sem: SemanticLayer) -> AskRequest | None:
    """规则抽取器：命中指标才走快路；未命中返回 None（交给慢路）"""
    metric = sem.match_metric(question)
    if metric is None:
        return None
    allowed = tuple(sem.metrics[metric]["dims"])
    lowered = question.lower()
    dims = tuple(d for d in allowed if any(k in lowered for k in _DIM_KEYWORDS.get(d, ())))
    filters: dict[str, str] = {}
    for m in _FILTER_RE.finditer(question):
        if m.group(1):
            col = "channel" if m.group(1) == "渠道" else "product"
            val = m.group(2)
        elif m.group(3):
            col, val = "channel", m.group(3)
        else:
            col, val = "product", m.group(4)
        filters[col] = val
    period = _PERIOD_RE.search(question)
    time_range = (period.group(0), period.group(0)) if period else None
    return AskRequest(metric=metric, dims=dims, filters=filters, time_range=time_range)


def pre_tool_gate(req: AskRequest, sem: SemanticLayer) -> None:
    """前闸：四类拒服（P-04 未登记 / P-05 未签字 / P-08 乱维度 / P-09 未注册）"""
    meta = sem.metrics.get(req.metric)
    if meta is None:
        raise UnregisteredMetricError(f"指标 {req.metric!r} 未登记，已登记：{sem.metric_enum}")

    for field_name in ("owner", "signed_at", "changelog"):
        value = meta.get(field_name)
        # 与 semantic/check.py 一致：changelog 允许空列表，其余字段为空即未签字
        if not value and not (field_name == "changelog" and value == []):
            raise UnsignedMetricError(f"指标 {req.metric!r} 缺 {field_name}，拒绝服务")

    if req.dims:
        if len(req.dims) > 1:
            raise DimensionNotAllowedError(f"快路当前只支持单维度分组，收到 {list(req.dims)}")
        extra = set(req.dims) - set(meta["dims"])
        if extra:
            raise DimensionNotAllowedError(
                f"指标 {req.metric!r} 不支持维度 {sorted(extra)}，可选：{meta['dims']}"
            )

    columns = set(sem.tables.get(FACT_TABLE, {}).get("columns", []))
    extra_filters = set(req.filters) - columns
    if extra_filters:
        raise DimensionNotAllowedError(
            f"过滤字段 {sorted(extra_filters)} 不在表 {FACT_TABLE} 白名单"
        )

    if meta.get("calc") not in METRIC_FUNCS:
        raise CalcNotRegisteredError(
            f"指标 {req.metric!r} 的 calc={meta.get('calc')!r} 未注册纯函数（P-09）"
        )


def ask_fast(
    req: AskRequest,
    sem: SemanticLayer,
    df: pd.DataFrame,
    facts: FactStore,
    *,
    question: str = "",
    llm=None,
    obs=None,
    role: str = "analyst_qa",
) -> AskResult:
    """执行快路：前闸 → 纯函数计算 → FactStore。

    `role` 仅用于前闸留痕与调用方上下文，不做数据过滤；行权限在 T-4.1.4。
    """
    pre_tool_gate(req, sem)

    metric = req.metric
    group_by = req.dims[0] if req.dims else None
    if llm is not None:
        # 模型只选参数（P-03）：允许它覆盖指标/维度，但覆盖值必须再过一次前闸
        resp = llm.chat(
            "extraction",
            f"问题：{question}。可选指标 enum={sem.metric_enum}，"
            f"可选维度 enum={sem.dim_enum}。只选参数，不要算数。",
        )
        action = resp.get("action", resp)
        metric = action.get("metric", metric)
        chosen_dim = action.get("group_by")
        if chosen_dim is not None:
            group_by = chosen_dim
            req = AskRequest(
                metric=metric,
                dims=(chosen_dim,),
                filters=req.filters,
                time_range=req.time_range,
            )
        elif metric != req.metric:
            req = AskRequest(metric=metric, filters=req.filters, time_range=req.time_range)
        pre_tool_gate(req, sem)

    work = df
    for key, value in req.filters.items():
        work = work[work[key] == value]

    res = compute_metric(metric, work, group_by)
    unit = sem.metrics[metric]["unit"]
    collected: list[Fact] = []
    if group_by:
        for _, row in res.iterrows():
            value = float(row["value"])
            if math.isnan(value):
                continue
            fid = facts.put(
                value,
                unit,
                metric,
                segment=f"{group_by}={row[group_by]}",
                source="fast",
            )
            collected.append(facts.get(fid))
    else:
        value = float(res["value"].iloc[0])
        if not math.isnan(value):
            fid = facts.put(value, unit, metric, source="fast")
            collected.append(facts.get(fid))

    if not collected:
        raise NoFactError(f"指标 {metric!r} 计算后无可用事实，禁止出报告（P-06）")

    if obs is not None:
        obs.log("fast_fc", metric=metric, group_by=group_by, role=role)

    return AskResult(
        metric=metric,
        group_by=group_by,
        facts=tuple(collected),
        data_as_of=collected[-1].data_as_of,
    )
