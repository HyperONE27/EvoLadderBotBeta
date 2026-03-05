from pathlib import Path

_default_locale = "enUS"
_translations: dict[str, dict[str, str]] = {}

_locales_dir = Path(Path(__file__).resolve().parent.parent.parent / "data" / "locales")


def _load_translations(locale: str, file_path: Path = _locales_dir) -> None:
    pass


def t(*, key: str, locale: str = _default_locale) -> str | None:
    pass
