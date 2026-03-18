import structlog
import discord
from discord import app_commands

from bot.components.buttons import ConfirmButton, CancelButton
from bot.components.embeds import ErrorEmbed
from bot.core.config import BACKEND_URL
from bot.core.http import get_session
from bot.helpers.checks import check_if_owner

logger = structlog.get_logger(__name__)

# ----------
# Components
# ----------

# --- Embeds ---


class ToggleAdminPreviewEmbed(discord.Embed):
    def __init__(self, target: discord.User) -> None:
        super().__init__(
            title="⚠️ Toggle Admin Role",
            description=(
                f"You are about to toggle the admin role for:\n\n"
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n\n"
                "- If the user is **not an admin**, they will be **promoted to admin**.\n"
                "- If the user is an **active admin**, they will be **demoted to inactive**.\n"
                "- If the user is **inactive**, they will be **re-promoted to admin**.\n"
                "- **Owners cannot be demoted** through this command.\n\n"
                "Please confirm below."
            ),
            color=discord.Color.orange(),
        )


class ToggleAdminSuccessEmbed(discord.Embed):
    def __init__(self, target: discord.User, action: str, new_role: str) -> None:
        if action == "promoted":
            emoji = "⬆️"
            color = discord.Color.green()
        elif action == "demoted":
            emoji = "⬇️"
            color = discord.Color.orange()
        else:
            emoji = "➕"
            color = discord.Color.green()

        super().__init__(
            title=f"{emoji} Admin Role Updated",
            description=(
                f"**User:** {target.mention} (`{target.name}` / `{target.id}`)\n"
                f"**Action:** {action.title()}\n"
                f"**New Role:** `{new_role}`"
            ),
            color=color,
        )


# --- Views ---


class ToggleAdminConfirmView(discord.ui.View):
    def __init__(self, caller_id: int, target: discord.User) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    "You cannot use this button.", ephemeral=True
                )
                return
            await _send_toggle_admin_request(interaction, target)

        self.add_item(ConfirmButton(callback=on_confirm))
        self.add_item(CancelButton())


# ----------------
# Internal helpers
# ----------------


async def _send_toggle_admin_request(
    interaction: discord.Interaction,
    target: discord.User,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/owner/admin",
        json={
            "discord_uid": target.id,
            "discord_username": target.name,
        },
    ) as response:
        data = await response.json()

    if not data.get("success"):
        error = data.get("error") or "An unexpected error occurred."
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title="❌ Error",
                description=error,
            ),
            view=None,
        )
        return

    action = data.get("action") or "updated"
    new_role = data.get("new_role") or "unknown"

    logger.info(
        f"Owner {interaction.user.name} ({interaction.user.id}) toggled admin for "
        f"{target.name} ({target.id}): action={action}, new_role={new_role}"
    )

    await interaction.response.edit_message(
        embed=ToggleAdminSuccessEmbed(target, action, new_role),
        view=None,
    )


# --------------------
# Command registration
# --------------------


def register_owner_admin_command(tree: app_commands.CommandTree) -> None:
    @tree.command(name="admin", description="[Owner] Toggle a user's admin role")
    @app_commands.check(check_if_owner)
    async def admin_command(
        interaction: discord.Interaction,
        user: discord.User,
    ) -> None:
        await interaction.response.defer()
        logger.info(
            f"Owner {interaction.user.name} ({interaction.user.id}) "
            f"invoked /admin for {user.name} ({user.id})"
        )
        await interaction.followup.send(
            embed=ToggleAdminPreviewEmbed(user),
            view=ToggleAdminConfirmView(interaction.user.id, user),
        )
