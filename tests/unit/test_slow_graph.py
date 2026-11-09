"""慢路固定图单测（T-4.1.3）：60s 熔断、修正 ≤2 轮、人审分级。

全部用 FakeLLM + 假时钟驱动，不 sleep、不接真模型（P-17）。
"""

from __future__ import annotations

import pytest

from riskqa.llm.fake import FakeLLM
from riskqa.orchestration.graph_qa import build_qa_graph

SLOW_Q = "各渠道平均逾期水平如何"  # 不命中语义层 → 慢路
GOOD_SQL = (
    "SELECT channel, AVG(is_fpd30) FROM fact_application "
    "WHERE is_pass = 1 GROUP BY channel LIMIT 10"
)
BAD_SQL = "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel"
# 分母错（漏 is_pass=1）→ 与快路口径不一致
WRONG_DENOM_SQL = "SELECT channel, AVG(is_fpd30) FROM fact_application GROUP BY channel LIMIT 10"
# 无 GROUP BY 的整体口径：用于验证交叉验证用的是"行权限可见 df"
OVERALL_SQL = "SELECT channel, AVG(is_fpd30) FROM fact_application WHERE is_pass = 1 LIMIT 10"

ANALYST_FPD30 = 0.22391857506361323
WRONG_FPD30 = 0.1461794019933555


class FakeClock:
    """可注入的单调时钟：测试推进时间，不真实等待。"""

    def __init__(self, start: float = 1000.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


class ClockLLM(FakeLLM):
    """在指定任务返回后推进时钟，模拟该阶段耗时。"""

    def __init__(self, script, clock, advance_task="drill", advance_s=61.0):
        super().__init__(script=script)
        self.clock = clock
        self.advance_task = advance_task
        self.advance_s = advance_s

    def chat(self, task: str, prompt: str, **kw) -> dict:
        out = super().chat(task, prompt, **kw)
        if task == self.advance_task:
            self.clock.advance(self.advance_s)
        return out


def _run(semantic, demo_df, facts, observer, spec, llm, **kwargs):
    role = kwargs.pop("role", "analyst_qa")
    graph = build_qa_graph(semantic, demo_df, facts, llm, observer, spec, role=role, **kwargs)
    return graph.invoke(
        {"question": SLOW_Q, "role": role},
        config={"configurable": {"thread_id": "slow-graph"}},
    )


def test_slow_timeout_fires_at_60s(semantic, demo_df, facts, observer, spec):
    """SQL 生成阶段耗时超过 60s → 熔断拒交付，失败码为 ("timeout", 60)。"""
    clock = FakeClock()
    llm = ClockLLM([{"tables": ["fact_application"]}, {"sql": GOOD_SQL}], clock)

    out = _run(semantic, demo_df, facts, observer, spec, llm, now=clock)

    assert out["route"] == "slow"
    assert out["result"]["passed"] is False
    assert out["result"]["failures"] == [("timeout", 60)]
    assert "熔断" in out["narrative"]
    assert out["trace"][-1] == "fail(timeout)"
    assert facts.digest() == []  # 超时不算数，事实不落库


def test_slow_within_budget_passes(semantic, demo_df, facts, observer, spec, fake_llm):
    """时钟不推进 → 正常收敛，不误伤。"""
    clock = FakeClock()
    llm = fake_llm(
        [
            {"tables": ["fact_application"]},
            {"sql": GOOD_SQL},
            {"text": "各渠道逾期见 {{F0001}}。"},
        ]
    )

    out = _run(semantic, demo_df, facts, observer, spec, llm, now=clock)

    assert out["result"]["passed"] is True
    assert out["corrections"] == 0
    assert out["steps"] == 1


def test_slow_stops_after_two_corrections(semantic, demo_df, facts, observer, spec, fake_llm):
    """连续被驳回：1 次首生成 + 2 次修正后停手，修正轮次恰好 2。"""
    llm = fake_llm([{"tables": ["fact_application"]}] + [{"sql": BAD_SQL}] * 3)

    out = _run(semantic, demo_df, facts, observer, spec, llm, max_steps=3)

    assert out["result"]["failures"] == [("step_limit", 3)]
    assert out["corrections"] == 2
    assert out["steps"] == 3
    checks = [t for t in observer.trace if t["node"] == "slow_sql_check"]
    assert len(checks) == 3
    assert all(t["ok"] is False for t in checks)
    assert out["narrative"] == "[失败] 慢路未在步数上限内收敛，拒绝交付半成品"


def test_slow_first_shot_zero_corrections(semantic, demo_df, facts, observer, spec, fake_llm):
    """首轮合规不计修正。"""
    llm = fake_llm(
        [
            {"tables": ["fact_application"]},
            {"sql": GOOD_SQL},
            {"text": "见 {{F0001}}。"},
        ]
    )

    out = _run(semantic, demo_df, facts, observer, spec, llm)

    assert out["corrections"] == 0
    assert out["steps"] == 1


def test_slow_review_uses_state_role(semantic, demo_df, facts, observer, spec, fake_llm):
    """分级与行权限同源：角色取 state，不用 builder 闭包默认值。

    builder 默认 analyst_qa，invoke 传 risk_admin：若仍用闭包角色会判 sample，
    正确实现应判 auto 且审计 actor=risk_admin。
    """
    llm = fake_llm(
        [
            {"tables": ["fact_application"]},
            {"sql": GOOD_SQL},
            {"text": "见 {{F0001}}。"},
        ]
    )
    graph = build_qa_graph(semantic, demo_df, facts, llm, observer, spec, role="analyst_qa")
    out = graph.invoke(
        {"question": SLOW_Q, "role": "risk_admin"},
        config={"configurable": {"thread_id": "slow-role"}},
    )

    assert out.get("__interrupt__") is None
    entry = [a for a in observer.audit if a.route == "slow"][-1]
    assert entry.actor == "risk_admin"
    assert entry.review_level == "auto"
    assert entry.human_action == "auto"


def test_slow_cross_check_returns_both_sides(semantic, demo_df, facts, observer, spec, fake_llm):
    """交叉验证不一致：双侧数字并列拒交付，不平均、不落 FactStore。"""
    llm = fake_llm([{"tables": ["fact_application"]}, {"sql": WRONG_DENOM_SQL}])

    out = _run(semantic, demo_df, facts, observer, spec, llm)

    assert out["result"]["passed"] is False
    kind, label, slow, recomputed = out["result"]["failures"][0]
    assert kind == "cross_check"
    assert label == "fpd30_rate@channel=A"
    assert slow == pytest.approx(WRONG_FPD30, rel=1e-6)
    assert recomputed == pytest.approx(ANALYST_FPD30, rel=1e-6)
    # 叙事把两侧数字原样并列，且没有任何平均值
    assert str(slow) in out["narrative"]
    assert str(recomputed) in out["narrative"]
    assert str((slow + recomputed) / 2) not in out["narrative"]
    assert "不做平均" in out["narrative"]
    assert facts.digest() == []  # 不一致的结果绝不落库
    assert out["trace"][-1] == "cross_fail"


def test_slow_cross_check_consistent_commits(semantic, demo_df, facts, observer, spec, fake_llm):
    """交叉验证一致：通过后才写 FactStore，事实段与慢路一致。"""
    llm = fake_llm(
        [
            {"tables": ["fact_application"]},
            {"sql": GOOD_SQL},
            {"text": "各渠道逾期见 {{F0001}}。"},
        ]
    )

    out = _run(semantic, demo_df, facts, observer, spec, llm)

    assert out["result"]["passed"] is True
    assert len(facts.digest()) == 1  # analyst 行权限下仅 A 渠道
    assert out["facts"][0]["segment"] == "channel=A"
    assert out["facts"][0]["value"] == pytest.approx(ANALYST_FPD30, rel=1e-6)
    assert out["cross_check"]["ok"] is True


def test_slow_cross_check_uses_visible_df(semantic, demo_df, facts, observer, spec, fake_llm):
    """反证：重算必须用行权限收窄后的可见 df。

    analyst 的"整体"口径实际只覆盖 A 渠道（0.2239）。若用全量 df 重算会得到
    0.2859，与本用例期望的 passed=True 直接冲突——防止 T-4.1.4 那类越权/口径
    混用问题在交叉验证里复发。
    """
    llm = fake_llm(
        [
            {"tables": ["fact_application"]},
            {"sql": OVERALL_SQL},
            {"text": "整体逾期见 {{F0001}}。"},
        ]
    )

    out = _run(semantic, demo_df, facts, observer, spec, llm)

    assert out["result"]["passed"] is True
    item = out["cross_check"]["items"][0]
    assert item["label"] == "fpd30_rate@overall"
    assert item["recomputed"] == pytest.approx(ANALYST_FPD30, rel=1e-6)
    assert out["facts"][0]["value"] == pytest.approx(ANALYST_FPD30, rel=1e-6)


def test_slow_degraded_sql_skips_cross_check(semantic, demo_df, facts, observer, spec, fake_llm):
    """演示执行器不支持的 SQL 形态：跳过交叉验证，由校验闸抓编造引用（v2_3 同路径）。"""
    llm = fake_llm(
        [
            {"tables": ["fact_application"]},
            # MEDIAN 不在演示执行器支持范围，触发优雅降级（不是 must 级，不中断）
            {
                "sql": "SELECT channel, MEDIAN(is_fpd30) FROM fact_application "
                "WHERE is_pass = 1 LIMIT 10"
            },
            {"text": "跨表查询完成，见 {{F0001}}。"},
        ]
    )

    out = _run(semantic, demo_df, facts, observer, spec, llm)

    assert out["result"]["passed"] is False
    assert out["result"]["failures"][0][0] == "fabricated_ref"
    assert facts.digest() == []
    assert any("slow_cross_check(skipped)" == t for t in out["trace"])
