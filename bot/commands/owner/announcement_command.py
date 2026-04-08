"""
/announcement — owner-only broadcast DM to all eligible players.

Flow:
  1. Slash command shows an intro embed with [Write announcement] / [Cancel].
  2. Write opens a modal (title <= 200, body <= 1700).
  3. On submit, the bot fetches the recipient set from the backend, filters
     to members currently in the configured guild, and shows a preview embed
     with rendered content + recipient count and a confirm button.
  4. On confirm, the bot fans out DMs via the low-priority message queue,
     tallies successes/failures, and posts an audit-log event to the backend.
"""

from __future__ import annotations

import asyncio
from typing import Any

import discord
import structlog
from discord import app_commands

from bot.components.embeds import ErrorEmbed
from bot.core.config import BACKEND_URL, SERVER_GUILD_ID
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.helpers.checks import check_admin
from bot.helpers.message_helpers import queue_user_send_low
from common.i18n import t

logger = structlog.get_logger(__name__)

_TITLE_MAX = 200
_BODY_MAX = 1700


# ----------------
# Helpers
# ----------------


def _render_message(title: str, body: str) -> str:
    return f"## {title}\n\n{body}"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _fetch_recipient_uids(
    owner_discord_uid: int, debug: bool, require_setup: bool
) -> list[int] | None:
    try:
        async with get_session().get(
            f"{BACKEND_URL}/owner/announcement_recipients",
            params={
                "owner_discord_uid": owner_discord_uid,
                "debug": str(debug).lower(),
                "require_setup": str(require_setup).lower(),
            },
        ) as resp:
            if resp.status >= 400:
                return None
            data = await resp.json()
            return [int(x) for x in data.get("discord_uids", [])]
    except Exception:
        logger.exception("announcement: failed to fetch recipients")
        return None


async def _post_audit_log(payload: dict[str, Any]) -> None:
    try:
        async with get_session().post(
            f"{BACKEND_URL}/owner/announcement_log", json=payload
        ) as resp:
            if resp.status >= 400:
                logger.warning(
                    "announcement: audit log POST failed", status=resp.status
                )
    except Exception:
        logger.exception("announcement: failed to POST audit log")


# ----------------
# Embeds
# ----------------


def _intro_embed(locale: str, debug: bool, require_setup: bool) -> discord.Embed:
    return discord.Embed(
        title=t("owner_announcement.intro.title", locale),
        description=t(
            "owner_announcement.intro.description",
            locale,
            debug=str(debug),
            require_setup=str(require_setup),
        ),
        color=discord.Color.blurple(),
    )


def _preview_embed(
    locale: str,
    rendered: str,
    recipient_count: int,
    not_in_server_count: int,
    debug: bool,
    require_setup: bool,
) -> discord.Embed:
    embed = discord.Embed(
        title=t("owner_announcement.preview.title", locale),
        description=_truncate(rendered, 4000),
        color=discord.Color.orange(),
    )
    embed.add_field(
        name=t("owner_announcement.preview.field.recipients", locale),
        value=str(recipient_count),
        inline=True,
    )
    embed.add_field(
        name=t("owner_announcement.preview.field.skipped_not_in_server", locale),
        value=str(not_in_server_count),
        inline=True,
    )
    embed.add_field(
        name=t("owner_announcement.preview.field.flags", locale),
        value=f"debug={debug} · require_setup={require_setup}",
        inline=False,
    )
    return embed


def _result_embed(
    locale: str,
    sent: int,
    dm_closed: int,
    not_in_server: int,
    other_error: int,
    total: int,
) -> discord.Embed:
    return discord.Embed(
        title=t("owner_announcement.result.title", locale),
        description=t(
            "owner_announcement.result.description",
            locale,
            sent=str(sent),
            dm_closed=str(dm_closed),
            not_in_server=str(not_in_server),
            other_error=str(other_error),
            total=str(total),
        ),
        color=discord.Color.green(),
    )


def _cancelled_embed(locale: str) -> discord.Embed:
    return discord.Embed(
        title=t("owner_announcement.cancelled.title", locale),
        description=t("owner_announcement.cancelled.description", locale),
        color=discord.Color.dark_grey(),
    )


# ----------------
# Modal
# ----------------


class _AnnouncementModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        invoker_uid: int,
        debug: bool,
        require_setup: bool,
        client: discord.Client,
        locale: str,
    ) -> None:
        super().__init__(title=t("owner_announcement.modal.title", locale), timeout=600)
        self._invoker_uid = invoker_uid
        self._debug = debug
        self._require_setup = require_setup
        self._client = client
        self._locale = locale

        self.title_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label=t("owner_announcement.modal.label.title", locale),
            style=discord.TextStyle.short,
            max_length=_TITLE_MAX,
            required=True,
        )
        self.body_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label=t("owner_announcement.modal.label.body", locale),
            style=discord.TextStyle.paragraph,
            max_length=_BODY_MAX,
            required=True,
        )
        self.add_item(self.title_input)
        self.add_item(self.body_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        title = self.title_input.value.strip()
        body = self.body_input.value
        rendered = _render_message(title, body)
        locale = self._locale

        all_uids = await _fetch_recipient_uids(
            self._invoker_uid, self._debug, self._require_setup
        )
        if all_uids is None:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title=t("error_embed.title.generic", locale),
                    description=t(
                        "owner_announcement.error.fetch_recipients_failed", locale
                    ),
                    locale=locale,
                ),
                ephemeral=True,
            )
            return

        guild = self._client.get_guild(SERVER_GUILD_ID)
        if guild is None:
            await interaction.followup.send(
                embed=ErrorEmbed(
                    title=t("error_embed.title.generic", locale),
                    description=t("owner_announcement.error.guild_unavailable", locale),
                    locale=locale,
                ),
                ephemeral=True,
            )
            return

        in_server: list[int] = []
        not_in_server = 0
        for uid in all_uids:
            if guild.get_member(uid) is not None:
                in_server.append(uid)
            else:
                not_in_server += 1

        view = _ConfirmAnnouncementView(
            invoker_uid=self._invoker_uid,
            client=self._client,
            recipient_uids=in_server,
            not_in_server_count=not_in_server,
            title=title,
            body=body,
            rendered=rendered,
            debug=self._debug,
            require_setup=self._require_setup,
            locale=locale,
        )
        view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
            embed=_preview_embed(
                locale,
                rendered,
                len(in_server),
                not_in_server,
                self._debug,
                self._require_setup,
            ),
            view=view,
        )


# ----------------
# Views
# ----------------


class _IntroView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_uid: int,
        debug: bool,
        require_setup: bool,
        client: discord.Client,
        locale: str,
    ) -> None:
        super().__init__(timeout=300)
        self._invoker_uid = invoker_uid
        self._debug = debug
        self._require_setup = require_setup
        self._client = client
        self._locale = locale
        self.message: discord.Message | None = None

        write_btn: discord.ui.Button[Any] = discord.ui.Button(
            label=t("owner_announcement.button.write", locale),
            style=discord.ButtonStyle.primary,
            emoji="📝",
        )
        write_btn.callback = self._on_write  # type: ignore[method-assign]
        self.add_item(write_btn)

        cancel_btn: discord.ui.Button[Any] = discord.ui.Button(
            label=t("button.cancel", locale),
            style=discord.ButtonStyle.danger,
            emoji="✖️",
        )
        cancel_btn.callback = self._on_cancel  # type: ignore[method-assign]
        self.add_item(cancel_btn)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_uid:
            await interaction.response.send_message(
                t(
                    "state_change.invoker_only",
                    get_player_locale(interaction.user.id),
                ),
                ephemeral=True,
            )
            return False
        return True

    async def _on_write(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_modal(
            _AnnouncementModal(
                invoker_uid=self._invoker_uid,
                debug=self._debug,
                require_setup=self._require_setup,
                client=self._client,
                locale=self._locale,
            )
        )

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.response.edit_message(
            embed=_cancelled_embed(self._locale), view=None
        )


class _ConfirmAnnouncementView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_uid: int,
        client: discord.Client,
        recipient_uids: list[int],
        not_in_server_count: int,
        title: str,
        body: str,
        rendered: str,
        debug: bool,
        require_setup: bool,
        locale: str,
    ) -> None:
        super().__init__(timeout=300)
        self._invoker_uid = invoker_uid
        self._client = client
        self._recipient_uids = recipient_uids
        self._not_in_server_count = not_in_server_count
        self._title = title
        self._body = body
        self._rendered = rendered
        self._debug = debug
        self._require_setup = require_setup
        self._locale = locale
        self.message: discord.Message | None = None

        confirm_btn: discord.ui.Button[Any] = discord.ui.Button(
            label=t("owner_announcement.button.send", locale),
            style=discord.ButtonStyle.success,
            emoji="📣",
        )
        confirm_btn.callback = self._on_confirm  # type: ignore[method-assign]
        self.add_item(confirm_btn)

        cancel_btn: discord.ui.Button[Any] = discord.ui.Button(
            label=t("button.cancel", locale),
            style=discord.ButtonStyle.danger,
            emoji="✖️",
        )
        cancel_btn.callback = self._on_cancel  # type: ignore[method-assign]
        self.add_item(cancel_btn)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_uid:
            await interaction.response.send_message(
                t(
                    "state_change.invoker_only",
                    get_player_locale(interaction.user.id),
                ),
                ephemeral=True,
            )
            return False
        return True

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.response.edit_message(
            embed=_cancelled_embed(self._locale), view=None
        )

    async def _on_confirm(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.response.defer()

        guild = self._client.get_guild(SERVER_GUILD_ID)
        sent = 0
        dm_closed = 0
        not_in_server = self._not_in_server_count
        other_error = 0

        for uid in self._recipient_uids:
            member = guild.get_member(uid) if guild is not None else None
            if member is None:
                not_in_server += 1
                continue
            try:
                await queue_user_send_low(member, content=self._rendered)
                sent += 1
            except discord.Forbidden:
                dm_closed += 1
            except discord.NotFound:
                not_in_server += 1
            except discord.HTTPException:
                other_error += 1
                logger.warning(
                    "announcement: HTTPException sending DM",
                    uid=uid,
                    exc_info=True,
                )
            except Exception:
                other_error += 1
                logger.exception("announcement: unexpected send failure", uid=uid)
            # Yield to the event loop occasionally so we don't hog it.
            if (sent + dm_closed + other_error) % 25 == 0:
                await asyncio.sleep(0)

        total = len(self._recipient_uids) + self._not_in_server_count
        await _post_audit_log(
            {
                "owner_discord_uid": self._invoker_uid,
                "title": self._title,
                "body": self._body,
                "debug": self._debug,
                "require_setup": self._require_setup,
                "recipient_count": total,
                "sent_count": sent,
                "dm_closed_count": dm_closed,
                "not_in_server_count": not_in_server,
                "other_error_count": other_error,
            }
        )

        logger.info(
            "announcement: sent",
            owner=self._invoker_uid,
            sent=sent,
            dm_closed=dm_closed,
            not_in_server=not_in_server,
            other_error=other_error,
            total=total,
        )

        await interaction.followup.send(
            embed=_result_embed(
                self._locale, sent, dm_closed, not_in_server, other_error, total
            )
        )


# --------------------
# Command registration
# --------------------


def register_owner_announcement_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="announcement",
        description="[Owner] Broadcast a DM to all eligible players",
    )
    @app_commands.describe(
        debug="Restrict recipients to the admins table (test mode)",
        require_setup="Only send to players who have completed setup",
    )
    async def announcement_command(
        interaction: discord.Interaction,
        debug: bool = False,
        require_setup: bool = True,
    ) -> None:
        await interaction.response.defer()
        await check_admin(interaction, owner=True)

        locale = get_player_locale(interaction.user.id)
        client = interaction.client

        logger.info(
            "Owner invoked /announcement",
            owner=interaction.user.id,
            debug=debug,
            require_setup=require_setup,
        )

        view = _IntroView(
            invoker_uid=interaction.user.id,
            debug=debug,
            require_setup=require_setup,
            client=client,
            locale=locale,
        )
        view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
            embed=_intro_embed(locale, debug, require_setup),
            view=view,
        )
