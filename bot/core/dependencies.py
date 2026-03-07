from bot.core.bootstrap import Bot

_bot: Bot | None = None


def set_bot(app: Bot) -> None:
    global _bot
    _bot = app


def get_bot() -> Bot:
    if _bot is None:
        raise RuntimeError("Bot not initialized")
    return _bot
