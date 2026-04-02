.PHONY: quality
quality:
	uv run ruff check --fix . && uv run ruff format . && uv run mypy backend bot channel_manager common && uv run python -m pytest tests/ -v

.PHONY: run
run:
	./run_local.sh
