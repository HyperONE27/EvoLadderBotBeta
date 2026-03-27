"""Bot command: /party invite, /party leave, /party status."""

import structlog
import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_player_locale
from bot.core.http import get_session
from bot.core.player_lookup import resolve_player_by_string
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)
from bot.helpers.embed_branding import apply_default_embed_footer
from common.i18n import t

logger = structlog.get_logger(__name__)


# --------------------
# Embed helpers
# --------------------


def _party_embed(
    title_key: str, desc_key: str, locale: str, color: discord.Color, **kwargs: str
) -> discord.Embed:
    embed = discord.Embed(
        title=t(title_key, locale),
        description=t(desc_key, locale, **kwargs),
        color=color,
    )
    apply_default_embed_footer(embed, locale=locale)
    return embed


def _error_embed(desc_key: str, locale: str, **kwargs: str) -> discord.Embed:
    embed = discord.Embed(
        title=t("error_embed.title.generic", locale),
        description=t(desc_key, locale, **kwargs),
        color=discord.Color.red(),
    )
    apply_default_embed_footer(embed, locale=locale)
    return embed


# --------------------
# Command registration
# --------------------


party_group = app_commands.Group(
    name="party",
    description="2v2 party commands: invite a partner, leave, or check status",
)


@party_group.command(name="invite", description="Invite a player to your 2v2 party")
@app_commands.check(check_if_accepted_tos)
@app_commands.check(check_if_completed_setup)
@app_commands.check(check_if_banned)
@app_commands.check(check_if_dm)
@app_commands.describe(player="Ladder name, Discord username, or Discord ID")
async def party_invite_command(
    interaction: discord.Interaction,
    player: str,
) -> None:
    await interaction.response.defer()
    uid = interaction.user.id
    locale = get_player_locale(uid)

    # Fetch inviter's player name.
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{uid}") as resp:
            data = await resp.json()
    except Exception:
        await interaction.followup.send(
            embed=_error_embed("party.error.backend_unavailable", locale)
        )
        return

    inviter_player = data.get("player")
    if inviter_player is None:
        await interaction.followup.send(
            embed=_error_embed("party.error.no_profile", locale)
        )
        return
    inviter_name: str = inviter_player.get("player_name", interaction.user.name)

    # Resolve invitee by string.
    invitee_player = await resolve_player_by_string(player)
    if invitee_player is None:
        await interaction.followup.send(
            embed=_error_embed("party.error.player_not_found", locale, player=player)
        )
        return

    invitee_discord_uid: int = invitee_player["discord_uid"]
    invitee_name: str = invitee_player["player_name"]

    if invitee_discord_uid == uid:
        await interaction.followup.send(
            embed=_error_embed("party.error.cannot_invite_self", locale)
        )
        return

    # Send invite to backend.
    payload = {
        "inviter_discord_uid": uid,
        "inviter_player_name": inviter_name,
        "invitee_discord_uid": invitee_discord_uid,
        "invitee_player_name": invitee_name,
    }
    try:
        async with get_session().put(
            f"{BACKEND_URL}/party_2v2/invite", json=payload
        ) as resp:
            if resp.status != 200:
                error_data = await resp.json()
                detail = error_data.get("detail", "Unknown error.")
                await interaction.followup.send(
                    embed=_error_embed(
                        "party.error.invite_failed", locale, detail=detail
                    )
                )
                return
    except Exception:
        await interaction.followup.send(
            embed=_error_embed("party.error.backend_unavailable", locale)
        )
        return

    # Send DM to the invitee with accept/decline buttons.
    invitee_locale = get_player_locale(invitee_discord_uid)
    invite_embed = _party_embed(
        "party.invite_received.title",
        "party.invite_received.description",
        invitee_locale,
        discord.Color.blue(),
        inviter_name=inviter_name,
    )
    view = PartyInviteResponseView(
        invitee_discord_uid=invitee_discord_uid,
        inviter_name=inviter_name,
    )

    try:
        invitee_user = await interaction.client.fetch_user(invitee_discord_uid)
        await invitee_user.send(embed=invite_embed, view=view)
    except discord.Forbidden:
        await interaction.followup.send(
            embed=_error_embed(
                "party.error.cannot_dm", locale, invitee_name=invitee_name
            )
        )
        return

    await interaction.followup.send(
        embed=_party_embed(
            "party.invite_sent.title",
            "party.invite_sent.description",
            locale,
            discord.Color.green(),
            invitee_name=invitee_name,
        )
    )


@party_group.command(name="leave", description="Leave your current 2v2 party")
@app_commands.check(check_if_banned)
@app_commands.check(check_if_dm)
async def party_leave_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    uid = interaction.user.id
    locale = get_player_locale(uid)

    payload = {"discord_uid": uid}
    try:
        async with get_session().delete(
            f"{BACKEND_URL}/party_2v2/leave", json=payload
        ) as resp:
            if resp.status != 200:
                error_data = await resp.json()
                detail = error_data.get("detail", "Unknown error.")
                await interaction.followup.send(
                    embed=_error_embed(
                        "party.error.leave_failed", locale, detail=detail
                    )
                )
                return
            data = await resp.json()
    except Exception:
        await interaction.followup.send(
            embed=_error_embed("party.error.backend_unavailable", locale)
        )
        return

    partner_uid = data.get("partner_discord_uid")
    await interaction.followup.send(
        embed=_party_embed(
            "party.left.title",
            "party.left.description",
            locale,
            discord.Color.orange(),
        )
    )

    # Notify the partner via DM.
    if partner_uid:
        try:
            partner_locale = get_player_locale(partner_uid)
            partner_user = await interaction.client.fetch_user(partner_uid)
            await partner_user.send(
                embed=_party_embed(
                    "party.disbanded.title",
                    "party.disbanded.description",
                    partner_locale,
                    discord.Color.orange(),
                    leaver_name=interaction.user.name,
                )
            )
        except Exception:
            logger.warning(f"Could not notify partner {partner_uid} about party leave")


@party_group.command(name="status", description="Check your current 2v2 party status")
@app_commands.check(check_if_dm)
async def party_status_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    uid = interaction.user.id
    locale = get_player_locale(uid)

    try:
        async with get_session().get(f"{BACKEND_URL}/party_2v2/{uid}") as resp:
            data = await resp.json()
    except Exception:
        await interaction.followup.send(
            embed=_error_embed("party.error.backend_unavailable", locale)
        )
        return

    if not data.get("in_party"):
        await interaction.followup.send(
            embed=_party_embed(
                "party.not_in_party.title",
                "party.not_in_party.description",
                locale,
                discord.Color.greyple(),
            )
        )
        return

    leader_name = data.get("leader_player_name", "Unknown")
    member_name = data.get("member_player_name", "Unknown")

    embed = discord.Embed(
        title=t("party.status.title", locale),
        color=discord.Color.green(),
    )
    embed.add_field(
        name=t("party.status.field_name.leader", locale),
        value=leader_name,
        inline=True,
    )
    embed.add_field(
        name=t("party.status.field_name.member", locale),
        value=member_name,
        inline=True,
    )
    apply_default_embed_footer(embed, locale=locale)

    await interaction.followup.send(embed=embed)


# --------------------
# Accept / Decline view
# --------------------


class PartyInviteResponseView(discord.ui.View):
    """Buttons sent to the invitee via DM to accept or decline a party invite."""

    def __init__(self, invitee_discord_uid: int, inviter_name: str) -> None:
        super().__init__(timeout=None)
        self.invitee_discord_uid = invitee_discord_uid
        self.inviter_name = inviter_name

        _locale = get_player_locale(invitee_discord_uid)

        accept_btn: discord.ui.Button[PartyInviteResponseView] = discord.ui.Button(
            label=t("party.button.accept", _locale),
            style=discord.ButtonStyle.green,
        )
        decline_btn: discord.ui.Button[PartyInviteResponseView] = discord.ui.Button(
            label=t("party.button.decline", _locale),
            style=discord.ButtonStyle.red,
        )

        async def _on_accept(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            await self._respond(interaction, accepted=True)

        async def _on_decline(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            await self._respond(interaction, accepted=False)

        accept_btn.callback = _on_accept  # type: ignore[method-assign]
        decline_btn.callback = _on_decline  # type: ignore[method-assign]
        self.add_item(accept_btn)
        self.add_item(decline_btn)

    async def _respond(self, interaction: discord.Interaction, accepted: bool) -> None:
        locale = get_player_locale(interaction.user.id)

        # Disable buttons after responding.
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.edit_original_response(view=self)

        payload = {
            "invitee_discord_uid": self.invitee_discord_uid,
            "accepted": accepted,
        }
        try:
            async with get_session().put(
                f"{BACKEND_URL}/party_2v2/respond", json=payload
            ) as resp:
                if resp.status != 200:
                    error_data = await resp.json()
                    detail = error_data.get("detail", "Unknown error.")
                    action = "accept" if accepted else "decline"
                    await interaction.followup.send(
                        embed=_error_embed(
                            "party.error.respond_failed",
                            locale,
                            action=action,
                            detail=detail,
                        )
                    )
                    return
                data = await resp.json()
        except Exception:
            await interaction.followup.send(
                embed=_error_embed("party.error.backend_unavailable", locale)
            )
            return

        inviter_uid = data.get("inviter_discord_uid")
        invitee_name = data.get("invitee_player_name", "your partner")

        if accepted:
            await interaction.followup.send(
                embed=_party_embed(
                    "party.accepted_invitee.title",
                    "party.accepted_invitee.description",
                    locale,
                    discord.Color.green(),
                    inviter_name=self.inviter_name,
                )
            )
            if inviter_uid:
                try:
                    inviter_locale = get_player_locale(inviter_uid)
                    inviter_user = await interaction.client.fetch_user(inviter_uid)
                    await inviter_user.send(
                        embed=_party_embed(
                            "party.accepted_inviter.title",
                            "party.accepted_inviter.description",
                            inviter_locale,
                            discord.Color.green(),
                            invitee_name=invitee_name,
                        )
                    )
                except Exception:
                    logger.warning(
                        f"Could not notify inviter {inviter_uid} about accept"
                    )
        else:
            await interaction.followup.send(
                embed=_party_embed(
                    "party.declined_invitee.title",
                    "party.declined_invitee.description",
                    locale,
                    discord.Color.red(),
                    inviter_name=self.inviter_name,
                )
            )
            if inviter_uid:
                try:
                    inviter_locale = get_player_locale(inviter_uid)
                    inviter_user = await interaction.client.fetch_user(inviter_uid)
                    await inviter_user.send(
                        embed=_party_embed(
                            "party.declined_inviter.title",
                            "party.declined_inviter.description",
                            inviter_locale,
                            discord.Color.red(),
                            invitee_name=invitee_name,
                        )
                    )
                except Exception:
                    logger.warning(
                        f"Could not notify inviter {inviter_uid} about decline"
                    )


def register_party_command(tree: app_commands.CommandTree) -> None:
    tree.add_command(party_group)
