"""Translation lookup (i18n).

Usage::

    from common.i18n import t

    title = t("bot.commands.user.setcountry.confirm.title", locale)
    desc  = t("bot.commands.user.setcountry.not_found.description", locale, country=name)

``init_i18n`` is called once at startup by ``Cache._populate_locale_data``.
All subsequent calls to ``t`` read from the module-level cache.
"""

from __future__ import annotations

_DEFAULT_LOCALE = "enUS"

# locale_code → {key: translated_string}
_locales: dict[str, dict[str, str]] = {}


def init_i18n(locales: dict[str, dict[str, str]]) -> None:
    """Populate the module-level locale cache.  Called once at startup."""
    global _locales
    _locales = locales


def t(key: str, locale: str = _DEFAULT_LOCALE, **kwargs: str) -> str:
    """Return the translated string for *key* in *locale*.

    Fallback order:
    1. ``_locales[locale][key]``
    2. ``_locales[enUS][key]``
    3. ``key`` itself (safe no-op when translation is missing)

    Named placeholders (``{name}``) are substituted via *kwargs*.
    """
    strings = _locales.get(locale) or _locales.get(_DEFAULT_LOCALE) or {}
    value = strings.get(key) or key
    if kwargs:
        try:
            return value.format_map(kwargs)
        except (KeyError, ValueError):
            return value
    return value
