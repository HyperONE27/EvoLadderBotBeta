.PHONY: quality
quality:
	ruff check --fix . && ruff format . && mypy backend bot common

.PHONY: dev
dev:
	./run_local.sh