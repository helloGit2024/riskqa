"""缺失值归一化单测（OPEN-QUESTIONS #12：固化当前金融版实现与 V2 的差异）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from riskqa.data.snapshot import normalize_missing


def test_object_column_normalizes_all_tokens():
    df = pd.DataFrame(
        {
            "text": ["", "unknown", "Unknown", "ok", -999],
            "num": [1, 2, 3, 4, -999],
        }
    )
    out = normalize_missing(df)
    assert out["text"].isna().tolist() == [True, True, True, False, True]
    assert out["num"].isna().tolist() == [False, False, False, False, True]
    assert len(out) == len(df)


def test_string_dtype_normalizes_empty_and_unknown():
    df = pd.DataFrame({"text": pd.Series(["", "unknown", "Unknown", "ok"], dtype="string")})
    out = normalize_missing(df)
    assert out["text"].isna().tolist() == [True, True, True, False]


def test_capitalized_unknown_is_normalized_unlike_v2():
    """迁移差异：V2 只替换 ``["", "unknown", -999]``，不会处理 ``"Unknown"``。

    当前实现取金融版（额外替换 ``"Unknown"``），本测试固化该行为；
    不是放宽标准，差异记录在 OPEN-QUESTIONS #12。
    """
    df = pd.DataFrame({"text": pd.Series(["Unknown", "not unknown"], dtype=object)})
    out = normalize_missing(df)
    assert np.isnan(out.loc[0, "text"])
    assert out.loc[1, "text"] == "not unknown"
