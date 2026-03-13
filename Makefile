.PHONY: quality
quality:
	ruff check --fix . && ruff format . && mypy backend bot common

.PHONY: run
run:
	./run_local.sh