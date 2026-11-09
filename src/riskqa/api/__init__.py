"""REST API v1（T-4.1.5）：协议出口层。

边界：
- 只做协议转换、身份识别与错误码映射，不产出任何数字（P-03）。
- 口径来自 `config/semantic_view.yaml`，本包不内嵌默认值（P-15）。
- 身份只来自 `X-RiskQA-Token`，任何端点不接受 body 自报身份（P-10）。
"""
