import structlog
import discord
from discord import app_commands

from bot.components.buttons import ConfirmButton
from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_dm

logger = structlog.get_logger(__name__)

# ----------
# Components
# ----------

# --- Embeds ---


class TermsOfServiceEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="📜 Terms of Service",
            description=(
                "Please read our Terms of Service, User Conduct guidelines, Privacy Policy, and Refund Policy. **You must accept these terms in order to use the SC: Evo Complete Ladder Bot.**\n\n"
                "**Official Terms of Service:**\n"
                "🔗 [SC: Evo Ladder ToS](https://www.scevo.net/ladder/tos)\n"
                "🔗 [EvoLadderBot ToS (Mirror)](https://rentry.co/evoladderbot-tos)\n\n"
                "By clicking **✅ I Accept These Terms** below, you confirm that you have read and agree to abide by the Terms of Service. "
                "You can withdraw your agreement to these terms at any time by using this command again and clicking **❌ I Decline These Terms** below.\n\n"
                "**⚠️ Failure to read or understand these terms is NOT AN ACCEPTABLE DEFENSE for violating them, and may result in your removal from the Service.**"
            ),
            color=discord.Color.blue(),
        )


class TermsOfServiceAcceptedEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="✅ Terms of Service Accepted",
            description=(
                "Thank you for agreeing to the Terms of Service. "
                "Welcome to the SC: Evo Complete Ladder Bot!"
            ),
            color=discord.Color.green(),
        )


class TermsOfServiceDeclinedEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="❌ Terms of Service Declined",
            description=(
                "You have declined the Terms of Service. "
                "As such, you may not use the SC: Evo Complete Ladder Bot."
            ),
            color=discord.Color.red(),
        )


# --- Views ---


class TermsOfServiceView(discord.ui.View):
    def __init__(self, discord_uid: int, discord_username: str) -> None:
        super().__init__()

        async def on_accept(interaction: discord.Interaction) -> None:
            logger.info(
                f"User {discord_username} ({discord_uid}) accepting Terms of Service"
            )
            await _send_tos_request(
                interaction, discord_uid, discord_username, accepted=True
            )

        async def on_decline(interaction: discord.Interaction) -> None:
            logger.info(
                f"User {discord_username} ({discord_uid}) declining Terms of Service"
            )
            await _send_tos_request(
                interaction, discord_uid, discord_username, accepted=False
            )

        self.add_item(ConfirmButton(label="Accept", callback=on_accept))
        self.add_item(
            ConfirmButton(
                label="Decline",
                callback=on_decline,
                style=discord.ButtonStyle.red,
                emoji="✖️",
            )
        )


# ----------------
# Internal helpers
# ----------------


async def _send_tos_request(
    interaction: discord.Interaction,
    discord_uid: int,
    discord_username: str,
    accepted: bool,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/commands/termsofservice",
        json={
            "discord_uid": discord_uid,
            "discord_username": discord_username,
            "accepted": accepted,
        },
    ) as response:
        data = await response.json()

    if not data.get("success"):
        logger.error(
            f"TOS upsert failed for {discord_username} ({discord_uid}): {data.get('message')}"
        )
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ Error",
                description=data.get("message") or "An unexpected error occurred.",
                color=discord.Color.red(),
            ),
            view=None,
        )
        return

    logger.info(
        f"TOS upsert succeeded for {discord_username} ({discord_uid}): accepted={accepted}"
    )
    embed = TermsOfServiceAcceptedEmbed() if accepted else TermsOfServiceDeclinedEmbed()
    await interaction.response.edit_message(embed=embed, view=None)


# --------------------
# Command registration
# --------------------


def register_termsofservice_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="termsofservice", description="View and accept the Terms of Service"
    )
    @app_commands.check(check_if_dm)
    async def termsofservice_command(interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        discord_uid = interaction.user.id
        discord_username = interaction.user.name
        logger.info(f"User {discord_username} ({discord_uid}) opened Terms of Service")
        await interaction.followup.send(
            embed=TermsOfServiceEmbed(),
            view=TermsOfServiceView(discord_uid, discord_username),
        )
