"""Default ladder branding on Discord embed footers."""

from __future__ import annotations

import discord

from bot.core.config import BOT_ICON_URL
from common.i18n import t

EMBED_BRAND_FOOTER_KEY = "embed_brand.footer.1"


def apply_default_embed_footer(
    embed: discord.Embed,
    *,
    locale: str = "enUS",
) -> None:
    """Append localized ladder branding to the embed footer.

    If there is no footer text, the footer becomes only the brand line.
    If there is footer text, the brand line is appended on a new line.
    ``icon_url`` is set from ``BOT_ICON_URL`` when non-empty.
    Skips if the last non-empty line already equals the localized brand line.
    """

    brand_line = t(EMBED_BRAND_FOOTER_KEY, locale)
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
