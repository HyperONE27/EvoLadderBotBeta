import aiohttp

_session: aiohttp.ClientSession | None = None


def get_session() -> aiohttp.ClientSession:
    if _session is None:
        raise RuntimeError("HTTP session not initialized")
    return _session


async def init_session() -> None:
    global _session
    if _session is not None:
        return
    _session = aiohttp.ClientSession()


async def close_session() -> None:
    global _session
    if _session:
        await _session.close()
        _session = None
