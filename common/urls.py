"""
External URLs referenced by both the backend and bot processes.

Backend modules should import these values via ``backend.core.config``,
and bot modules via ``bot.core.config`` — never directly from this module.
"""

QUICKSTART_URL: str = "https://rentry.co/evoladderbot-quickstartguide"

TOS_URL: str = "https://www.scevo.net/ladder/tos"

TOS_MIRROR_URL: str = "https://rentry.co/evoladderbot-tos"

DISCORD_INVITE_URL: str = "https://discord.gg/fDvwdnkDeB"
