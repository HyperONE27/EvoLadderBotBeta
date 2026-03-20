import discord
import structlog
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_cache
from bot.core.http import get_session
from common.i18n import t

logger = structlog.get_logger(__name__)

# --- Checks ---


def check_if_dm(interaction: discord.Interaction) -> bool:
    if (
        interaction.channel is None
        or interaction.channel.type != discord.ChannelType.private
    ):
        raise NotInDMError()
    return True


async def check_if_banned(interaction: discord.Interaction) -> bool:
    """Hit GET /players/{uid} and check is_banned. Async check."""
    uid = interaction.user.id
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{uid}") as resp:
            data = await resp.json()
    except Exception:
        # If the backend is unreachable, don't block the user.
        return True

    player = data.get("player")
    if player is not None:
        language = player.get("language")
        if language:
            get_cache().player_locales[uid] = language
        if player.get("is_banned"):
            raise BannedError()
    return True


async def check_if_accepted_tos(interaction: discord.Interaction) -> bool:
    """Hit GET /players/{uid} and check accepted_tos. Async check."""
    uid = interaction.user.id
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{uid}") as resp:
            data = await resp.json()
    except Exception:
        return True

    player = data.get("player")
    if player is None or not player.get("accepted_tos"):
        raise NotAcceptedTosError()
    return True


async def check_if_completed_setup(interaction: discord.Interaction) -> bool:
    """Hit GET /players/{uid} and check completed_setup. Async check."""
    uid = interaction.user.id
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{uid}") as resp:
            data = await resp.json()
    except Exception:
        return True

    player = data.get("player")
    if player is None or not player.get("completed_setup"):
        raise NotCompletedSetupError()
    return True


async def check_if_queueing(interaction: discord.Interaction) -> bool:
    """Hit GET /players/{uid} and check player_status is not 'queueing'. Async check."""
    uid = interaction.user.id
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{uid}") as resp:
            data = await resp.json()
    except Exception:
        return True

    player = data.get("player")
    if player is not None and player.get("player_status") == "queueing":
        raise AlreadyQueueingError()
    return True


async def check_if_admin(interaction: discord.Interaction) -> bool:
    """Hit GET /admins/{uid} and check role is not 'inactive'."""
    uid = interaction.user.id
    try:
        async with get_session().get(f"{BACKEND_URL}/admins/{uid}") as resp:
            data = await resp.json()
    except Exception:
        raise NotAdminError()

    admin = data.get("admin")
    if admin is None or admin.get("role") == "inactive":
        raise NotAdminError()
    return True


async def check_if_name_unique(
    player_name: str, exclude_discord_uid: int, locale: str
) -> None:
    """Raise NameNotUniqueError if player_name is already used by another account."""
    try:
        async with get_session().get(
            f"{BACKEND_URL}/players/player_name_availability",
            params={
                "player_name": player_name,
                "exclude_discord_uid": exclude_discord_uid,
            },
        ) as resp:
            if resp.status != 200:
                logger.warning(
                    "player_name_availability_non_200",
                    status=resp.status,
                    player_name=player_name,
                )
                return
            data = await resp.json()
    except Exception:
        logger.warning(
            "player_name_availability_request_failed",
            player_name=player_name,
            exc_info=True,
        )
        return
    if not data.get("available", True):
        raise NameNotUniqueError(
            t("setup_validation_error_embed.error.player_name_taken", locale)
        )


async def check_if_owner(interaction: discord.Interaction) -> bool:
    """Hit GET /admins/{uid} and check role is 'owner'."""
    uid = interaction.user.id
    try:
        async with get_session().get(f"{BACKEND_URL}/admins/{uid}") as resp:
            data = await resp.json()
    except Exception:
        raise NotOwnerError()

    admin = data.get("admin")
    if admin is None or admin.get("role") != "owner":
        raise NotOwnerError()
    return True


# --- Errors ---


class NotInDMError(app_commands.CheckFailure):
    def __init__(self) -> None:
        super().__init__("This command can only be used in DMs.")


class BannedError(app_commands.CheckFailure):
    def __init__(self) -> None:
        super().__init__(
            "Your account has been banned. You cannot use bot commands.\n"
            "If you believe this is an error, please contact an admin."
        )


class NotAdminError(app_commands.CheckFailure):
    def __init__(self) -> None:
        super().__init__("This command is restricted to administrators.")


class NotOwnerError(app_commands.CheckFailure):
    def __init__(self) -> None:
        super().__init__("This command is restricted to bot owners.")


class NotAcceptedTosError(app_commands.CheckFailure):
    def __init__(self) -> None:
        super().__init__(
            "You must accept the Terms of Service before using this command.\n"
            "Use `/termsofservice` to review and accept them."
        )


class NotCompletedSetupError(app_commands.CheckFailure):
    def __init__(self) -> None:
        super().__init__(
            "You must complete your player setup before using this command.\n"
            "Use `/setup` to configure your profile."
        )


class AlreadyQueueingError(app_commands.CheckFailure):
    def __init__(self) -> None:
        super().__init__("You are already in the queue.")


class NameNotUniqueError(app_commands.CheckFailure):
    """Chosen player_name is already registered to another Discord account."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
