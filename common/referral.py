"""Referral code utilities.

Each player's referral code is their Discord UID encoded as a 16-character
uppercase hex string with dashes every 4 characters:
    XXXX-XXXX-XXXX-XXXX

Discord snowflakes are 64-bit (8 bytes = 16 hex digits), so they always fit
exactly. Shorter UIDs are zero-padded on the left.
"""


def uid_to_code(discord_uid: int) -> str:
    """Convert a Discord UID to a formatted referral code."""
    hex_str = format(discord_uid, "016X")
    return f"{hex_str[0:4]}-{hex_str[4:8]}-{hex_str[8:12]}-{hex_str[12:16]}"


def code_to_uid(code: str) -> int | None:
    """Convert a referral code to a Discord UID.

    Accepts codes with or without dashes. Returns None if the code is
    not a valid 16-character uppercase hex string.
    """
    stripped = code.replace("-", "").upper()
    if len(stripped) != 16:
        return None
    try:
        return int(stripped, 16)
    except ValueError:
        return None
