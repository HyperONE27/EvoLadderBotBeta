"""Locale parity tests.

CLAUDE.md mandates that all six locale files share an identical key set
and that keys within each file are in lexicographic order. These tests
make that invariant enforceable — if a contributor forgets to update a
sibling locale file when adding a key, CI will fail here rather than
the bot discovering it at runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

LOCALES_DIR = Path(__file__).resolve().parents[1] / "data" / "locales"
LOCALE_FILES = ("base", "enUS", "esMX", "koKR", "ruRU", "zhCN")


def _load(locale: str) -> dict[str, str]:
    with (LOCALES_DIR / f"{locale}.json").open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def locales() -> dict[str, dict[str, str]]:
    return {name: _load(name) for name in LOCALE_FILES}


def test_all_locale_files_exist() -> None:
    for name in LOCALE_FILES:
        path = LOCALES_DIR / f"{name}.json"
        assert path.exists(), f"missing locale file: {path}"


def test_identical_key_sets(locales: dict[str, dict[str, str]]) -> None:
    reference = set(locales["base"].keys())
    for name, data in locales.items():
        if name == "base":
            continue
        current = set(data.keys())
        missing = reference - current
        extra = current - reference
        assert not missing and not extra, (
            f"{name}.json key set diverges from base.json — "
            f"missing: {sorted(missing)}, extra: {sorted(extra)}"
        )


@pytest.mark.parametrize("name", LOCALE_FILES)
def test_keys_are_lexicographically_sorted(
    name: str, locales: dict[str, dict[str, str]]
) -> None:
    keys = list(locales[name].keys())
    sorted_keys = sorted(keys)
    assert keys == sorted_keys, (
        f"{name}.json keys are not in lexicographic order. "
        f"First out-of-order key: "
        f"{next((k for k, s in zip(keys, sorted_keys) if k != s), '?')}"
    )
