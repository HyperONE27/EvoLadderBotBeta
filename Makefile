.PHONY: quality
quality:
	ruff check --fix . && ruff format . && mypy backend bot channel_manager common && python -m pytest tests/ -v

.PHONY: run
run:
	./run_local.sh