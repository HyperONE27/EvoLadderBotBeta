"""
Startup role backfill and helpers for granting/removing the ladder player role.

The ladder player role is granted to all non-banned players who have accepted
the Terms of Service. It is toggled on ban/unban and granted on ToS acceptance.
"""

import asyncio
from collections.abc import Coroutine
from functools import partial
from typing import Any

import discord
import structlog

from bot.core.config import BACKEND_URL, LADDER_PLAYER_ROLE_ID, SERVER_GUILD_ID
from bot.core.http import get_session
from bot.core.queues import get_role_queue

logger = structlog.get_logger(__name__)


def _get_role(client: discord.Client) -> discord.Role | None:
    """Resolve the ladder player role object, or None if not configured."""
    if LADDER_PLAYER_ROLE_ID is None:
        return None
    guild = client.get_guild(SERVER_GUILD_ID)
    if guild is None:
        logger.warning("[RoleSync] Guild not found in cache")
        return None
    role = guild.get_role(LADDER_PLAYER_ROLE_ID)
    if role is None:
        logger.warning(f"[RoleSync] Role {LADDER_PLAYER_ROLE_ID} not found in guild")
    return role


def _add_role_op(
    member: discord.Member, role: discord.Role, reason: str
) -> Coroutine[Any, Any, None]:
    return member.add_roles(role, reason=reason)


def _remove_role_op(
    member: discord.Member, role: discord.Role, reason: str
) -> Coroutine[Any, Any, None]:
    return member.remove_roles(role, reason=reason)


async def grant_role(client: discord.Client, discord_uid: int) -> None:
    """Enqueue a role-add for the given user. No-op if role not configured."""
    role = _get_role(client)
    if role is None:
        return
    guild = client.get_guild(SERVER_GUILD_ID)
    if guild is None:
        return
    member = guild.get_member(discord_uid)
    if member is None:
        return
    if role in member.roles:
        return
    rq = get_role_queue()
    await rq.enqueue(partial(_add_role_op, member, role, "Ladder: ToS accepted"))


async def remove_role(client: discord.Client, discord_uid: int) -> None:
    """Enqueue a role-remove for the given user. No-op if role not configured."""
    role = _get_role(client)
    if role is None:
        return
    guild = client.get_guild(SERVER_GUILD_ID)
    if guild is None:
        return
    member = guild.get_member(discord_uid)
    if member is None:
        return
    if role not in member.roles:
        return
    rq = get_role_queue()
    await rq.enqueue(partial(_remove_role_op, member, role, "Ladder: banned"))


async def backfill_roles(client: discord.Client) -> None:
    """Fetch all eligible UIDs from backend and enqueue role grants for those missing it."""
    if LADDER_PLAYER_ROLE_ID is None:
        return

    role = _get_role(client)
    if role is None:
        return

    guild = client.get_guild(SERVER_GUILD_ID)
    if guild is None:
        return

    try:
        async with get_session().get(
            f"{BACKEND_URL}/players/eligible_role_uids"
        ) as resp:
            if resp.status >= 400:
                logger.error(f"[RoleSync] Backend returned {resp.status}")
                return
            data = await resp.json()
    except Exception:
        logger.exception("[RoleSync] Failed to fetch eligible UIDs")
        return

    uids: list[int] = data.get("discord_uids", [])
    rq = get_role_queue()
    enqueued = 0

    # Ensure the full member list is cached — Discord only sends all members
    # automatically for small guilds (<75 members).  Requires members intent.
    if not guild.chunked:
        await guild.chunk()

    for uid in uids:
        member = guild.get_member(uid)
        if member is None:
            continue
        if role in member.roles:
            continue
        await rq.enqueue(partial(_add_role_op, member, role, "Ladder: backfill"))
        enqueued += 1
        # Yield to event loop periodically to avoid blocking.
        if enqueued % 50 == 0:
            await asyncio.sleep(0)

    logger.info(f"[RoleSync] Backfill enqueued {enqueued} role grants")
