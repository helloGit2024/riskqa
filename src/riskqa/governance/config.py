# -*- coding: utf-8 -*-
"""治理配置：三层（全局/域覆盖/临时）+ 护栏校验（V3 版）。"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import yaml


@dataclass(frozen=True)
class PromotionRule:
    min_users: int
    min_queries: int
    min_days: int
    max_top_user_share: float
    max_active_days_gap: int


@dataclass(frozen=True)
class ReviewRule:
    sla_hours: int
    escalate_after_sla: int
    shelve_after_sla: int


@dataclass(frozen=True)
class GovernanceConfig:
    promotion: PromotionRule
    window_days: int
    retention_days: int
    review: ReviewRule

    def for_domain(self, domain: str, overrides: dict) -> PromotionRule:
        """第二层：主题域覆盖。返回该域生效的晋升规则"""
        ov = (overrides or {}).get(domain, {}).get("promotion")
        if not ov:
            return self.promotion
        merged = {**asdict(self.promotion), **ov}
        return PromotionRule(**merged)

    def apply_temporary(self, temporary: list[dict], today: str) -> "GovernanceConfig":
        """第三层：未过期的临时调整叠加生效；过期忽略"""
        import dataclasses
        cfg = self
        for t in temporary or []:
            if t.get("expires", "9999") >= today:
                cfg = dataclasses.replace(
                    cfg,
                    promotion=dataclasses.replace(
                        cfg.promotion,
                        **{t["param"].split(".")[-1]: t["value"]}))
        return cfg


def validate_governance(cfg: GovernanceConfig) -> list[str]:
    """护栏：非法配置拒绝加载，保持上一版，不让系统带病运行"""
    errs: list[str] = []
    p = cfg.promotion
    if p.min_users < 1:
        errs.append("min_users < 1：任何查询都能晋升，机制形同虚设")
    if p.min_queries < p.min_users:
        errs.append("min_queries < min_users：阈值自相矛盾")
    if p.min_days < 1:
        errs.append("min_days < 1：允许单日集中刷量晋升")
    if not 0.5 < p.max_top_user_share <= 1.0:
        errs.append("max_top_user_share 必须落在 (0.5, 1.0]")
    if cfg.window_days > cfg.retention_days:
        errs.append("热度窗口 > 保留期限：窗口内数据已被删除，热度永远算不出")
    if cfg.review.sla_hours < 24:
        errs.append("SLA < 24h：会把 Owner 变成瓶颈，评审队列必堆积")
    return errs


def load_governance(yaml_text: str, today: str = "2026-10-30") -> GovernanceConfig:
    raw = yaml.safe_load(yaml_text)
    g = raw["global"]
    cfg = GovernanceConfig(
        promotion=PromotionRule(**g["promotion"]),
        window_days=g["window_days"],
        retention_days=g["retention_days"],
        review=ReviewRule(**g["review"]))
    errs = validate_governance(cfg)
    if errs:
        raise GovernanceError("治理配置未过护栏，拒绝加载：" + "；".join(errs))
    return cfg.apply_temporary(raw.get("temporary"), today)


class GovernanceError(Exception):
    """治理配置非法——护栏拒绝"""
