from bot.core.bootstrap import Bot, Cache

_bot: Bot | None = None
_cache: Cache | None = None


def set_bot(app: Bot) -> None:
    global _bot
    _bot = app


def get_bot() -> Bot:
    if _bot is None:
        raise RuntimeError("Bot not initialized")
    return _bot


def get_cache() -> Cache:
    if _bot is None:
        raise RuntimeError("Bot not initialized")
    if _bot.cache is None:
        raise RuntimeError("Cache not initialized")
    return _bot.cache
