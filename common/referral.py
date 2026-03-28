"""Referral code utilities.

Each player's referral code is their Discord UID encoded as an 11-character
base62 string (digits 0-9, uppercase A-Z, lowercase a-z), left-padded with
'0'. Discord snowflakes are 64-bit unsigned integers; the maximum value
(2^64 - 1) encodes to exactly 11 base62 characters.
"""

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BASE = len(_ALPHABET)  # 62
_CODE_LENGTH = 11  # ceil(log62(2^64)) = 11

_DECODE_MAP: dict[str, int] = {ch: i for i, ch in enumerate(_ALPHABET)}


def uid_to_code(discord_uid: int) -> str:
    """Convert a Discord UID to an 11-character base62 referral code."""
    if discord_uid < 0:
        msg = "discord_uid must be non-negative"
        raise ValueError(msg)
    n = discord_uid
    chars: list[str] = []
    while n:
        n, remainder = divmod(n, _BASE)
        chars.append(_ALPHABET[remainder])
    # Reverse (most-significant digit first) and left-pad to fixed width.
    return "".join(reversed(chars)).rjust(_CODE_LENGTH, "0")


def code_to_uid(code: str) -> int | None:
    """Convert a base62 referral code to a Discord UID.

    Returns None if the code contains invalid characters or exceeds 11
    characters.
    """
    stripped = code.strip()
    if not stripped or len(stripped) > _CODE_LENGTH:
        return None
    result = 0
    for ch in stripped:
        val = _DECODE_MAP.get(ch)
        if val is None:
            return None
        result = result * _BASE + val
    return result
