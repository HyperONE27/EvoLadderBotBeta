"""
/announcement — owner-only broadcast embed DM to eligible players.

Flow:
  1. Slash command shows an intro embed with [Write announcement] / [Cancel].
  2. Write opens a modal (title <= 256, body <= 4000).
  3. On submit, the bot fetches the recipient set from the backend, filters
     to members currently in the configured guild, and shows a preview that
     pairs the rendered announcement embed with a meta embed listing the
     recipient counts and audience flags.
  4. On confirm, the view is immediately disabled and the message is replaced
     with a "Sending..." progress embed that is updated periodically as the
     fan-out runs. When complete, the same message is replaced with a final
     result embed and an audit-log event is posted to the backend.

Audience flags (precedence):
  - ``owners_only``  → admins.role == "owner"
  - ``debug``        → admins.role != "inactive"
  - default          → players.is_banned == False [+ completed_setup if
                       ``require_setup`` is True]
"""

from __future__ import annotations

import asyncio
import time
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

# Discord embed hard limits.
_TITLE_MAX = 256
_BODY_MAX = 4000  # Modal TextInput max_length cap; embed description allows 4096.

# Live progress update cadence.
_PROGRESS_UPDATE_EVERY_N = 10
_PROGRESS_UPDATE_MIN_INTERVAL_S = 1.5


# ----------------
# Backend helpers
# ----------------


async def _fetch_recipient_uids(
    owner_discord_uid: int,
    debug: bool,
    owners_only: bool,
    require_setup: bool,
) -> list[int] | None:
    try:
        async with get_session().get(
            f"{BACKEND_URL}/owner/announcement_recipients",
            params={
                "owner_discord_uid": owner_discord_uid,
                "debug": str(debug).lower(),
                "owners_only": str(owners_only).lower(),
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


def _audience_label(debug: bool, owners_only: bool) -> str:
    if owners_only:
        return 'Owners only (`admins.role == "owner"`)'
    if debug:
        return 'Admins (debug — `admins.role != "inactive"`)'
    return "All eligible players"


def _flags_block(debug: bool, owners_only: bool, require_setup: bool) -> str:
    lines = [f"• **Audience:** {_audience_label(debug, owners_only)}"]
    if not (owners_only or debug):
        lines.append(
            f"• **Require completed setup:** {'Yes' if require_setup else 'No'}"
        )
    return "\n".join(lines)


def _announcement_embed(title: str, body: str) -> discord.Embed:
    """The actual embed that will be DM'd to recipients."""
    return discord.Embed(
        title=title[:_TITLE_MAX],
        description=body[:4096],
        color=discord.Color.blurple(),
    )


def _intro_embed(
    locale: str, debug: bool, owners_only: bool, require_setup: bool
) -> discord.Embed:
    return discord.Embed(
        title=t("owner_announcement.intro.title", locale),
        description=t(
            "owner_announcement.intro.description",
            locale,
            flags=_flags_block(debug, owners_only, require_setup),
        ),
        color=discord.Color.blurple(),
    )


def _preview_meta_embed(
    locale: str,
    recipient_count: int,
    not_in_server_count: int,
    debug: bool,
    owners_only: bool,
    require_setup: bool,
) -> discord.Embed:
    embed = discord.Embed(
        title=t("owner_announcement.preview.title", locale),
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
        value=_flags_block(debug, owners_only, require_setup),
        inline=False,
    )
    return embed


def _sending_meta_embed(
    locale: str,
    sent: int,
    dm_closed: int,
    not_in_server: int,
    other_error: int,
    total: int,
) -> discord.Embed:
    processed = sent + dm_closed + not_in_server + other_error
    return discord.Embed(
        title=t("owner_announcement.sending.title", locale),
        description=t(
            "owner_announcement.sending.description",
            locale,
            processed=str(processed),
            total=str(total),
            sent=str(sent),
            dm_closed=str(dm_closed),
            not_in_server=str(not_in_server),
            other_error=str(other_error),
        ),
        color=discord.Color.orange(),
    )


def _result_meta_embed(
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
        owners_only: bool,
        require_setup: bool,
        client: discord.Client,
        locale: str,
    ) -> None:
        super().__init__(title=t("owner_announcement.modal.title", locale), timeout=600)
        self._invoker_uid = invoker_uid
        self._debug = debug
        self._owners_only = owners_only
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
        # Defer as a message update — the modal was launched from a button on
        # the intro message, so this acks the modal submit without sending a
        # new response, leaving us free to edit the parent message in place.
        await interaction.response.defer()

        title = self.title_input.value.strip()
        body = self.body_input.value
        locale = self._locale

        async def _edit_with_error(description: str) -> None:
            await interaction.edit_original_response(
                embeds=[
                    ErrorEmbed(
                        title=t("error_embed.title.generic", locale),
                        description=description,
                        locale=locale,
                    )
                ],
                view=None,
            )

        all_uids = await _fetch_recipient_uids(
            self._invoker_uid,
            self._debug,
            self._owners_only,
            self._require_setup,
        )
        if all_uids is None:
            await _edit_with_error(
                t("owner_announcement.error.fetch_recipients_failed", locale)
            )
            return

        guild = self._client.get_guild(SERVER_GUILD_ID)
        if guild is None:
            await _edit_with_error(
                t("owner_announcement.error.guild_unavailable", locale)
            )
            return

        in_server: list[int] = []
        not_in_server = 0
        for uid in all_uids:
            if guild.get_member(uid) is not None:
                in_server.append(uid)
            else:
                not_in_server += 1

        announcement_embed = _announcement_embed(title, body)
        meta_embed = _preview_meta_embed(
            locale,
            len(in_server),
            not_in_server,
            self._debug,
            self._owners_only,
            self._require_setup,
        )

        view = _ConfirmAnnouncementView(
            invoker_uid=self._invoker_uid,
            client=self._client,
            recipient_uids=in_server,
            not_in_server_count=not_in_server,
            title=title,
            body=body,
            debug=self._debug,
            owners_only=self._owners_only,
            require_setup=self._require_setup,
            locale=locale,
        )
        await interaction.edit_original_response(
            embeds=[announcement_embed, meta_embed],
            view=view,
        )
        view.message = await interaction.original_response()


# ----------------
# Views
# ----------------


class _IntroView(discord.ui.View):
    def __init__(
        self,
        *,
        invoker_uid: int,
        debug: bool,
        owners_only: bool,
        require_setup: bool,
        client: discord.Client,
        locale: str,
    ) -> None:
        super().__init__(timeout=300)
        self._invoker_uid = invoker_uid
        self._debug = debug
        self._owners_only = owners_only
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
                owners_only=self._owners_only,
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
        debug: bool,
        owners_only: bool,
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
        self._debug = debug
        self._owners_only = owners_only
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
            embed=_cancelled_embed(self._locale), embeds=[], view=None
        )

    async def _on_confirm(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True

        announcement_embed = _announcement_embed(self._title, self._body)
        total = len(self._recipient_uids) + self._not_in_server_count
        sent = 0
        dm_closed = 0
        not_in_server = self._not_in_server_count
        other_error = 0

        # Immediately replace the preview with the "sending..." state and
        # drop the view buttons. This acknowledges the interaction.
        await interaction.response.edit_message(
            embeds=[
                announcement_embed,
                _sending_meta_embed(
                    self._locale, sent, dm_closed, not_in_server, other_error, total
                ),
            ],
            view=None,
        )

        async def push_progress() -> None:
            try:
                await interaction.edit_original_response(
                    embeds=[
                        announcement_embed,
                        _sending_meta_embed(
                            self._locale,
                            sent,
                            dm_closed,
                            not_in_server,
                            other_error,
                            total,
                        ),
                    ]
                )
            except discord.HTTPException:
                logger.warning("announcement: progress edit failed", exc_info=True)

        guild = self._client.get_guild(SERVER_GUILD_ID)
        last_update = time.monotonic()
        steps_since_update = 0

        for uid in self._recipient_uids:
            member = guild.get_member(uid) if guild is not None else None
            if member is None:
                not_in_server += 1
            else:
                try:
                    await queue_user_send_low(member, embed=announcement_embed)
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

            steps_since_update += 1
            now = time.monotonic()
            if (
                steps_since_update >= _PROGRESS_UPDATE_EVERY_N
                and (now - last_update) >= _PROGRESS_UPDATE_MIN_INTERVAL_S
            ):
                await push_progress()
                last_update = now
                steps_since_update = 0
                # Yield to the event loop so other coroutines can run.
                await asyncio.sleep(0)

        await _post_audit_log(
            {
                "owner_discord_uid": self._invoker_uid,
                "title": self._title,
                "body": self._body,
                "debug": self._debug,
                "owners_only": self._owners_only,
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

        try:
            await interaction.edit_original_response(
                embeds=[
                    announcement_embed,
                    _result_meta_embed(
                        self._locale,
                        sent,
                        dm_closed,
                        not_in_server,
                        other_error,
                        total,
                    ),
                ]
            )
        except discord.HTTPException:
            logger.warning("announcement: final edit failed", exc_info=True)


# --------------------
# Command registration
# --------------------


def register_owner_announcement_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="announcement",
        description="[Owner] Broadcast an embed DM to all eligible players",
    )
    @app_commands.describe(
        debug="Restrict recipients to the admins table (test mode)",
        owners_only="Restrict recipients to owners only (highest precedence)",
        require_setup="Only send to players who have completed setup",
    )
    async def announcement_command(
        interaction: discord.Interaction,
        debug: bool = False,
        owners_only: bool = False,
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
            owners_only=owners_only,
            require_setup=require_setup,
        )

        view = _IntroView(
            invoker_uid=interaction.user.id,
            debug=debug,
            owners_only=owners_only,
            require_setup=require_setup,
            client=client,
            locale=locale,
        )
        view.message = await interaction.followup.send(  # type: ignore[func-returns-value]
            embed=_intro_embed(locale, debug, owners_only, require_setup),
            view=view,
        )
