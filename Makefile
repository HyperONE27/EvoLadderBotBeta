.PHONY: quality
quality:
	ruff check --fix . && ruff format . && mypy backend bot channel_manager common

.PHONY: run
run:
	./run_local.sh