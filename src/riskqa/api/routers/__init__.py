"""API 路由包：按契约路径分组，一组一个文件。"""

from __future__ import annotations

from . import ask, evidence, governance, ops, review

__all__ = ["ask", "evidence", "governance", "ops", "review"]
