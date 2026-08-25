.PHONY: lint test venv

# Guarded on uv (same pattern as contract-tests): machines without the Python
# toolchain no-op honestly instead of failing the repo-wide make lint/test.
ifeq (,$(shell command -v uv 2>/dev/null))
lint test venv:
	@echo "sdks/python: uv not installed — skipping $@ (https://docs.astral.sh/uv/)"
else
venv:
	uv sync

lint: venv
	uv run ruff check .
	uv run mypy

test: venv
	uv run pytest -q
endif
