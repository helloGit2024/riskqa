# -*- coding: utf-8 -*-
"""存储层：SQLite 运营数据（schema + 六表 DAO）。

错误类型集中在这里，子模块只 import 不做二次定义。
"""

from __future__ import annotations


class StoreError(Exception):
    """存储层错误基类——所有存储异常都显式抛出，不吞掉（P-14）"""


class SchemaError(StoreError):
    """schema 缺失或与 data-model.md 不一致"""


class InvalidFactValueError(StoreError):
    """fact.value 非有限数（NaN/±Inf）——拒收，不写哨兵"""


class InvalidTransitionError(StoreError):
    """review_record 状态机不允许的推进"""


class ConcurrentTransitionError(StoreError):
    """状态推进时 WHERE state=旧值 未命中——并发冲突"""
