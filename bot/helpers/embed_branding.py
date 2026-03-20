"""Default ladder branding on Discord embed footers."""

from __future__ import annotations

import discord

from bot.core.config import BOT_ICON_URL

BRAND_FOOTER_TEXT = "SC: Evo Complete Ladder Bot"


def apply_default_embed_footer(embed: discord.Embed) -> None:
    """Set or extend the embed footer with ladder branding.

    - If there is no footer text, the footer becomes only the brand line.
    - If there is footer text, the brand line is appended on a new line.
    - ``icon_url`` is set from ``BOT_ICON_URL`` when non-empty (replaces any
      previous footer icon so the bot icon stays consistent).
    - Safe to call repeatedly: skips if the last line is already the brand text.

    Discord allows a single footer per embed (one text + one icon).
    """

    icon_url = BOT_ICON_URL.strip() or None
    existing_raw = embed.footer.text if embed.footer.text else ""
    existing = existing_raw.strip()
    lines = [ln for ln in existing.splitlines() if ln.strip()]
    if lines and lines[-1] == BRAND_FOOTER_TEXT:
        return

    if not existing:
        new_text = BRAND_FOOTER_TEXT
    else:
        new_text = f"{existing}\n{BRAND_FOOTER_TEXT}"

    embed.set_footer(text=new_text, icon_url=icon_url)


class _BrandedEmbedMeta(type):
    def __call__(cls, *args, **kwargs):
        self = super().__call__(*args, **kwargs)
        apply_default_embed_footer(self)
        return self


class BrandedEmbed(discord.Embed, metaclass=_BrandedEmbedMeta):
    """discord.Embed that applies ladder footer after subclass ``__init__`` completes."""
