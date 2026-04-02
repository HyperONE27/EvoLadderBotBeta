from datetime import datetime

import discord
import structlog
from discord import app_commands

from bot.core.config import BACKEND_URL
from bot.core.dependencies import get_cache
from bot.core.http import get_session
from common.datetime_helpers import ensure_utc, utc_now
from common.i18n import t

logger = structlog.get_logger(__name__)

# --- Helpers ---


async def _ensure_locale_cached(
    uid: int, player: dict[str, object] | None = None
) -> None:
    """Cache the player's locale if not already present.

    If *player* is provided (already fetched by the caller), extract the
    language from it directly.  Otherwise fetch ``GET /players/{uid}``
    on a cache miss.  Fail-open: defaults to ``enUS`` on error.
    """
    if uid in get_cache().player_locales:
        return

    if player is None:
        try:
            async with get_session().get(f"{BACKEND_URL}/players/{uid}") as resp:
                data = await resp.json()
            player = data.get("player")
        except Exception:
            return

    if player is not None:
        language = player.get("language")
        if language:
            get_cache().player_locales[uid] = language  # type: ignore[assignment]


# --- Checks ---


def check_if_dm(interaction: discord.Interaction) -> bool:
    if (
        interaction.channel is None
        or interaction.channel.type != discord.ChannelType.private
    ):
        raise NotInDMError()
    return True


async def check_player(
    interaction: discord.Interaction,
    *,
    banned: bool = True,
    accepted_tos: bool = False,
    completed_setup: bool = False,
    not_queueing: bool = False,
    not_timed_out: bool = False,
) -> None:
    """Single ``GET /players/{uid}`` fetch, validate multiple conditions.

    Always caches the player dict in ``Cache.player_presets`` and locale in
    ``Cache.player_locales``.  Fail-open on network errors.
    """
    uid = interaction.user.id
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{uid}") as resp:
            data = await resp.json()
    except Exception:
        return  # fail-open

    player = data.get("player")
    if player is not None:
        await _ensure_locale_cached(uid, player)
        get_cache().player_presets[uid] = player

    if banned and player is not None and player.get("is_banned"):
        raise BannedError()
    if accepted_tos and (player is None or not player.get("accepted_tos")):
        raise NotAcceptedTosError()
    if completed_setup and (player is None or not player.get("completed_setup")):
        raise NotCompletedSetupError()
    if (
        not_queueing
        and player is not None
        and player.get("player_status") == "queueing"
    ):
        raise AlreadyQueueingError()
    if not_timed_out and player is not None:
        timeout_until_raw = player.get("timeout_until")
        if timeout_until_raw is not None:
            timeout_until = ensure_utc(timeout_until_raw)
            if timeout_until is not None and utc_now() < timeout_until:
                raise PlayerTimedOutError(timeout_until)


async def check_if_queueing(interaction: discord.Interaction) -> bool:
    """Hit GET /players/{uid} and check player_status is not 'queueing'. Async check.

    Kept as a standalone function for inline use in view button callbacks.
    """
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


async def check_admin(
    interaction: discord.Interaction,
    *,
    owner: bool = False,
) -> None:
    """Single ``GET /admins/{uid}`` fetch, validate admin or owner role."""
    uid = interaction.user.id
    try:
        async with get_session().get(f"{BACKEND_URL}/admins/{uid}") as resp:
            data = await resp.json()
    except Exception:
        raise NotOwnerError() if owner else NotAdminError()

    admin = data.get("admin")
    if owner:
        if admin is None or admin.get("role") != "owner":
            raise NotOwnerError()
    else:
        if admin is None or admin.get("role") == "inactive":
            raise NotAdminError()

    await _ensure_locale_cached(uid)


async def check_if_name_unique(
    player_name: str, exclude_discord_uid: int, locale: str
) -> None:
    """Raise NameNotUniqueError if player_name is already used by another account.

    Fail-open: if the backend is unreachable or returns a non-200, the check
    passes silently rather than blocking the /setup flow.  This matches the
    pattern used by check_if_banned, check_if_accepted_tos, etc.  Duplicate
    names are non-critical and can be resolved by admins.
    """
    try:
        async with get_session().get(
            f"{BACKEND_URL}/players/player_name_availability",
            params={
                "player_name": player_name,
                "exclude_discord_uid": exclude_discord_uid,
            },
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning(
                    "player_name_availability_non_200",
                    status=resp.status,
                    body=body,
                    player_name=player_name,
                )
                return  # fail-open
            data = await resp.json()
    except Exception:
        logger.warning(
            "player_name_availability_request_failed",
            player_name=player_name,
            exc_info=True,
        )
        return  # fail-open
    if not data.get("available", True):
        raise NameNotUniqueError(
            t("setup_validation_error_embed.error.player_name_taken", locale)
        )


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
            "Use `/setup` to review and accept them."
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


class PlayerTimedOutError(app_commands.CheckFailure):
    """Player is serving a timeout penalty from aborting or abandoning a match."""

    def __init__(self, timeout_until: datetime) -> None:
        self.timeout_until = timeout_until
        super().__init__("You are currently timed out from queueing.")


class NameNotUniqueError(app_commands.CheckFailure):
    """Chosen player_name is already registered to another Discord account."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
