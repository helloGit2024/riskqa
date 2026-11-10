# Makefile · 风控问数系统

# 纪律：本文件分两类 target——
#   【立即可用】今天就能跑（docs-check / openq / env-check）
#   【V4.0 启用】随 tasks.md T-4.0.7 落地并当天实跑后生效；未建成时给出明确指路，不静默失败
# 参数透传用变量：make test T="-k permission"（make 会吞 -k，anti-patterns：rag-kb 实测）

.PHONY: help docs-check openq env-check test lint format-check secret-scan health run api mcp eval semantic-check governance-check check bootstrap python-guard ci demo-snapshot

SCRIPTS := scripts
PYTHON ?=

# 解释器优先级：显式 PYTHON → .venv/bin/python → python3.13 → 版本合格的 python3。
# 不用系统 python3 的默认版本猜环境（本机曾为 3.8.5）；缺失时由 python-guard 显式报错。
ifeq ($(strip $(PYTHON)),)
PY := $(shell \
	if [ -x .venv/bin/python ]; then \
		echo .venv/bin/python; \
	elif command -v python3.13 >/dev/null 2>&1; then \
		echo python3.13; \
	elif python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 13) else 1)' >/dev/null 2>&1; then \
		echo python3; \
	else \
		echo __missing__; \
	fi)
else
PY := $(PYTHON)
endif

# bootstrap 不能复用待创建的 .venv；只从 PYTHON / python3.13 / 合格 python3 中选。
BOOT_PY := $(if $(strip $(PYTHON)),$(PYTHON),$(shell \
	if command -v python3.13 >/dev/null 2>&1; then \
		echo python3.13; \
	elif python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 13) else 1)' >/dev/null 2>&1; then \
		echo python3; \
	else \
		echo __missing__; \
	fi))

help:
	@echo "【立即可用】"
	@echo "make docs-check   - 文档自检（validate_docs.py）"
	@echo "make openq        - 汇总待确认项（collect_open_questions.py）"
	@echo "make env-check    - 检查 Python 版本与依赖可导入"
	@echo "【V4.0 启用】"
	@echo "make test         - pytest 全量（V2 九场景 + V3 八场景 + 单元）"
	@echo "make lint         - ruff check + format --check"
	@echo "make format-check - ruff format --check"
	@echo "make secret-scan  - 密钥/敏感信息扫描（QG-04，P-01）"
	@echo "make health       - 服务健康检查（API /api/v1/health，接受 200/503）"
	@echo "make run          - 启动 API 服务（127.0.0.1:8080）"
	@echo "make demo-snapshot - 现场生成 demo 快照（合成数据，synthetic=true，不提交）"
	@echo "make api          - 同 run"
	@echo "make mcp          - 启动 MCP Server（stdio）"
	@echo "make eval         - 跑黄金题集（evals/golden_set.yaml）"
	@echo "make semantic-check - 语义层/治理 YAML 校验（三字段+护栏）"
	@echo "make governance-check - 同 semantic-check 的治理部分"
	@echo "make check        - 提交前一条（= lint + test + semantic-check + secret-scan）"
	@echo "make ci           - CI 全量门禁（快闸先、慢闸后）"
	@echo "make bootstrap    - 创建 .venv 并安装锁定依赖（首次使用）"

# ---------- 环境引导 ----------
python-guard:
	@if [ "$(PY)" = "__missing__" ]; then \
		echo "需要 Python 3.13，或先 make bootstrap"; exit 2; \
	fi
	@$(PY) -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 13) else 1)' \
		|| (echo "需要 Python 3.13，或先 make bootstrap"; exit 2)

bootstrap:
	@if [ "$(BOOT_PY)" = "__missing__" ]; then \
		echo "需要 Python 3.13：请安装 python3.13，或用 PYTHON=/path/to/python3.13 指定"; exit 2; \
	fi
	$(BOOT_PY) -m venv .venv
	.venv/bin/python -m pip install -U pip
	.venv/bin/python -m pip install -r requirements.lock.txt
	@echo "完成。之后 make 会自动优先使用 .venv/bin/python"

# ---------- 【立即可用】 ----------
docs-check: python-guard
	$(PY) $(SCRIPTS)/validate_docs.py .

openq: python-guard
	$(PY) $(SCRIPTS)/collect_open_questions.py .

env-check: python-guard
	@$(PY) -c "import sys; print(f'Python {sys.version.split()[0]}')"
	@$(PY) -c "import pandas, numpy, yaml; print('core deps OK')" \
		|| (echo "缺少依赖：$(PY) -m pip install -r requirements.lock.txt"; exit 1)

# ---------- 【V4.0 启用】 ----------
test: python-guard
	@test -d tests || (echo "tests/ 未建成——见 tasks.md T-4.0.6"; exit 1)
	$(PY) -m pytest tests/ -q $(T)

lint: python-guard
	@test -f requirements.txt || (echo "requirements.txt 未建成——见 T-4.0.5"; exit 1)
	$(PY) -m ruff check src/ tests/
	$(PY) -m ruff format --check src/ tests/

format-check: python-guard
	$(PY) -m ruff format --check src/ tests/

secret-scan:
	@if git grep -nE "(api[_-]?key|secret|token|password|passwd| AKLT|AKIA)[[:space:]]*[:=][[:space:]]*['\"][^'\"]{8,}"; then \
		echo "↑ 疑似密钥/连接串命中——见 AGENTS.md P-01，一票否决"; exit 1; \
	else \
		status=$$?; \
		if [ $$status -eq 1 ]; then \
			echo "secret-scan: 0 命中"; \
		else \
			echo "secret-scan: git grep 执行失败"; exit $$status; \
		fi; \
	fi

health:
	@test -d src/riskqa/api || (echo "API 未建成——见 tasks.md T-4.1.5"; exit 1)
	@code=$$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/v1/health || true); \
	if [ "$$code" = "200" ] || [ "$$code" = "503" ]; then \
		echo "health: HTTP $$code（503 = degraded，三态见响应体；V4.1 无真 LLM，属预期）"; \
	else \
		echo "服务未响应（HTTP $$code）——见 docs/ops-runbook.md A1"; exit 1; \
	fi

run:
	@test -d src/riskqa/api || (echo "API 未建成——见 tasks.md T-4.1.5"; exit 1)
	$(PY) -m uvicorn riskqa.api.app:app --host 127.0.0.1 --port 8080

demo-snapshot: python-guard
	@test -d data/snapshots || (echo "data/snapshots/ 不存在——见 REPO_CONVENTION.md §三"; exit 1)
	$(PY) $(SCRIPTS)/make_demo_snapshot.py

api: run
	@true

mcp:
	@test -d src/riskqa/mcp || (echo "MCP 未建成——见 tasks.md T-4.2.6"; exit 1)
	$(PY) -m riskqa.mcp.server

eval:
	@test -f evals/golden_set.yaml || (echo "题库未就绪"; exit 1)
	@test -d tests || (echo "评估 runner 未建成——见 tasks.md T-4.1.8"; exit 1)
	$(PY) -m riskqa.orchestration.eval_runner --golden evals/golden_set.yaml

semantic-check: python-guard
	@test -f config/semantic_view.yaml || (echo "语义层未外置——见 tasks.md T-4.0.2"; exit 1)
	PYTHONPATH=src $(PY) -m riskqa.semantic.check config/semantic_view.yaml

governance-check: python-guard
	@test -f config/governance.yaml || (echo "治理配置未外置——见 T-4.0.2"; exit 1)
	PYTHONPATH=src $(PY) -m riskqa.governance.check config/governance.yaml

check: lint test semantic-check secret-scan
	@echo "check 通过"

ci: docs-check openq secret-scan lint semantic-check governance-check test
	@echo "ci 全部通过"
