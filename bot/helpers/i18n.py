from pathlib import Path

_default_locale = "enUS"
_translations: dict[str, dict[str, str]] = {}

_locales_dir = Path(Path(__file__).resolve().parent.parent.parent / "data" / "locales")

# Human-readable display names for each locale code.
LOCALE_DISPLAY_NAMES: dict[str, tuple[str, str]] = {
    "enUS": ("English (US)", "🇺🇸"),
    "esMX": ("Español (MX)", "🇲🇽"),
    "koKR": ("한국어", "🇰🇷"),
    "ruRU": ("Русский", "🇷🇺"),
    "zhCN": ("中文 (简体)", "🇨🇳"),
}


def get_available_locales() -> list[str]:
    """Return locale codes derived from files present in data/locales/, excluding base."""
    return sorted(p.stem for p in _locales_dir.glob("*.json") if p.stem != "base")


def _load_translations(locale: str, file_path: Path = _locales_dir) -> None:
    pass


def t(*, key: str, locale: str = _default_locale) -> str | None:
    pass
