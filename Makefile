.PHONY: quality
quality:
	ruff check --fix . && ruff format . && mypy src