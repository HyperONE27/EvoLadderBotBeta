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


class StatusResetPreviewEmbed(discord.Embed):
    def __init__(self, target: discord.User) -> None:
        super().__init__(
            title="⚠️ Admin: Confirm Status Reset",
            description=(
                f"**Player:** {target.mention} (`{target.name}` / `{target.id}`)\n\n"
                "This will reset the player's state to **idle**, clearing their "
                "current match mode and match ID. Use this to fix stuck players.\n\n"
                "Confirm?"
            ),
            color=discord.Color.orange(),
        )


class StatusResetSuccessEmbed(discord.Embed):
    def __init__(
        self,
        target: discord.User,
        old_status: str | None,
        admin: discord.User | discord.Member,
    ) -> None:
        super().__init__(
            title="✅ Admin: Player Status Reset",
            description=(
                f"**Player:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Previous State:** `{old_status or 'unknown'}`\n"
                f"**New State:** `idle`"
            ),
            color=discord.Color.green(),
        )
        self.add_field(name="👤 Admin", value=admin.name, inline=True)


# --- Views ---


class StatusResetConfirmView(discord.ui.View):
    def __init__(self, caller_id: int, target: discord.User) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    "You cannot use this button.", ephemeral=True
                )
                return
            await _send_statusreset_request(interaction, target)

        self.add_item(ConfirmButton(callback=on_confirm))
        self.add_item(CancelButton())


# ----------------
# Internal helpers
# ----------------


async def _send_statusreset_request(
    interaction: discord.Interaction,
    target: discord.User,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/admin/statusreset",
        json={"discord_uid": target.id},
    ) as response:
        data = await response.json()

    if not data.get("success"):
        error = data.get("error") or "An unexpected error occurred."
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ Admin: Status Reset Failed",
                description=f"Error: {error}",
                color=discord.Color.red(),
            ),
            view=None,
        )
        return

    old_status = data.get("old_status")
    logger.info(
        f"Admin {interaction.user.name} ({interaction.user.id}) reset status for "
        f"{target.name} ({target.id}): {old_status} -> idle"
    )

    await interaction.response.edit_message(
        embed=StatusResetSuccessEmbed(target, old_status, interaction.user),
        view=None,
    )


# --------------------
# Command registration
# --------------------


def register_admin_statusreset_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="statusreset",
        description="[Admin] Reset a player's status to idle (fixes stuck players)",
    )
    @app_commands.check(check_if_admin)
    async def statusreset_command(
        interaction: discord.Interaction,
        user: discord.User,
    ) -> None:
        await interaction.response.defer()
        logger.info(
            f"Admin {interaction.user.name} ({interaction.user.id}) "
            f"invoked /statusreset for {user.name} ({user.id})"
        )
        await interaction.followup.send(
            embed=StatusResetPreviewEmbed(user),
            view=StatusResetConfirmView(interaction.user.id, user),
        )
