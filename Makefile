# Makefile · 风控问数系统

# 纪律：本文件分两类 target——
#   【立即可用】今天就能跑（docs-check / openq / env-check）
#   【V4.0 启用】随 tasks.md T-4.0.7 落地并当天实跑后生效；未建成时给出明确指路，不静默失败
# 参数透传用变量：make test T="-k permission"（make 会吞 -k，anti-patterns：rag-kb 实测）

.PHONY: help docs-check openq env-check test lint secret-scan health run api mcp eval semantic-check governance-check check bootstrap

PY := python3
SCRIPTS := scripts

# 若仓库内 .venv 存在则优先使用（含项目依赖 pyyaml/pandas/numpy），
# 否则退回系统 python3（此时部分“立即可用” target 会按设计指路到 T-4.0.5）。
# 首次使用请先跑 `make bootstrap` 创建 .venv。
ifeq ($(wildcard .venv/bin/python),)
PY := python3
else
PY := .venv/bin/python
endif

help:
	@echo "【立即可用】"
	@echo "make docs-check   - 文档自检（validate_docs.py）"
	@echo "make openq        - 汇总待确认项（collect_open_questions.py）"
	@echo "make env-check    - 检查 Python 依赖可导入"
	@echo "【V4.0 启用】"
	@echo "make test         - pytest 全量（V2 九场景 + V3 八场景 + 单元）"
	@echo "make lint         - ruff check + format --check"
	@echo "make secret-scan  - 密钥/敏感信息扫描（QG-04，P-01）"
	@echo "make health       - 服务健康检查（API /health，恢复后用）"
	@echo "make run          - 启动 API 服务（127.0.0.1:8080）"
	@echo "make api          - 同 run"
	@echo "make mcp          - 启动 MCP Server（stdio）"
	@echo "make eval         - 跑黄金题集（evals/golden_set.yaml）"
	@echo "make semantic-check - 语义层/治理 YAML 校验（三字段+护栏）"
	@echo "make governance-check - 同 semantic-check 的治理部分"
	@echo "make check        - 提交前一条（= lint + test + semantic-check + secret-scan）"
	@echo "make bootstrap    - 创建 .venv 并安装基础依赖（首次使用）"

# ---------- 环境引导 ----------
bootstrap:
	@echo "创建 .venv 并安装基础依赖（pyyaml / pandas / numpy）"
	python3 -m venv .venv
	.venv/bin/python -m pip install -U pip
	.venv/bin/python -m pip install pyyaml pandas numpy
	@echo "完成。之后 make 会自动优先使用 .venv/bin/python"

# ---------- 【立即可用】 ----------
docs-check:
	$(PY) $(SCRIPTS)/validate_docs.py .

openq:
	$(PY) $(SCRIPTS)/collect_open_questions.py .

env-check:
	@$(PY) -c "import pandas, numpy, yaml; print('core deps OK')" \
	  || (echo "缺少依赖：pip install -r requirements.txt（T-4.0.5）"; exit 1)

# ---------- 【V4.0 启用】 ----------
test:
	@test -d tests || (echo "tests/ 未建成——见 tasks.md T-4.0.6"; exit 1)
	$(PY) -m pytest tests/ -q $(T)

lint:
	@test -f requirements.txt || (echo "requirements.txt 未建成——见 T-4.0.5"; exit 1)
	$(PY) -m ruff check src/ tests/ && $(PY) -m ruff format --check src/ tests/

secret-scan:
	@test -d src || (echo "src/ 未建成——见 tasks.md T-4.0.1"; exit 1)
	@if grep -rnE "(api[_-]?key|secret|token|password|passwd| AKLT|AKIA)[[:space:]]*[:=][[:space:]]*['\"][^'\"]{8,}" src/ tests/ evals/ --include="*.py" --include="*.yaml"; then \
	  echo "↑ 疑似密钥/连接串命中——见 AGENTS.md P-01，一票否决"; exit 1; \
	else echo "secret-scan: 0 命中"; fi

health:
	@test -d src/riskqa/api || (echo "API 未建成——见 tasks.md T-4.1.5"; exit 1)
	@curl -fsS http://127.0.0.1:8080/health || (echo "服务未响应——见 docs/ops-runbook.md A1"; exit 1)

run:
	@test -d src/riskqa/api || (echo "API 未建成——见 tasks.md T-4.1.5"; exit 1)
	$(PY) -m uvicorn riskqa.api.app:app --host 127.0.0.1 --port 8080

api: run
	@true

mcp:
	@test -d src/riskqa/mcp || (echo "MCP 未建成——见 tasks.md T-4.2.6"; exit 1)
	$(PY) -m riskqa.mcp.server

eval:
	@test -f evals/golden_set.yaml || (echo "题库未就绪"; exit 1)
	@test -d tests || (echo "评估 runner 未建成——见 tasks.md T-4.1.8"; exit 1)
	$(PY) -m riskqa.orchestration.eval_runner --golden evals/golden_set.yaml

semantic-check:
	@test -f config/semantic_view.yaml || (echo "语义层未外置——见 tasks.md T-4.0.2"; exit 1)
	$(PY) -m riskqa.semantic.check config/semantic_view.yaml

governance-check:
	@test -f config/governance.yaml || (echo "治理配置未外置——见 T-4.0.2"; exit 1)
	$(PY) -m riskqa.governance.check config/governance.yaml

check: lint test semantic-check secret-scan
	@echo "check 通过"
