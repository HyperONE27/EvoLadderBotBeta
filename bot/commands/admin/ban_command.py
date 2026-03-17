import structlog
import discord
from discord import app_commands

from bot.components.buttons import ConfirmButton, CancelButton
from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_admin

logger = structlog.get_logger(__name__)

# ----------
# Components
# ----------

# --- Embeds ---


class BanPreviewEmbed(discord.Embed):
    def __init__(self, target: discord.User) -> None:
        super().__init__(
            title="⚠️ Toggle Ban",
            description=(
                f"You are about to toggle the ban status for:\n\n"
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n\n"
                "If the user is currently **unbanned**, they will be **banned**.\n"
                "If the user is currently **banned**, they will be **unbanned**.\n\n"
                "Please confirm below."
            ),
            color=discord.Color.orange(),
        )


class BanSuccessEmbed(discord.Embed):
    def __init__(self, target: discord.User, new_is_banned: bool) -> None:
        action = "banned" if new_is_banned else "unbanned"
        emoji = "🔨" if new_is_banned else "✅"
        color = discord.Color.red() if new_is_banned else discord.Color.green()
        super().__init__(
            title=f"{emoji} User {action.title()}",
            description=(
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Status:** {action.upper()}"
            ),
            color=color,
        )


# --- Views ---


class BanConfirmView(discord.ui.View):
    def __init__(self, caller_id: int, target: discord.User) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    "You cannot use this button.", ephemeral=True
                )
                return
            await _send_ban_request(interaction, target)

        self.add_item(ConfirmButton(callback=on_confirm))
        self.add_item(CancelButton())


# ----------------
# Internal helpers
# ----------------


async def _send_ban_request(
    interaction: discord.Interaction,
    target: discord.User,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/admin/ban",
        json={"discord_uid": target.id},
    ) as response:
        data = await response.json()

    if not data.get("success"):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ Error",
                description="Failed to toggle ban status. The user may not have a profile.",
                color=discord.Color.red(),
            ),
            view=None,
        )
        return

    new_is_banned: bool = data["new_is_banned"]
    logger.info(
        f"Admin {interaction.user.name} ({interaction.user.id}) toggled ban for "
        f"{target.name} ({target.id}): is_banned={new_is_banned}"
    )
    await interaction.response.edit_message(
        embed=BanSuccessEmbed(target, new_is_banned),
        view=None,
    )


# --------------------
# Command registration
# --------------------


def register_admin_ban_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="ban", description="[Admin] Toggle a user's ban status")
    @app_commands.check(check_if_admin)
    async def ban_command(
        interaction: discord.Interaction,
        user: discord.User,
    ) -> None:
        await interaction.response.defer()
        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /ban for {user.name} ({user.id})"
        )
        await interaction.followup.send(
            embed=BanPreviewEmbed(user),
            view=BanConfirmView(interaction.user.id, user),
        )
