"""Default ladder branding on Discord embed footers."""

from __future__ import annotations

from typing import Any

import discord

from bot.core.config import BOT_ICON_URL
from common.i18n import t

EMBED_BRAND_FOOTER_KEY = "embed_brand.footer.1"


def apply_default_embed_footer(
    embed: discord.Embed,
    *,
    locale: str | None = None,
) -> None:
    """Set or extend the embed footer with localized ladder branding.

    Uses ``embed._embed_locale`` when *locale* is omitted (set by ``BrandedEmbed``).
    If there is no footer text, the footer becomes only the brand line.
    If there is footer text, the brand line is appended on a new line.
    ``icon_url`` is set from ``BOT_ICON_URL`` when non-empty.
    Skips if the last non-empty line already equals the localized brand line.
    """

    loc = locale if locale is not None else getattr(embed, "_embed_locale", "enUS")
    brand_line = t(EMBED_BRAND_FOOTER_KEY, loc)
    icon_url = BOT_ICON_URL.strip() or None

    existing_raw = embed.footer.text if embed.footer.text else ""
    existing = existing_raw.strip()
    lines = [ln for ln in existing.splitlines() if ln.strip()]
    if lines and lines[-1] == brand_line:
        return

    if not existing:
        new_text = brand_line
    else:
        new_text = f"{existing}\n{brand_line}"

    embed.set_footer(text=new_text, icon_url=icon_url)


class _BrandedEmbedMeta(type):
    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        self = super().__call__(*args, **kwargs)
        apply_default_embed_footer(self)
        return self


class BrandedEmbed(discord.Embed, metaclass=_BrandedEmbedMeta):
    """discord.Embed that applies localized ladder footer after ``__init__`` completes."""

    _embed_locale: str

    def __init__(self, *args: Any, locale: str = "enUS", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._embed_locale = locale
