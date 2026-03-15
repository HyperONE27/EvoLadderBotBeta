import discord

from common.json_types import Emote
from common.lookups.emote_lookups import get_emote_by_name
from common.lookups.race_lookups import get_races


def _get_emote(name: str) -> Emote:
    emote = get_emote_by_name(name)
    if emote is None:
        raise ValueError(f"Emote not found: {name!r}")
    return emote


def _flag_emoji(code: str) -> str | discord.PartialEmoji | None:
    """Convert a country code to an emoji usable in both embed text and SelectOption.

    - Standard 2-letter ISO codes → Unicode regional-indicator string (e.g. 🇺🇸).
    - Special codes XX/ZZ → PartialEmoji parsed from the custom guild emote markdown.
    - Anything else → None.
    """
    if code == "XX":
        return _get_emote("flag_xx")["markdown"]
    if code == "ZZ":
        return _get_emote("flag_zz")["markdown"]
    if len(code) == 2 and code.isascii() and code.isalpha():
        return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)
    return None


def get_flag_emote(country_code: str) -> str | discord.PartialEmoji:
    emoji = _flag_emoji(country_code)
    if emoji is not None:
        return emoji
    return f":flag_{country_code.lower()}:"


def get_game_emote(game: str) -> str:
    if game.lower() != "bw" and game.lower() != "sc2":
        raise ValueError(f"Invalid game: {game!r}, expected 'bw' or 'sc2'")
    return _get_emote(f"{game.lower()}_logo")["markdown"]


def get_globe_emote(region_code: str) -> str:
    globe_emotes = {"AM": "🌎", "AF": "🌍", "AS": "🌏"}

    return globe_emotes.get(region_code, "🌐")


def get_race_emote(race: str) -> str:
    if race.lower() not in get_races().keys():
        raise ValueError(f"Invalid race: {race!r}")
    return _get_emote(race.lower())["markdown"]


def get_rank_emote(rank: str) -> str:
    if len(rank) != 1:
        raise ValueError(f"Invalid rank: {rank!r}, expected a single character")
    return _get_emote(f"{rank.lower()}_rank")["markdown"]
