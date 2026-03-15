import logging
import re
from typing import Any

import discord
from discord import app_commands

from bot.components.buttons import CancelButton, ConfirmButton, RestartButton
from bot.helpers.checks import check_if_dm
from bot.helpers.emotes import get_flag_emote, get_globe_emote
from bot.helpers.i18n import LOCALE_DISPLAY_NAMES, get_available_locales
from common.json_types import Country, GeographicRegion
from common.lookups.country_lookups import get_common_countries
from common.lookups.region_lookups import get_geographic_regions

log = logging.getLogger(__name__)

# ----------
# Components
# ----------

# --- Embeds ---

_COUNTRY_LIMIT_NOTE = (
    "**Due to Discord UI limitations, only 49 common nationalities are listed here.**\n"
    "- If your nationality is not listed, select **Other** (page 2), then use `/setcountry` "
    "to set your exact nationality.\n"
    "- If you are non-representing, select **Other** (page 2), then use `/setcountry` "
    "to select **Non-representing**."
)


class SetupIntroEmbed(discord.Embed):
    def __init__(self) -> None:
        super().__init__(
            title="⚙️ Player Setup",
            description=(
                "Welcome to EvoLadder! Click **Begin Setup** to configure your player profile.\n\n"
                "You will need to provide:\n"
                "- A **User ID** (your display name on the ladder)\n"
                "- Your **BattleTag** (e.g. `Username#1234`)\n"
                "- Your **nationality**, **location**, and **language**\n"
                "- Optional **alternative IDs**"
            ),
            color=discord.Color.blue(),
        )


class SetupValidationErrorEmbed(discord.Embed):
    def __init__(self, title: str, error: str) -> None:
        super().__init__(
            title=f"❌ {title}",
            description=f"**Error:** {error}\n\nPlease try again.",
            color=discord.Color.red(),
        )


class SetupSelectionEmbed(discord.Embed):
    def __init__(
        self,
        country: Country | None = None,
        region: GeographicRegion | None = None,
        language: str | None = None,
    ) -> None:
        super().__init__(
            title="⚙️ Setup — Nationality, Location & Language",
            color=discord.Color.blue(),
        )
        selected_lines: list[str] = []
        if country:
            selected_lines.append(
                f"- Nationality: {get_flag_emote(country['code'])} {country['name']}"
            )
        if region:
            selected_lines.append(
                f"- Location: {get_globe_emote(region['globe_emote_code'])} {region['name']}"
            )
        if language:
            entry = LOCALE_DISPLAY_NAMES.get(language)
            flag, display = (entry[1], entry[0]) if entry else ("", language)
            selected_lines.append(f"- Language: {flag} {display}")

        if selected_lines:
            selected_block = "**Selected:**\n" + "\n".join(selected_lines) + "\n\n"
        else:
            selected_block = ""

        if country and region and language:
            self.description = selected_block + "Click **Confirm** to proceed."
        else:
            missing: list[str] = []
            if not country:
                missing.append("nationality")
            if not region:
                missing.append("location")
            if not language:
                missing.append("language")
            self.description = (
                selected_block
                + f"Please select your {', '.join(missing)}.\n\n{_COUNTRY_LIMIT_NOTE}"
            )


class SetupPreviewEmbed(discord.Embed):
    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        country: Country,
        region: GeographicRegion,
        language: str,
    ) -> None:
        super().__init__(
            title="🔍 Preview Setup Information",
            description="Please review your setup information before confirming:",
            color=discord.Color.blue(),
        )
        self.add_field(name=":id: **User ID**", value=f"`{player_name}`", inline=False)
        self.add_field(
            name=":hash: **BattleTag**", value=f"`{battletag}`", inline=False
        )
        self.add_field(
            name=f"{get_flag_emote(country['code'])} **Nationality**",
            value=f"`{country['name']} ({country['code']})`",
            inline=False,
        )
        self.add_field(
            name=f"{get_globe_emote(region['globe_emote_code'])} **Location**",
            value=f"`{region['name']}`",
            inline=False,
        )
        self.add_field(
            name="🌐 **Language**",
            value=f"`{LOCALE_DISPLAY_NAMES[language][0] if language in LOCALE_DISPLAY_NAMES else language}`",
            inline=False,
        )
        alt_display = ", ".join(f"`{a}`" for a in alt_ids) if alt_ids else "None"
        self.add_field(name=":id: **Alternative IDs**", value=alt_display, inline=False)


class SetupSuccessEmbed(discord.Embed):
    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        country: Country,
        region: GeographicRegion,
        language: str,
    ) -> None:
        super().__init__(
            title="✅ Setup Complete!",
            description="Your player profile has been successfully configured.",
            color=discord.Color.green(),
        )
        self.add_field(name=":id: **User ID**", value=f"`{player_name}`", inline=False)
        self.add_field(
            name=":hash: **BattleTag**", value=f"`{battletag}`", inline=False
        )
        self.add_field(
            name=f"{get_flag_emote(country['code'])} **Nationality**",
            value=f"`{country['name']} ({country['code']})`",
            inline=False,
        )
        self.add_field(
            name=f"{get_globe_emote(region['globe_emote_code'])} **Location**",
            value=f"`{region['name']}`",
            inline=False,
        )
        self.add_field(
            name="🌐 **Language**",
            value=f"`{LOCALE_DISPLAY_NAMES[language][0] if language in LOCALE_DISPLAY_NAMES else language}`",
            inline=False,
        )
        alt_display = ", ".join(f"`{a}`" for a in alt_ids) if alt_ids else "None"
        self.add_field(name=":id: **Alternative IDs**", value=alt_display, inline=False)


# --- Views ---


class SetupIntroView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__()

        async def on_begin(interaction: discord.Interaction) -> None:
            log.debug(
                "SetupIntroView: begin setup clicked by user=%s", interaction.user.id
            )
            modal = SetupModal(message=interaction.message)
            await interaction.response.send_modal(modal)

        self.add_item(ConfirmButton(callback=on_begin, label="Begin Setup"))
        self.add_item(CancelButton())


class CountryPage1Select(discord.ui.Select):
    def __init__(self, countries: list[Country], selected_code: str | None) -> None:
        options = [
            discord.SelectOption(
                label=c["name"],
                value=c["code"],
                emoji=get_flag_emote(c["code"]),
                default=(c["code"] == selected_code),
            )
            for c in countries[:25]
        ]
        super().__init__(
            placeholder="Nationality (Page 1)…",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupSelectionView = self.view  # type: ignore[assignment]
        view.selected_country = next(
            c for c in view.countries if c["code"] == self.values[0]
        )
        view.country_page1_code = self.values[0]
        view.country_page2_code = None
        await view.refresh(interaction)


class CountryPage2Select(discord.ui.Select):
    def __init__(self, countries: list[Country], selected_code: str | None) -> None:
        options = [
            discord.SelectOption(
                label=c["name"],
                value=c["code"],
                emoji=get_flag_emote(c["code"]),
                default=(c["code"] == selected_code),
            )
            for c in countries[25:50]
        ]
        super().__init__(
            placeholder="Nationality (Page 2)…",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupSelectionView = self.view  # type: ignore[assignment]
        view.selected_country = next(
            c for c in view.countries if c["code"] == self.values[0]
        )
        view.country_page2_code = self.values[0]
        view.country_page1_code = None
        await view.refresh(interaction)


class RegionSelect(discord.ui.Select):
    def __init__(
        self, regions: list[GeographicRegion], selected_code: str | None
    ) -> None:
        options = [
            discord.SelectOption(
                label=r["name"],
                value=r["code"],
                emoji=get_globe_emote(r["globe_emote_code"]),
                default=(r["code"] == selected_code),
            )
            for r in regions
        ]
        super().__init__(
            placeholder="Location…",
            min_values=1,
            max_values=1,
            options=options,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupSelectionView = self.view  # type: ignore[assignment]
        view.selected_region = next(
            r for r in view.regions if r["code"] == self.values[0]
        )
        await view.refresh(interaction)


class LanguageSelect(discord.ui.Select):
    def __init__(self, locales: list[str], selected_code: str | None) -> None:
        options = [
            discord.SelectOption(
                label=LOCALE_DISPLAY_NAMES[code][0]
                if code in LOCALE_DISPLAY_NAMES
                else code,
                value=code,
                emoji=LOCALE_DISPLAY_NAMES[code][1]
                if code in LOCALE_DISPLAY_NAMES
                else None,
                default=(code == selected_code),
            )
            for code in locales
        ]
        super().__init__(
            placeholder="Language…",
            min_values=1,
            max_values=1,
            options=options,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: SetupSelectionView = self.view  # type: ignore[assignment]
        view.selected_language = self.values[0]
        await view.refresh(interaction)


class SetupSelectionView(discord.ui.View):
    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        message: discord.Message,
        selected_country: Country | None = None,
        selected_region: GeographicRegion | None = None,
        selected_language: str | None = None,
        country_page1_code: str | None = None,
        country_page2_code: str | None = None,
    ) -> None:
        super().__init__()
        self.player_name = player_name
        self.battletag = battletag
        self.alt_ids = alt_ids
        self.message = message
        self.selected_country = selected_country
        self.selected_region = selected_region
        self.selected_language = selected_language
        self.country_page1_code = country_page1_code
        self.country_page2_code = country_page2_code

        self.countries: list[Country] = sorted(
            get_common_countries().values(), key=lambda c: c["name"]
        )
        self.regions: list[GeographicRegion] = list(get_geographic_regions().values())
        self.locales: list[str] = get_available_locales()

        self._build()

    def _build(self) -> None:
        self.clear_items()

        self.add_item(CountryPage1Select(self.countries, self.country_page1_code))
        self.add_item(CountryPage2Select(self.countries, self.country_page2_code))
        self.add_item(
            RegionSelect(
                self.regions,
                self.selected_region["code"] if self.selected_region else None,
            )
        )
        self.add_item(LanguageSelect(self.locales, self.selected_language))

        async def on_confirm(interaction: discord.Interaction) -> None:
            if (
                not self.selected_country
                or not self.selected_region
                or not self.selected_language
            ):
                embed = SetupSelectionEmbed(
                    self.selected_country, self.selected_region, self.selected_language
                )
                embed.set_footer(
                    text="Please select a nationality, location, and language before confirming."
                )
                fresh = SetupSelectionView(
                    player_name=self.player_name,
                    battletag=self.battletag,
                    alt_ids=self.alt_ids,
                    message=self.message,
                    selected_country=self.selected_country,
                    selected_region=self.selected_region,
                    selected_language=self.selected_language,
                    country_page1_code=self.country_page1_code,
                    country_page2_code=self.country_page2_code,
                )
                await interaction.response.edit_message(embed=embed, view=fresh)
                return

            await interaction.response.edit_message(
                embed=SetupPreviewEmbed(
                    self.player_name,
                    self.battletag,
                    self.alt_ids,
                    self.selected_country,
                    self.selected_region,
                    self.selected_language,
                ),
                view=SetupPreviewView(
                    player_name=self.player_name,
                    battletag=self.battletag,
                    alt_ids=self.alt_ids,
                    message=self.message,
                    country=self.selected_country,
                    region=self.selected_region,
                    language=self.selected_language,
                ),
            )

        async def on_restart(interaction: discord.Interaction) -> None:
            modal = SetupModal(
                presets={
                    "player_name": self.player_name,
                    "battletag": self.battletag,
                    "alt_ids": " ".join(self.alt_ids),
                },
                message=self.message,
            )
            await interaction.response.send_modal(modal)

        self.add_item(ConfirmButton(callback=on_confirm, row=4))
        self.add_item(RestartButton(callback=on_restart, row=4))
        self.add_item(CancelButton(row=4))

    async def refresh(self, interaction: discord.Interaction) -> None:
        new_view = SetupSelectionView(
            player_name=self.player_name,
            battletag=self.battletag,
            alt_ids=self.alt_ids,
            message=self.message,
            selected_country=self.selected_country,
            selected_region=self.selected_region,
            selected_language=self.selected_language,
            country_page1_code=self.country_page1_code,
            country_page2_code=self.country_page2_code,
        )
        await interaction.response.edit_message(
            embed=SetupSelectionEmbed(
                self.selected_country, self.selected_region, self.selected_language
            ),
            view=new_view,
        )


class SetupPreviewView(discord.ui.View):
    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        message: discord.Message,
        country: Country,
        region: GeographicRegion,
        language: str,
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            await _send_setup_request(
                interaction, player_name, battletag, alt_ids, country, region, language
            )

        async def on_restart(interaction: discord.Interaction) -> None:
            modal = SetupModal(
                presets={
                    "player_name": player_name,
                    "battletag": battletag,
                    "alt_ids": " ".join(alt_ids),
                },
                message=message,
            )
            await interaction.response.send_modal(modal)

        self.add_item(ConfirmButton(callback=on_confirm))
        self.add_item(RestartButton(callback=on_restart))
        self.add_item(CancelButton())


class SetupValidationErrorView(discord.ui.View):
    def __init__(self, presets: dict[str, str], message: discord.Message) -> None:
        super().__init__()

        async def on_restart(interaction: discord.Interaction) -> None:
            modal = SetupModal(presets=presets, message=message)
            await interaction.response.send_modal(modal)

        self.add_item(RestartButton(callback=on_restart, label="Try Again"))
        self.add_item(CancelButton())


# --- Modal ---


class SetupModal(discord.ui.Modal, title="Player Setup"):
    player_name_input: discord.ui.TextInput
    battletag_input: discord.ui.TextInput
    alt_ids_input: discord.ui.TextInput

    def __init__(
        self,
        presets: dict[str, str] | None = None,
        message: discord.Message | None = None,
    ) -> None:
        super().__init__()
        self._message = message
        p = presets or {}

        self.player_name_input = discord.ui.TextInput(
            label="User ID",
            placeholder="3–12 characters (letters, digits, - _ .)",
            default=p.get("player_name") or None,
            min_length=3,
            max_length=12,
            required=True,
        )
        self.battletag_input = discord.ui.TextInput(
            label="BattleTag",
            placeholder="e.g. Username#1234",
            default=p.get("battletag") or None,
            min_length=5,
            max_length=25,
            required=True,
        )
        self.alt_ids_input = discord.ui.TextInput(
            label="Alternative IDs (optional)",
            placeholder="Space-separated names, e.g. AltName1 AltName2",
            default=p.get("alt_ids") or None,
            max_length=100,
            required=False,
        )
        self.add_item(self.player_name_input)
        self.add_item(self.battletag_input)
        self.add_item(self.alt_ids_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        player_name = self.player_name_input.value.strip()
        battletag = self.battletag_input.value.strip()
        raw_alt_ids = self.alt_ids_input.value.strip()

        log.debug(
            "SetupModal.on_submit: user=%s player_name=%r battletag=%r alt_ids=%r",
            interaction.user.id,
            player_name,
            battletag,
            raw_alt_ids,
        )

        current_presets: dict[str, str] = {
            "player_name": player_name,
            "battletag": battletag,
            "alt_ids": raw_alt_ids,
        }

        ok, error = _validate_player_name(player_name)
        if not ok:
            log.debug("SetupModal validation failed (player_name): %s", error)
            await self._edit(
                interaction,
                embed=SetupValidationErrorEmbed("Invalid User ID", error or ""),
                view=SetupValidationErrorView(current_presets, self._message),  # type: ignore[arg-type]
            )
            return

        ok, error = _validate_battletag(battletag)
        if not ok:
            log.debug("SetupModal validation failed (battletag): %s", error)
            await self._edit(
                interaction,
                embed=SetupValidationErrorEmbed("Invalid BattleTag", error or ""),
                view=SetupValidationErrorView(current_presets, self._message),  # type: ignore[arg-type]
            )
            return

        alt_ids: list[str] = []
        for token in raw_alt_ids.split():
            ok, error = _validate_player_name(token, allow_international=True)
            if not ok:
                log.debug("SetupModal validation failed (alt_id %r): %s", token, error)
                await self._edit(
                    interaction,
                    embed=SetupValidationErrorEmbed(
                        f"Invalid Alternative ID: {token}", error or ""
                    ),
                    view=SetupValidationErrorView(current_presets, self._message),  # type: ignore[arg-type]
                )
                return
            alt_ids.append(token)

        if len({player_name, *alt_ids}) != len([player_name, *alt_ids]):
            log.debug("SetupModal validation failed: duplicate IDs")
            await self._edit(
                interaction,
                embed=SetupValidationErrorEmbed(
                    "Duplicate IDs", "All IDs must be unique."
                ),
                view=SetupValidationErrorView(current_presets, self._message),  # type: ignore[arg-type]
            )
            return

        log.debug(
            "SetupModal.on_submit: validation passed for user=%s, showing selection",
            interaction.user.id,
        )
        await self._edit(
            interaction,
            embed=SetupSelectionEmbed(),
            view=SetupSelectionView(
                player_name=player_name,
                battletag=battletag,
                alt_ids=alt_ids,
                message=self._message,  # type: ignore[arg-type]
            ),
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[Any] | None = None,
        /,
    ) -> None:
        log.exception(
            "SetupModal.on_error: unhandled exception for user=%s",
            interaction.user.id,
            exc_info=error,
        )
        try:
            if self._message is not None:
                await interaction.response.defer()
                await self._message.edit(
                    content="An unexpected error occurred. Please try again.",
                    embed=None,
                    view=None,
                )
            else:
                await interaction.response.send_message(
                    "An unexpected error occurred. Please try again.", ephemeral=True
                )
        except discord.InteractionResponded:
            pass

    async def _edit(
        self,
        interaction: discord.Interaction,
        *,
        embed: discord.Embed,
        view: discord.ui.View,
    ) -> None:
        await interaction.response.defer()
        await self._message.edit(embed=embed, view=view)  # type: ignore[union-attr]


# ----------------
# Internal helpers
# ----------------


_PLAYER_NAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]{3,12}$")
_PLAYER_NAME_INTL_RE = re.compile(r"^[\w\-\.]{3,12}$", re.UNICODE)
_BATTLETAG_RE = re.compile(r"^.{1,12}#\d{3,12}$")


def _validate_player_name(
    name: str, *, allow_international: bool = False
) -> tuple[bool, str | None]:
    pattern = _PLAYER_NAME_INTL_RE if allow_international else _PLAYER_NAME_RE
    if not pattern.match(name):
        if allow_international:
            return (
                False,
                "Must be 3–12 characters. Spaces and most symbols are not allowed.",
            )
        return False, "Must be 3–12 characters using only letters, digits, -, _, ."
    return True, None


def _validate_battletag(tag: str) -> tuple[bool, str | None]:
    if not _BATTLETAG_RE.match(tag):
        return False, "Must follow the format Name#Digits (e.g. Username#1234)."
    return True, None


async def _send_setup_request(
    interaction: discord.Interaction,
    player_name: str,
    battletag: str,
    alt_ids: list[str],
    country: Country,
    region: GeographicRegion,
    language: str,
) -> None:
    log.info(
        "_send_setup_request: user=%s player_name=%r battletag=%r alt_ids=%r country=%s region=%s language=%s",
        interaction.user.id,
        player_name,
        battletag,
        alt_ids,
        country["code"],
        region["code"],
        language,
    )
    await interaction.response.edit_message(
        embed=SetupSuccessEmbed(
            player_name, battletag, alt_ids, country, region, language
        ),
        view=None,
    )


# --------------------
# Command registration
# --------------------


def register_setup_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="setup", description="Set up your player profile for matchmaking"
    )
    @app_commands.check(check_if_dm)
    async def setup_command(interaction: discord.Interaction) -> None:
        log.debug("setup_command invoked by user=%s", interaction.user.id)
        await interaction.response.defer()
        await interaction.followup.send(
            embed=SetupIntroEmbed(),
            view=SetupIntroView(),
        )
