"""Bot command: /party invite, /party leave, /party status."""

import structlog
import discord
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import (
    check_if_accepted_tos,
    check_if_banned,
    check_if_completed_setup,
    check_if_dm,
)

logger = structlog.get_logger(__name__)


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
async def party_invite_command(
    interaction: discord.Interaction,
    user: discord.User,
) -> None:
    await interaction.response.defer()
    uid = interaction.user.id

    # Fetch inviter's player name.
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{uid}") as resp:
            data = await resp.json()
    except Exception:
        await interaction.followup.send("Failed to reach the backend. Try again later.")
        return

    inviter_player = data.get("player")
    if inviter_player is None:
        await interaction.followup.send(
            "Your player profile was not found. Run `/setup` first."
        )
        return
    inviter_name: str = inviter_player.get("player_name", interaction.user.name)

    # Fetch invitee's player name.
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{user.id}") as resp:
            data = await resp.json()
    except Exception:
        await interaction.followup.send("Failed to reach the backend. Try again later.")
        return

    invitee_player = data.get("player")
    if invitee_player is None:
        await interaction.followup.send(
            f"{user.mention} has not completed setup yet. They need to run `/setup` first."
        )
        return
    invitee_name: str = invitee_player.get("player_name", user.name)

    # Send invite to backend.
    payload = {
        "inviter_discord_uid": uid,
        "inviter_player_name": inviter_name,
        "invitee_discord_uid": user.id,
        "invitee_player_name": invitee_name,
    }
    try:
        async with get_session().put(
            f"{BACKEND_URL}/party_2v2/invite", json=payload
        ) as resp:
            if resp.status != 200:
                error_data = await resp.json()
                detail = error_data.get("detail", "Unknown error.")
                await interaction.followup.send(f"Could not send invite: {detail}")
                return
    except Exception:
        await interaction.followup.send("Failed to reach the backend. Try again later.")
        return

    # Send DM to the invitee with accept/decline buttons.
    embed = discord.Embed(
        title="2v2 Party Invite",
        description=(
            f"**{inviter_name}** has invited you to form a 2v2 party!\n\n"
            f"Accept to team up and queue together."
        ),
        color=discord.Color.blue(),
    )
    view = PartyInviteResponseView(
        invitee_discord_uid=user.id,
        inviter_name=inviter_name,
    )

    try:
        await user.send(embed=embed, view=view)
    except discord.Forbidden:
        await interaction.followup.send(
            f"Could not DM {user.mention}. They may have DMs disabled."
        )
        return

    await interaction.followup.send(
        f"Party invite sent to **{invitee_name}**! They will receive a DM to accept or decline."
    )


@party_group.command(name="leave", description="Leave your current 2v2 party")
@app_commands.check(check_if_banned)
@app_commands.check(check_if_dm)
async def party_leave_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    uid = interaction.user.id

    payload = {"discord_uid": uid}
    try:
        async with get_session().delete(
            f"{BACKEND_URL}/party_2v2/leave", json=payload
        ) as resp:
            if resp.status != 200:
                error_data = await resp.json()
                detail = error_data.get("detail", "Unknown error.")
                await interaction.followup.send(f"Could not leave party: {detail}")
                return
            data = await resp.json()
    except Exception:
        await interaction.followup.send("Failed to reach the backend. Try again later.")
        return

    partner_uid = data.get("partner_discord_uid")
    await interaction.followup.send(
        "You have left the party. Both players are now idle."
    )

    # Notify the partner via DM.
    if partner_uid:
        try:
            partner_user = await interaction.client.fetch_user(partner_uid)
            await partner_user.send(
                f"Your 2v2 party has been disbanded because **{interaction.user.name}** left."
            )
        except Exception:
            logger.warning(f"Could not notify partner {partner_uid} about party leave")


@party_group.command(name="status", description="Check your current 2v2 party status")
@app_commands.check(check_if_dm)
async def party_status_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    uid = interaction.user.id

    try:
        async with get_session().get(f"{BACKEND_URL}/party_2v2/{uid}") as resp:
            data = await resp.json()
    except Exception:
        await interaction.followup.send("Failed to reach the backend. Try again later.")
        return

    if not data.get("in_party"):
        await interaction.followup.send("You are not currently in a 2v2 party.")
        return

    leader_name = data.get("leader_player_name", "Unknown")
    member_name = data.get("member_player_name", "Unknown")

    embed = discord.Embed(
        title="2v2 Party Status",
        color=discord.Color.green(),
    )
    embed.add_field(name="Leader", value=leader_name, inline=True)
    embed.add_field(name="Member", value=member_name, inline=True)

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

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PartyInviteResponseView"],
    ) -> None:
        await interaction.response.defer()
        await self._respond(interaction, accepted=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["PartyInviteResponseView"],
    ) -> None:
        await interaction.response.defer()
        await self._respond(interaction, accepted=False)

    async def _respond(self, interaction: discord.Interaction, accepted: bool) -> None:
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
                    await interaction.followup.send(
                        f"Could not {'accept' if accepted else 'decline'} invite: {detail}"
                    )
                    return
                data = await resp.json()
        except Exception:
            await interaction.followup.send(
                "Failed to reach the backend. Try again later."
            )
            return

        if accepted:
            await interaction.followup.send(
                f"You have joined **{self.inviter_name}**'s party! "
                f"Both players can now `/queue` for 2v2."
            )
            # Notify the inviter.
            inviter_uid = data.get("inviter_discord_uid")
            invitee_name = data.get("invitee_player_name", "your partner")
            if inviter_uid:
                try:
                    inviter_user = await interaction.client.fetch_user(inviter_uid)
                    await inviter_user.send(
                        f"**{invitee_name}** has accepted your party invite! "
                        f"Both players can now `/queue` for 2v2."
                    )
                except Exception:
                    logger.warning(
                        f"Could not notify inviter {inviter_uid} about accept"
                    )
        else:
            await interaction.followup.send(
                f"You have declined the party invite from **{self.inviter_name}**."
            )
            # Notify the inviter.
            inviter_uid = data.get("inviter_discord_uid")
            invitee_name = data.get("invitee_player_name", "the invitee")
            if inviter_uid:
                try:
                    inviter_user = await interaction.client.fetch_user(inviter_uid)
                    await inviter_user.send(
                        f"**{invitee_name}** has declined your party invite."
                    )
                except Exception:
                    logger.warning(
                        f"Could not notify inviter {inviter_uid} about decline"
                    )


def register_party_command(tree: app_commands.CommandTree) -> None:
    tree.add_command(party_group)
