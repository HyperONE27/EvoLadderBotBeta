"""
Wrapper functions that route non-interaction Discord API calls through the
message queue.

Interaction endpoints (response.send_message, response.defer, followup.send,
edit_original_response, etc.) are NOT rate-limited by Discord's global gateway
limit and must NOT be routed through this queue — call them directly.

High-priority wrappers — player is actively waiting:
    queue_user_send_high, queue_message_reply_high, queue_message_edit_high,
    queue_message_delete_high

Low-priority wrappers — background / non-urgent:
    queue_user_send_low, queue_channel_send_low, queue_message_edit_low,
    queue_message_delete_low, queue_message_reply_low
"""

from __future__ import annotations

from typing import Any

import discord

from bot.core.queues import get_message_queue

# Sentinel to distinguish "not provided" from None in message edits.
MISSING: Any = object()


# ======================================================================
# High-priority wrappers (player actively waiting)
# ======================================================================


async def queue_user_send_high(
    user: discord.User | discord.Member,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | discord.ui.LayoutView | None = None,
    **kwargs: Any,
) -> discord.Message:
    queue = get_message_queue()

    async def operation() -> discord.Message:
        send_kwargs: dict[str, Any] = {**kwargs}
        if content is not None:
            send_kwargs["content"] = content
        if embed is not None:
            send_kwargs["embed"] = embed
        if view is not None:
            send_kwargs["view"] = view
        return await user.send(**send_kwargs)

    future = await queue.enqueue_high(operation)
    return await future


async def queue_message_reply_high(
    message: discord.Message,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | discord.ui.LayoutView | None = None,
    **kwargs: Any,
) -> discord.Message:
    queue = get_message_queue()

    async def operation() -> discord.Message:
        reply_kwargs: dict[str, Any] = {**kwargs}
        if content is not None:
            reply_kwargs["content"] = content
        if embed is not None:
            reply_kwargs["embed"] = embed
        if view is not None:
            reply_kwargs["view"] = view
        return await message.reply(**reply_kwargs)

    future = await queue.enqueue_high(operation)
    return await future


async def queue_message_edit_high(
    message: discord.Message,
    content: Any = MISSING,
    embed: Any = MISSING,
    view: Any = MISSING,
    **kwargs: Any,
) -> discord.Message:
    queue = get_message_queue()

    async def operation() -> discord.Message:
        edit_kwargs: dict[str, Any] = {}
        if content is not MISSING:
            edit_kwargs["content"] = content
        if embed is not MISSING:
            edit_kwargs["embed"] = embed
        if view is not MISSING:
            edit_kwargs["view"] = view
        edit_kwargs.update(kwargs)
        return await message.edit(**edit_kwargs)

    future = await queue.enqueue_high(operation)
    return await future


async def queue_message_delete_high(
    message: discord.Message,
    **kwargs: Any,
) -> None:
    queue = get_message_queue()

    async def operation() -> object:
        await message.delete(**kwargs)
        return None

    future = await queue.enqueue_high(operation)
    await future


# ======================================================================
# Low-priority wrappers (background / non-urgent)
# ======================================================================


async def queue_user_send_low(
    user: discord.User | discord.Member,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | discord.ui.LayoutView | None = None,
    **kwargs: Any,
) -> discord.Message:
    queue = get_message_queue()

    async def operation() -> discord.Message:
        send_kwargs: dict[str, Any] = {**kwargs}
        if content is not None:
            send_kwargs["content"] = content
        if embed is not None:
            send_kwargs["embed"] = embed
        if view is not None:
            send_kwargs["view"] = view
        return await user.send(**send_kwargs)

    future = await queue.enqueue_low(operation)
    return await future


async def queue_channel_send_low(
    channel: discord.abc.Messageable,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | discord.ui.LayoutView | None = None,
    **kwargs: Any,
) -> discord.Message:
    queue = get_message_queue()

    async def operation() -> discord.Message:
        send_kwargs: dict[str, Any] = {**kwargs}
        if content is not None:
            send_kwargs["content"] = content
        if embed is not None:
            send_kwargs["embed"] = embed
        if view is not None:
            send_kwargs["view"] = view
        return await channel.send(**send_kwargs)

    future = await queue.enqueue_low(operation)
    return await future


async def queue_message_edit_low(
    message: discord.Message | discord.PartialMessage,
    content: Any = MISSING,
    embed: Any = MISSING,
    view: Any = MISSING,
    **kwargs: Any,
) -> discord.Message:
    queue = get_message_queue()

    async def operation() -> discord.Message:
        edit_kwargs: dict[str, Any] = {}
        if content is not MISSING:
            edit_kwargs["content"] = content
        if embed is not MISSING:
            edit_kwargs["embed"] = embed
        if view is not MISSING:
            edit_kwargs["view"] = view
        edit_kwargs.update(kwargs)
        return await message.edit(**edit_kwargs)

    future = await queue.enqueue_low(operation)
    return await future


async def queue_message_delete_low(
    message: discord.Message,
    **kwargs: Any,
) -> None:
    queue = get_message_queue()

    async def operation() -> object:
        await message.delete(**kwargs)
        return None

    future = await queue.enqueue_low(operation)
    await future


async def queue_message_reply_low(
    message: discord.Message,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | discord.ui.LayoutView | None = None,
    **kwargs: Any,
) -> discord.Message:
    queue = get_message_queue()

    async def operation() -> discord.Message:
        reply_kwargs: dict[str, Any] = {**kwargs}
        if content is not None:
            reply_kwargs["content"] = content
        if embed is not None:
            reply_kwargs["embed"] = embed
        if view is not None:
            reply_kwargs["view"] = view
        return await message.reply(**reply_kwargs)

    future = await queue.enqueue_low(operation)
    return await future
