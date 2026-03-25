"""
All Discord UI components (views, selects, buttons, modals) used across bot
commands, plus the HTTP action helpers called from their callbacks.
"""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from datetime import timedelta
from typing import Any, Awaitable, Callable

import discord
import structlog

from bot.components.queue_activity_chart import render_queue_join_chart_png
from bot.components.embeds import (
    AdminResolution2v2Embed,
    AdminResolutionEmbed,
    BanSuccessEmbed,
    ErrorEmbed,
    LobbyGuideEmbed,
    MatchAbortAckEmbed,
    MatchConfirmedEmbed,
    MatchInfoEmbed1v1,
    MatchInfoEmbeds2v2,
    QueueErrorEmbed,
    QueueSetupEmbed1v1,
    QueueSetupEmbed2v2,
    QueueSearchingEmbed,
    QueueSearchingEmbed2v2,
    SetCountryConfirmEmbed,
    SetMMRSuccessEmbed,
    SetupIntroEmbed,
    SetupNotificationEmbed,
    SetupPreviewEmbed,
    SetupSelectionEmbed,
    SetupSuccessEmbed,
    SetupValidationErrorEmbed,
    StatusResetSuccessEmbed,
    TermsOfServiceDeclinedEmbed,
    TermsOfServiceEmbed,
    ToggleAdminSuccessEmbed,
)
from bot.core.config import (
    BACKEND_URL,
    CONFIRMATION_TIMEOUT,
    CURRENT_SEASON,
    MATCH_LOG_CHANNEL_ID,
    MAX_MAP_VETOES,
    QUEUE_SEARCHING_HEARTBEAT_SECONDS,
)
from bot.core.dependencies import get_cache, get_player_locale
from bot.core.http import get_session
from bot.helpers.activity_analytics import (
    activity_chart_title,
    fetch_queue_join_analytics,
)
from bot.helpers.activity_stats import build_activity_embed_fields
from bot.helpers.checks import (
    AlreadyQueueingError,
    NameNotUniqueError,
    check_if_name_unique,
    check_if_queueing,
)
from bot.helpers.embed_branding import apply_default_embed_footer
from bot.helpers.emotes import (
    get_flag_emote,
    get_game_emote,
    get_globe_emote,
    get_race_emote,
)
from common.i18n import LOCALE_DISPLAY_NAMES, get_available_locales, t
from bot.helpers.message_helpers import (
    queue_channel_send_low,
    queue_message_edit_low,
    queue_user_send_low,
)
from common.datetime_helpers import utc_now
from common.json_types import Country, GeographicRegion
from common.lookups.map_lookups import get_maps
from common.lookups.race_lookups import get_bw_race_codes, get_races, get_sc2_race_codes
from common.lookups.country_lookups import get_common_countries, get_country_by_code
from common.lookups.region_lookups import (
    get_geographic_region_by_code,
    get_geographic_regions,
)

logger = structlog.get_logger(__name__)


def _localized_country_label(code: str, locale: str = "enUS") -> str:
    """Return ``(XX) Localized Name`` for dropdown labels."""
    translated = t(f"country.{code}.name", locale)
    name = translated if translated != f"country.{code}.name" else code
    return f"({code}) {name}"


def _localized_region_label(code: str, locale: str = "enUS") -> str:
    """Return ``(XXX) Localized Name`` for dropdown labels."""
    translated = t(f"region.{code}.name", locale)
    name = translated if translated != f"region.{code}.name" else code
    return f"({code}) {name}"


def _localized_language_label(code: str) -> str:
    """Return ``(code) Display Name`` for dropdown labels."""
    entry = LOCALE_DISPLAY_NAMES.get(code)
    name = entry[0] if entry else code
    return f"({code}) {name}"


# =========================================================================
# Reusable buttons
# =========================================================================


class ConfirmButton(discord.ui.Button["discord.ui.View"]):
    def __init__(
        self,
        callback: Callable[[discord.Interaction], Awaitable[None]],
        label: str = "Confirm",
        style: discord.ButtonStyle = discord.ButtonStyle.green,
        emoji: str = "✅",
        row: int | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            label=label, style=style, emoji=emoji, row=row, disabled=disabled
        )
        self._callback = callback

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction)


class RestartButton(discord.ui.Button["discord.ui.View"]):
    def __init__(
        self,
        callback: Callable[[discord.Interaction], Awaitable[None]],
        label: str = "Restart",
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        emoji: str = "🔄",
        row: int | None = None,
    ) -> None:
        super().__init__(label=label, style=style, emoji=emoji, row=row)
        self._callback = callback

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction)


class CancelButton(discord.ui.Button["discord.ui.View"]):
    def __init__(self, row: int | None = None, locale: str = "enUS") -> None:
        super().__init__(
            label=t("button.cancel", locale),
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.message is not None:
            await interaction.message.delete()


# =========================================================================
# Setup — Selects
# =========================================================================


class CountryPage1Select(discord.ui.Select):
    def __init__(
        self, countries: list[Country], selected_code: str | None, locale: str = "enUS"
    ) -> None:
        options = [
            discord.SelectOption(
                label=_localized_country_label(c["code"], locale),
                value=c["code"],
                emoji=get_flag_emote(c["code"]),
                default=(c["code"] == selected_code),
            )
            for c in countries[:25]
        ]
        super().__init__(
            placeholder=t("setup_selection_view.placeholder.nationality_page1", locale),
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
    def __init__(
        self, countries: list[Country], selected_code: str | None, locale: str = "enUS"
    ) -> None:
        options = [
            discord.SelectOption(
                label=_localized_country_label(c["code"], locale),
                value=c["code"],
                emoji=get_flag_emote(c["code"]),
                default=(c["code"] == selected_code),
            )
            for c in countries[25:50]
        ]
        super().__init__(
            placeholder=t("setup_selection_view.placeholder.nationality_page2", locale),
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
        self,
        regions: list[GeographicRegion],
        selected_code: str | None,
        locale: str = "enUS",
    ) -> None:
        options = [
            discord.SelectOption(
                label=_localized_region_label(r["code"], locale),
                value=r["code"],
                emoji=get_globe_emote(r["globe_emote_code"]),
                default=(r["code"] == selected_code),
            )
            for r in regions
        ]
        super().__init__(
            placeholder=t("setup_selection_view.placeholder.location", locale),
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
    def __init__(
        self,
        locales: list[str],
        selected_code: str | None,
        locale: str = "enUS",
        row: int = 3,
    ) -> None:
        options = [
            discord.SelectOption(
                label=_localized_language_label(code),
                value=code,
                emoji=LOCALE_DISPLAY_NAMES[code][1]
                if code in LOCALE_DISPLAY_NAMES
                else None,
                default=(code == selected_code),
            )
            for code in locales
        ]
        super().__init__(
            placeholder=t("locale_setup_view.placeholder.language", locale),
            min_values=1,
            max_values=1,
            options=options,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Default no-op — callers override this via .callback assignment.
        await interaction.response.defer()


# =========================================================================
# Setup — Views & Modal
# =========================================================================

_PLAYER_NAME_RE = re.compile(r"^[A-Za-z]{3,12}$")
_PLAYER_NAME_INTL_RE = re.compile(r"^[\w\-\.]{3,12}$", re.UNICODE)
_BATTLETAG_DISCRIMINATOR_RE = re.compile(r"^\d{3,5}$")
# Name part: letters (any script), decimal digits, non-spacing marks (accents)
_BATTLETAG_NAME_ALLOWED_CATEGORIES = frozenset(
    {"Lu", "Ll", "Lt", "Lm", "Lo", "Nd", "Mn"}
)


def _validate_player_name(
    name: str, *, allow_international: bool = False, locale: str = "enUS"
) -> tuple[bool, str | None]:
    pattern = _PLAYER_NAME_INTL_RE if allow_international else _PLAYER_NAME_RE
    if not pattern.match(name):
        if allow_international:
            return False, t("validation.player_name.intl.description", locale)
        return False, t("validation.player_name.ascii.description", locale)
    return True, None


def _validate_battletag(tag: str, locale: str = "enUS") -> tuple[bool, str | None]:
    err = t("validation.battletag.description", locale)
    if tag.count("#") != 1:
        return False, err
    name_part, disc_part = tag.split("#", 1)
    if not (1 <= len(name_part) <= 12):
        return False, err
    if not _BATTLETAG_DISCRIMINATOR_RE.fullmatch(disc_part):
        return False, err
    for ch in name_part:
        if unicodedata.category(ch) not in _BATTLETAG_NAME_ALLOWED_CATEGORIES:
            return False, err
    return True, None


def _country_page_codes(
    nationality_code: str | None,
) -> tuple[str | None, str | None]:
    """Return (page1_code, page2_code) for pre-selecting a country in the dropdowns."""
    if not nationality_code:
        return None, None
    countries = sorted(get_common_countries().values(), key=lambda c: c["code"])
    page1 = {c["code"] for c in countries[:25]}
    page2 = {c["code"] for c in countries[25:50]}
    if nationality_code in page1:
        return nationality_code, None
    if nationality_code in page2:
        return None, nationality_code
    return None, None


class SetupIntroView(discord.ui.View):
    def __init__(
        self,
        modal_presets: dict[str, str] | None = None,
        preselected_nationality: str | None = None,
        preselected_location: str | None = None,
        locale: str = "enUS",
        show_cancel: bool = True,
    ) -> None:
        super().__init__()

        async def on_begin(interaction: discord.Interaction) -> None:
            logger.debug(
                f"SetupIntroView: begin setup clicked by user={interaction.user.id}"
            )
            modal = SetupModal(
                presets=modal_presets,
                message=interaction.message,
                preselected_nationality=preselected_nationality,
                preselected_location=preselected_location,
                locale=get_player_locale(interaction.user.id),
                show_cancel=show_cancel,
            )
            await interaction.response.send_modal(modal)

        self.add_item(
            ConfirmButton(callback=on_begin, label=t("button.begin_setup", locale))
        )
        if show_cancel:
            self.add_item(CancelButton(locale=locale))


class SetupSelectionView(discord.ui.View):
    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        message: discord.Message,
        selected_country: Country | None = None,
        selected_region: GeographicRegion | None = None,
        country_page1_code: str | None = None,
        country_page2_code: str | None = None,
        locale: str = "enUS",
        show_cancel: bool = True,
    ) -> None:
        super().__init__()
        self.player_name = player_name
        self.battletag = battletag
        self.alt_ids = alt_ids
        self.message = message
        self.selected_country = selected_country
        self.selected_region = selected_region
        self.country_page1_code = country_page1_code
        self.country_page2_code = country_page2_code
        self.locale = locale
        self.show_cancel = show_cancel

        self.countries: list[Country] = sorted(
            get_common_countries().values(), key=lambda c: c["code"]
        )
        self.regions: list[GeographicRegion] = list(get_geographic_regions().values())

        self._build()

    def _build(self) -> None:
        self.clear_items()

        self.add_item(
            CountryPage1Select(self.countries, self.country_page1_code, self.locale)
        )
        self.add_item(
            CountryPage2Select(self.countries, self.country_page2_code, self.locale)
        )
        self.add_item(
            RegionSelect(
                self.regions,
                self.selected_region["code"] if self.selected_region else None,
                self.locale,
            )
        )

        async def on_confirm(interaction: discord.Interaction) -> None:
            if not self.selected_country or not self.selected_region:
                _loc = get_player_locale(interaction.user.id)
                embed = SetupSelectionEmbed(
                    self.selected_country,
                    self.selected_region,
                    locale=_loc,
                )
                embed.set_footer(
                    text=t(
                        "setup_selection_view.incomplete_footer.1",
                        _loc,
                    )
                )
                apply_default_embed_footer(embed, locale=_loc)
                fresh = SetupSelectionView(
                    player_name=self.player_name,
                    battletag=self.battletag,
                    alt_ids=self.alt_ids,
                    message=self.message,
                    selected_country=self.selected_country,
                    selected_region=self.selected_region,
                    country_page1_code=self.country_page1_code,
                    country_page2_code=self.country_page2_code,
                    locale=get_player_locale(interaction.user.id),
                    show_cancel=self.show_cancel,
                )
                await interaction.response.edit_message(embed=embed, view=fresh)
                return

            _locale = get_player_locale(interaction.user.id)
            await interaction.response.edit_message(
                embed=SetupNotificationEmbed(locale=_locale),
                view=SetupNotificationView(
                    player_name=self.player_name,
                    battletag=self.battletag,
                    alt_ids=self.alt_ids,
                    message=self.message,
                    country=self.selected_country,
                    region=self.selected_region,
                    language=get_player_locale(interaction.user.id),
                    locale=_locale,
                    show_cancel=self.show_cancel,
                ),
            )

        async def on_restart(interaction: discord.Interaction) -> None:
            _locale = get_player_locale(interaction.user.id)
            await interaction.response.edit_message(
                embed=SetupIntroEmbed(locale=_locale),
                view=SetupIntroView(
                    modal_presets={
                        "player_name": self.player_name,
                        "battletag": self.battletag,
                        "alt_ids": " ".join(self.alt_ids),
                    },
                    preselected_nationality=self.selected_country["code"]
                    if self.selected_country
                    else None,
                    preselected_location=self.selected_region["code"]
                    if self.selected_region
                    else None,
                    locale=_locale,
                    show_cancel=self.show_cancel,
                ),
            )

        self.add_item(
            ConfirmButton(
                callback=on_confirm,
                row=4,
                label=t("button.confirm", self.locale),
                disabled=not (self.selected_country and self.selected_region),
            )
        )
        self.add_item(
            RestartButton(
                callback=on_restart, row=4, label=t("button.restart", self.locale)
            )
        )
        if self.show_cancel:
            self.add_item(CancelButton(row=4, locale=self.locale))

    async def refresh(self, interaction: discord.Interaction) -> None:
        new_view = SetupSelectionView(
            player_name=self.player_name,
            battletag=self.battletag,
            alt_ids=self.alt_ids,
            message=self.message,
            selected_country=self.selected_country,
            selected_region=self.selected_region,
            country_page1_code=self.country_page1_code,
            country_page2_code=self.country_page2_code,
            locale=get_player_locale(interaction.user.id),
            show_cancel=self.show_cancel,
        )
        await interaction.response.edit_message(
            embed=SetupSelectionEmbed(
                self.selected_country,
                self.selected_region,
                locale=get_player_locale(interaction.user.id),
            ),
            view=new_view,
        )


def _notification_select_options(
    selected_value: str | None, locale: str
) -> list[discord.SelectOption]:
    """Build the 6 notification frequency options for a single mode select."""
    entries = [
        ("off", t("setup_notification_view.option.off", locale)),
        ("5", t("setup_notification_view.option.5min", locale)),
        ("15", t("setup_notification_view.option.15min", locale)),
        ("30", t("setup_notification_view.option.30min", locale)),
        ("60", t("setup_notification_view.option.1hr", locale)),
        ("180", t("setup_notification_view.option.3hr", locale)),
    ]
    return [
        discord.SelectOption(
            label=label,
            value=value,
            default=(value == selected_value),
        )
        for value, label in entries
    ]


class SetupNotificationView(discord.ui.View):
    """Notification preferences step of /setup.

    Player selects 1v1 and 2v2 notification intervals (or off).
    Both selects must have a selection before Confirm enables.
    On confirm: transitions to SetupPreviewView.
    On restart: returns to SetupIntroView.
    """

    def __init__(
        self,
        player_name: str,
        battletag: str,
        alt_ids: list[str],
        message: discord.Message,
        country: Country,
        region: GeographicRegion,
        language: str,
        preselected_1v1: str | None = None,
        preselected_2v2: str | None = None,
        locale: str = "enUS",
        show_cancel: bool = True,
    ) -> None:
        super().__init__()

        _options_1v1 = _notification_select_options(preselected_1v1, locale)
        _options_2v2 = _notification_select_options(preselected_2v2, locale)

        _confirm_disabled = preselected_1v1 is None or preselected_2v2 is None

        async def on_confirm(interaction: discord.Interaction) -> None:
            if preselected_1v1 is None or preselected_2v2 is None:
                await interaction.response.defer()
                return
            _locale = get_player_locale(interaction.user.id)
            notification_1v1 = (
                None if preselected_1v1 == "off" else int(preselected_1v1)
            )
            notification_2v2 = (
                None if preselected_2v2 == "off" else int(preselected_2v2)
            )
            await interaction.response.edit_message(
                embed=SetupPreviewEmbed(
                    player_name,
                    battletag,
                    alt_ids,
                    country,
                    region,
                    language,
                    notification_1v1,
                    notification_2v2,
                    locale=_locale,
                ),
                view=SetupPreviewView(
                    player_name=player_name,
                    battletag=battletag,
                    alt_ids=alt_ids,
                    message=message,
                    country=country,
                    region=region,
                    language=language,
                    notification_1v1=notification_1v1,
                    notification_2v2=notification_2v2,
                    locale=_locale,
                    show_cancel=show_cancel,
                ),
            )

        async def on_restart(interaction: discord.Interaction) -> None:
            _locale = get_player_locale(interaction.user.id)
            await interaction.response.edit_message(
                embed=SetupIntroEmbed(locale=_locale),
                view=SetupIntroView(
                    modal_presets={
                        "player_name": player_name,
                        "battletag": battletag,
                        "alt_ids": " ".join(alt_ids),
                    },
                    preselected_nationality=country["code"],
                    preselected_location=region["code"],
                    locale=_locale,
                    show_cancel=show_cancel,
                ),
            )

        select_1v1: discord.ui.Select = discord.ui.Select(
            placeholder=t("setup_notification_view.placeholder.1v1", locale),
            min_values=1,
            max_values=1,
            options=_options_1v1,
            row=0,
        )
        select_2v2: discord.ui.Select = discord.ui.Select(
            placeholder=t("setup_notification_view.placeholder.2v2", locale),
            min_values=1,
            max_values=1,
            options=_options_2v2,
            row=1,
        )

        async def on_select_1v1(interaction: discord.Interaction) -> None:
            fresh = SetupNotificationView(
                player_name=player_name,
                battletag=battletag,
                alt_ids=alt_ids,
                message=message,
                country=country,
                region=region,
                language=language,
                preselected_1v1=select_1v1.values[0],
                preselected_2v2=preselected_2v2,
                locale=get_player_locale(interaction.user.id),
                show_cancel=show_cancel,
            )
            await interaction.response.edit_message(view=fresh)

        async def on_select_2v2(interaction: discord.Interaction) -> None:
            fresh = SetupNotificationView(
                player_name=player_name,
                battletag=battletag,
                alt_ids=alt_ids,
                message=message,
                country=country,
                region=region,
                language=language,
                preselected_1v1=preselected_1v1,
                preselected_2v2=select_2v2.values[0],
                locale=get_player_locale(interaction.user.id),
                show_cancel=show_cancel,
            )
            await interaction.response.edit_message(view=fresh)

        select_1v1.callback = on_select_1v1  # type: ignore[method-assign]
        select_2v2.callback = on_select_2v2  # type: ignore[method-assign]

        self.add_item(select_1v1)
        self.add_item(select_2v2)
        self.add_item(
            ConfirmButton(
                label=t("button.confirm", locale),
                callback=on_confirm,
                row=2,
                disabled=_confirm_disabled,
            )
        )
        self.add_item(
            RestartButton(
                callback=on_restart,
                label=t("button.restart", locale),
                row=2,
            )
        )
        if show_cancel:
            self.add_item(CancelButton(row=2, locale=locale))


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
        notification_1v1: int | None,
        notification_2v2: int | None,
        locale: str = "enUS",
        show_cancel: bool = True,
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            await _send_setup_request(
                interaction,
                player_name,
                battletag,
                alt_ids,
                country,
                region,
                language,
                notification_1v1,
                notification_2v2,
            )

        async def on_restart(interaction: discord.Interaction) -> None:
            _locale = get_player_locale(interaction.user.id)
            await interaction.response.edit_message(
                embed=SetupIntroEmbed(locale=_locale),
                view=SetupIntroView(
                    modal_presets={
                        "player_name": player_name,
                        "battletag": battletag,
                        "alt_ids": " ".join(alt_ids),
                    },
                    preselected_nationality=country["code"],
                    preselected_location=region["code"],
                    locale=_locale,
                    show_cancel=show_cancel,
                ),
            )

        self.add_item(
            ConfirmButton(callback=on_confirm, label=t("button.confirm", locale))
        )
        self.add_item(
            RestartButton(callback=on_restart, label=t("button.restart", locale))
        )
        if show_cancel:
            self.add_item(CancelButton(locale=locale))


class SetupValidationErrorView(discord.ui.View):
    def __init__(
        self,
        presets: dict[str, str],
        message: discord.Message,
        locale: str = "enUS",
        show_cancel: bool = True,
    ) -> None:
        super().__init__()

        async def on_restart(interaction: discord.Interaction) -> None:
            modal = SetupModal(
                presets=presets,
                message=message,
                locale=get_player_locale(interaction.user.id),
                show_cancel=show_cancel,
            )
            await interaction.response.send_modal(modal)

        self.add_item(
            RestartButton(callback=on_restart, label=t("button.try_again", locale))
        )
        if show_cancel:
            self.add_item(CancelButton(locale=locale))


class SetupModal(discord.ui.Modal, title="Player Setup"):
    player_name_input: discord.ui.TextInput
    battletag_input: discord.ui.TextInput
    alt_ids_input: discord.ui.TextInput

    def __init__(
        self,
        presets: dict[str, str] | None = None,
        message: discord.Message | None = None,
        preselected_nationality: str | None = None,
        preselected_location: str | None = None,
        locale: str = "enUS",
        show_cancel: bool = True,
    ) -> None:
        super().__init__(title=t("setup_modal.title.1", locale))
        self._message = message
        self._preselected_nationality = preselected_nationality
        self._preselected_location = preselected_location
        self._show_cancel = show_cancel
        p = presets or {}

        self.player_name_input = discord.ui.TextInput(
            label=t("setup_modal.field_label.player_name", locale),
            placeholder=t("setup_modal.field_placeholder.player_name", locale),
            default=p.get("player_name") or None,
            min_length=3,
            max_length=12,
            required=True,
        )
        self.battletag_input = discord.ui.TextInput(
            label=t("setup_modal.field_label.battletag", locale),
            placeholder=t("setup_modal.field_placeholder.battletag", locale),
            default=p.get("battletag") or None,
            min_length=5,
            max_length=18,
            required=True,
        )
        self.alt_ids_input = discord.ui.TextInput(
            label=t("setup_modal.field_label.alt_ids", locale),
            placeholder=t("setup_modal.field_placeholder.alt_ids", locale),
            default=p.get("alt_ids") or None,
            max_length=100,
            required=False,
        )
        self.add_item(self.player_name_input)
        self.add_item(self.battletag_input)
        self.add_item(self.alt_ids_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self._message is None:
            await interaction.response.send_message(
                t(
                    "setup_modal.error.no_message",
                    get_player_locale(interaction.user.id),
                ),
                ephemeral=True,
            )
            return
        message: discord.Message = self._message
        _locale = get_player_locale(interaction.user.id)

        player_name = self.player_name_input.value.strip()
        battletag = self.battletag_input.value.strip()
        raw_alt_ids = self.alt_ids_input.value.strip()

        logger.debug(
            f"SetupModal.on_submit: user={interaction.user.id} "
            f"player_name={player_name!r} battletag={battletag!r} alt_ids={raw_alt_ids!r}"
        )

        current_presets: dict[str, str] = {
            "player_name": player_name,
            "battletag": battletag,
            "alt_ids": raw_alt_ids,
        }

        ok, error = _validate_player_name(player_name, locale=_locale)
        if not ok:
            logger.debug(f"SetupModal validation failed (player_name): {error}")
            await self._edit(
                interaction,
                message=message,
                embed=SetupValidationErrorEmbed(
                    t(
                        "setup_validation_error_embed.title.invalid_player_name",
                        _locale,
                    ),
                    error or "",
                    locale=_locale,
                ),
                view=SetupValidationErrorView(
                    current_presets,
                    message,
                    locale=_locale,
                    show_cancel=self._show_cancel,
                ),
            )
            return

        ok, error = _validate_battletag(battletag, locale=_locale)
        if not ok:
            logger.debug(f"SetupModal validation failed (battletag): {error}")
            await self._edit(
                interaction,
                message=message,
                embed=SetupValidationErrorEmbed(
                    t("setup_validation_error_embed.title.invalid_battletag", _locale),
                    error or "",
                    locale=_locale,
                ),
                view=SetupValidationErrorView(
                    current_presets,
                    message,
                    locale=_locale,
                    show_cancel=self._show_cancel,
                ),
            )
            return

        alt_ids: list[str] = []
        for token in raw_alt_ids.split():
            ok, error = _validate_player_name(
                token, allow_international=True, locale=_locale
            )
            if not ok:
                logger.debug(
                    f"SetupModal validation failed (alt_id {token!r}): {error}"
                )
                await self._edit(
                    interaction,
                    message=message,
                    embed=SetupValidationErrorEmbed(
                        t(
                            "setup_validation_error_embed.title.invalid_alt_id",
                            _locale,
                            token=token,
                        ),
                        error or "",
                        locale=_locale,
                    ),
                    view=SetupValidationErrorView(
                        current_presets,
                        message,
                        locale=_locale,
                        show_cancel=self._show_cancel,
                    ),
                )
                return
            alt_ids.append(token)

        if len({player_name, *alt_ids}) != len([player_name, *alt_ids]):
            logger.debug("SetupModal validation failed: duplicate IDs")
            await self._edit(
                interaction,
                message=message,
                embed=SetupValidationErrorEmbed(
                    t("setup_validation_error_embed.title.duplicate_ids", _locale),
                    t(
                        "setup_validation_error_embed.description.duplicate_ids",
                        _locale,
                    ),
                    locale=_locale,
                ),
                view=SetupValidationErrorView(
                    current_presets,
                    message,
                    locale=_locale,
                    show_cancel=self._show_cancel,
                ),
            )
            return

        try:
            await check_if_name_unique(player_name, interaction.user.id, _locale)
        except NameNotUniqueError as e:
            logger.debug("SetupModal validation failed (player_name not unique): %s", e)
            await self._edit(
                interaction,
                message=message,
                embed=SetupValidationErrorEmbed(
                    t(
                        "setup_validation_error_embed.title.player_name_taken",
                        _locale,
                    ),
                    str(e),
                    locale=_locale,
                ),
                view=SetupValidationErrorView(
                    current_presets,
                    message,
                    locale=_locale,
                    show_cancel=self._show_cancel,
                ),
            )
            return

        logger.debug(
            f"SetupModal.on_submit: validation passed for user={interaction.user.id}, showing selection"
        )
        preselected_country = (
            get_country_by_code(self._preselected_nationality)
            if self._preselected_nationality
            else None
        )
        preselected_region = (
            get_geographic_region_by_code(self._preselected_location)
            if self._preselected_location
            else None
        )
        _locale = get_player_locale(interaction.user.id)
        page1_code, page2_code = _country_page_codes(
            preselected_country["code"] if preselected_country else None
        )
        await self._edit(
            interaction,
            message=message,
            embed=SetupSelectionEmbed(
                preselected_country,
                preselected_region,
                locale=_locale,
            ),
            view=SetupSelectionView(
                player_name=player_name,
                battletag=battletag,
                alt_ids=alt_ids,
                message=message,
                selected_country=preselected_country,
                selected_region=preselected_region,
                country_page1_code=page1_code,
                country_page2_code=page2_code,
                locale=_locale,
                show_cancel=self._show_cancel,
            ),
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[Any] | None = None,
        /,
    ) -> None:
        logger.exception(
            f"SetupModal.on_error: unhandled exception for user={interaction.user.id}",
            exc_info=error,
        )
        try:
            if self._message is not None:
                await interaction.response.defer()
                await self._message.edit(
                    content=t(
                        "setup_modal.error.unexpected",
                        get_player_locale(interaction.user.id),
                    ),
                    embed=None,
                    view=None,
                )
            else:
                await interaction.response.send_message(
                    t(
                        "setup_modal.error.unexpected",
                        get_player_locale(interaction.user.id),
                    ),
                    ephemeral=True,
                )
        except discord.InteractionResponded:
            pass

    async def _edit(
        self,
        interaction: discord.Interaction,
        *,
        message: discord.Message,
        embed: discord.Embed,
        view: discord.ui.View,
    ) -> None:
        await interaction.response.defer()
        await message.edit(embed=embed, view=view)


# =========================================================================
# Setup — HTTP helper
# =========================================================================


async def _send_setup_request(
    interaction: discord.Interaction,
    player_name: str,
    battletag: str,
    alt_ids: list[str],
    country: Country,
    region: GeographicRegion,
    language: str,
    notification_1v1: int | None,
    notification_2v2: int | None,
) -> None:
    logger.info(
        f"_send_setup_request: user={interaction.user.id} player_name={player_name!r} "
        f"battletag={battletag!r} alt_ids={alt_ids!r} "
        f"nationality={country['code']} location={region['code']} language={language}"
    )
    async with get_session().put(
        f"{BACKEND_URL}/commands/setup",
        json={
            "discord_uid": interaction.user.id,
            "discord_username": interaction.user.name,
            "player_name": player_name,
            "alt_player_names": alt_ids if alt_ids else None,
            "battletag": battletag,
            "nationality": country["code"],
            "location": region["code"],
            "language": language,
        },
    ) as response:
        data = await response.json()

    if response.status >= 400:
        _locale = get_player_locale(interaction.user.id)
        error = data.get("detail") or t("error.unexpected_error", _locale)
        logger.error(
            f"_send_setup_request: backend returned {response.status} for user={interaction.user.id}: {error}"
        )
        await interaction.response.edit_message(
            embed=SetupValidationErrorEmbed(
                t("setup_validation_error_embed.title.setup_failed", _locale),
                error,
                locale=_locale,
            ),
            view=None,
        )
        return

    # Cache the player's chosen language so locale-aware embeds can use it.
    get_cache().player_locales[interaction.user.id] = language

    # After setup succeeds, upsert notification preferences.
    notif_payload: dict[str, object] = {
        "discord_uid": interaction.user.id,
        "notify_queue_1v1": notification_1v1 is not None,
        "notify_queue_2v2": notification_2v2 is not None,
    }
    if notification_1v1 is not None:
        notif_payload["notify_queue_1v1_cooldown"] = notification_1v1
    if notification_2v2 is not None:
        notif_payload["notify_queue_2v2_cooldown"] = notification_2v2
    try:
        async with get_session().put(
            f"{BACKEND_URL}/notifications",
            json=notif_payload,
        ) as notif_response:
            if notif_response.status >= 400:
                logger.warning(
                    f"_send_setup_request: notifications upsert failed for user={interaction.user.id}, status={notif_response.status}"
                )
    except Exception:
        logger.warning(
            f"_send_setup_request: notifications upsert request failed for user={interaction.user.id}",
            exc_info=True,
        )

    await interaction.response.edit_message(
        embed=SetupSuccessEmbed(
            player_name,
            battletag,
            alt_ids,
            country,
            region,
            language,
            notification_1v1=notification_1v1,
            notification_2v2=notification_2v2,
            locale=language,
        ),
        view=None,
    )


# =========================================================================
# Terms of Service
# =========================================================================

# TermsOfServiceView is deprecated.
# The standalone /termsofservice command has been merged into /setup. The ToS
# accept/decline flow is now handled by TermsOfServiceSetupView, which transitions
# to the setup flow on accept rather than ending in a standalone confirmation.
#
# class TermsOfServiceView(discord.ui.View):
#     def __init__(self, discord_uid: int, discord_username: str) -> None:
#         super().__init__()
#
#         async def on_accept(interaction: discord.Interaction) -> None:
#             logger.info(
#                 f"User {discord_username} ({discord_uid}) accepting Terms of Service"
#             )
#             await _send_tos_request(
#                 interaction, discord_uid, discord_username, accepted=True
#             )
#
#         async def on_decline(interaction: discord.Interaction) -> None:
#             logger.info(
#                 f"User {discord_username} ({discord_uid}) declining Terms of Service"
#             )
#             await _send_tos_request(
#                 interaction, discord_uid, discord_username, accepted=False
#             )
#
#         _locale = get_player_locale(discord_uid)
#         self.add_item(
#             ConfirmButton(label=t("button.accept", _locale), callback=on_accept)
#         )
#         self.add_item(
#             ConfirmButton(
#                 label=t("button.decline", _locale),
#                 callback=on_decline,
#                 style=discord.ButtonStyle.red,
#                 emoji="✖️",
#             )
#         )


async def _send_tos_request(
    interaction: discord.Interaction,
    discord_uid: int,
    discord_username: str,
    accepted: bool,
    on_accept_success: Callable[[discord.Interaction, str], Awaitable[None]]
    | None = None,
) -> None:
    """POST ToS accept/decline to the backend and update the message.

    On decline: edits to TermsOfServiceDeclinedEmbed.
    On accept: calls on_accept_success(interaction, locale) so the caller controls
    the post-accept transition (e.g. continue to setup flow).
    """
    async with get_session().put(
        f"{BACKEND_URL}/commands/termsofservice",
        json={
            "discord_uid": discord_uid,
            "discord_username": discord_username,
            "accepted": accepted,
        },
    ) as response:
        data = await response.json()

    _locale = get_player_locale(discord_uid)

    if response.status >= 400:
        error = data.get("detail") or t("error.unexpected_error", _locale)
        logger.error(
            f"TOS upsert failed for {discord_username} ({discord_uid}): {error}"
        )
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title=t("error_embed.title.generic", _locale),
                description=error,
                locale=_locale,
            ),
            view=None,
        )
        return

    logger.info(
        f"TOS upsert succeeded for {discord_username} ({discord_uid}): accepted={accepted}"
    )

    if accepted and on_accept_success is not None:
        await on_accept_success(interaction, _locale)
    else:
        await interaction.response.edit_message(
            embed=TermsOfServiceDeclinedEmbed(locale=_locale),
            view=None,
        )


class TermsOfServiceSetupView(discord.ui.View):
    """ToS accept/decline view used as the first step of /setup.

    On accept: POSTs ToS acceptance, fetches player data for pre-population,
    then transitions to SetupIntroEmbed + SetupIntroView.
    On decline: POSTs ToS decline, then shows TermsOfServiceDeclinedEmbed.
    """

    def __init__(
        self, discord_uid: int, discord_username: str, show_cancel: bool = True
    ) -> None:
        super().__init__()

        async def _on_tos_accepted(
            interaction: discord.Interaction, locale: str
        ) -> None:
            modal_presets: dict[str, str] | None = None
            preselected_nationality: str | None = None
            preselected_location: str | None = None

            player = get_cache().player_presets.get(discord_uid)
            if player:
                modal_presets = {
                    "player_name": player.get("player_name") or "",
                    "alt_ids": " ".join(player.get("alt_player_names") or []),
                    "battletag": player.get("battletag") or "",
                }
                preselected_nationality = player.get("nationality")
                preselected_location = player.get("location")

            await interaction.response.edit_message(
                embed=SetupIntroEmbed(locale=locale),
                view=SetupIntroView(
                    modal_presets=modal_presets,
                    preselected_nationality=preselected_nationality,
                    preselected_location=preselected_location,
                    locale=locale,
                    show_cancel=show_cancel,
                ),
            )

        async def on_accept(interaction: discord.Interaction) -> None:
            logger.info(
                f"User {discord_username} ({discord_uid}) accepting Terms of Service via /setup"
            )
            await _send_tos_request(
                interaction,
                discord_uid,
                discord_username,
                accepted=True,
                on_accept_success=_on_tos_accepted,
            )

        async def on_decline(interaction: discord.Interaction) -> None:
            logger.info(
                f"User {discord_username} ({discord_uid}) declining Terms of Service via /setup"
            )
            await _send_tos_request(
                interaction, discord_uid, discord_username, accepted=False
            )

        _locale = get_player_locale(discord_uid)
        self.add_item(
            ConfirmButton(label=t("button.accept", _locale), callback=on_accept)
        )
        self.add_item(
            ConfirmButton(
                label=t("button.decline", _locale),
                callback=on_decline,
                style=discord.ButtonStyle.red,
                emoji="✖️",
            )
        )


class LocaleSetupView(discord.ui.View):
    """First step of /setup: ask the player to pick their preferred language.

    On continue: caches the selected locale in player_locales and transitions
    to TermsOfServiceEmbed + TermsOfServiceSetupView rendered in that locale.
    """

    def __init__(
        self,
        discord_uid: int,
        discord_username: str,
        preselected_locale: str | None = None,
        show_cancel: bool = True,
    ) -> None:
        super().__init__()
        self.selected_language: str | None = preselected_locale

        locales: list[str] = get_available_locales()

        async def on_continue(interaction: discord.Interaction) -> None:
            if not self.selected_language:
                await interaction.response.defer()
                return
            get_cache().player_locales[discord_uid] = self.selected_language
            await interaction.response.edit_message(
                embed=TermsOfServiceEmbed(locale=self.selected_language),
                view=TermsOfServiceSetupView(
                    discord_uid, discord_username, show_cancel=show_cancel
                ),
            )

        language_select = LanguageSelect(
            locales=locales,
            selected_code=preselected_locale,
            locale="enUS",
            row=0,
        )
        _continue_button = ConfirmButton(
            label=t("button.continue", "enUS"),
            callback=on_continue,
            row=1,
            disabled=preselected_locale is None,
        )

        async def on_language_select(interaction: discord.Interaction) -> None:
            fresh = LocaleSetupView(
                discord_uid,
                discord_username,
                preselected_locale=language_select.values[0],
                show_cancel=show_cancel,
            )
            await interaction.response.edit_message(view=fresh)

        language_select.callback = on_language_select  # type: ignore[method-assign]

        self.add_item(language_select)
        self.add_item(_continue_button)


# =========================================================================
# Set Country
# =========================================================================


class SetCountryView(discord.ui.View):
    def __init__(self, country: Country, locale: str = "enUS"):
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            await _send_setcountry_request(interaction, country)

        self.add_item(
            ConfirmButton(callback=on_confirm, label=t("button.confirm", locale))
        )
        self.add_item(CancelButton(locale=locale))


async def _send_setcountry_request(
    interaction: discord.Interaction,
    country: Country,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/commands/setcountry",
        json={
            "discord_uid": interaction.user.id,
            "discord_username": interaction.user.name,
            "country_code": country["code"],
        },
    ) as response:
        data = await response.json()

    if response.status >= 400:
        _locale = get_player_locale(interaction.user.id)
        error = data.get("detail") or t("error.unexpected_error", _locale)
        logger.error(
            f"setcountry backend failure for user={interaction.user.id}: {error}"
        )
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title=t("error_embed.title.update_failed", _locale),
                description=error,
                locale=_locale,
            ),
            view=None,
        )
        return

    locale = get_cache().player_locales.get(interaction.user.id, "enUS")
    await interaction.response.edit_message(
        embed=SetCountryConfirmEmbed(country, locale=locale),
        view=None,
    )


# =========================================================================
# Admin: Ban
# =========================================================================


class BanConfirmView(discord.ui.View):
    def __init__(
        self, caller_id: int, target_discord_uid: int, target_player_name: str
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    t("error.not_your_button", get_player_locale(interaction.user.id)),
                    ephemeral=True,
                )
                return
            await _send_ban_request(interaction, target_discord_uid, target_player_name)

        _locale = get_player_locale(caller_id)
        self.add_item(
            ConfirmButton(callback=on_confirm, label=t("button.confirm", _locale))
        )
        self.add_item(CancelButton(locale=_locale))


async def _send_ban_request(
    interaction: discord.Interaction,
    target_discord_uid: int,
    target_player_name: str,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/admin/ban",
        json={
            "discord_uid": target_discord_uid,
            "admin_discord_uid": interaction.user.id,
        },
    ) as response:
        data = await response.json()

    if response.status >= 400:
        _locale = get_player_locale(interaction.user.id)
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title=t("error_embed.title.generic", _locale),
                description=t("error_embed.description.ban_failed", _locale),
                locale=_locale,
            ),
            view=None,
        )
        return

    new_is_banned: bool = data["new_is_banned"]
    logger.info(
        f"Admin {interaction.user.name} ({interaction.user.id}) toggled ban for "
        f"{target_player_name} ({target_discord_uid}): is_banned={new_is_banned}"
    )
    await interaction.response.edit_message(
        embed=BanSuccessEmbed(
            target_discord_uid,
            target_player_name,
            new_is_banned,
            locale=get_player_locale(interaction.user.id),
        ),
        view=None,
    )


# =========================================================================
# Admin: Resolve
# =========================================================================


class ResolveConfirmView(discord.ui.View):
    def __init__(
        self,
        caller_id: int,
        match_id: int,
        result: str,
        admin_discord_uid: int,
        reason: str | None,
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    t("error.not_your_button", get_player_locale(interaction.user.id)),
                    ephemeral=True,
                )
                return
            await _send_resolve_request(
                interaction, match_id, result, admin_discord_uid, reason
            )

        _locale = get_player_locale(caller_id)
        self.add_item(
            ConfirmButton(callback=on_confirm, label=t("button.confirm", _locale))
        )
        self.add_item(CancelButton(locale=_locale))


async def _send_resolve_request(
    interaction: discord.Interaction,
    match_id: int,
    result: str,
    admin_discord_uid: int,
    reason: str | None,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/admin/matches_1v1/{match_id}/resolve",
        json={
            "result": result,
            "admin_discord_uid": admin_discord_uid,
        },
    ) as response:
        data = await response.json()

    if response.status >= 400:
        _locale = get_player_locale(interaction.user.id)
        error = data.get("detail") or t("error.unexpected_error", _locale)
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title=t("error_embed.title.resolution_failed", _locale),
                description=t(
                    "error_embed.description.with_error", _locale, error=error
                ),
                locale=_locale,
            ),
            view=None,
        )
        return

    resolve_data = data.get("data") or {}
    admin_name = interaction.user.name
    logger.info(
        f"Admin {admin_name} ({interaction.user.id}) resolved "
        f"match #{match_id}: result={result}"
    )

    admin_embed = AdminResolutionEmbed(
        resolve_data,
        reason=reason,
        admin_name=admin_name,
        is_admin_confirm=True,
        locale=get_player_locale(interaction.user.id),
    )
    await interaction.response.edit_message(embed=admin_embed, view=None)

    await _notify_players(interaction, resolve_data, reason, admin_name)
    await _send_to_match_log(interaction, resolve_data, reason, admin_name)


async def _notify_players(
    interaction: discord.Interaction,
    data: dict,
    reason: str | None,
    admin_name: str,
) -> None:
    """DM both players with the Admin Resolution embed."""
    p1_uid = data.get("player_1_discord_uid")
    p2_uid = data.get("player_2_discord_uid")

    for uid in (p1_uid, p2_uid):
        if uid is None:
            continue
        try:
            locale = get_player_locale(uid)
            user = await interaction.client.fetch_user(uid)
            await queue_user_send_low(
                user,
                embed=AdminResolutionEmbed(
                    data, reason=reason, admin_name=admin_name, locale=locale
                ),
            )
        except Exception:
            logger.warning(f"Failed to DM player {uid} about admin resolve")


async def _send_to_match_log(
    interaction: discord.Interaction,
    data: dict,
    reason: str | None,
    admin_name: str,
) -> None:
    """Send the Admin Resolution embed to the match log channel."""
    try:
        channel = interaction.client.get_channel(MATCH_LOG_CHANNEL_ID)
        if channel is None:
            channel = await interaction.client.fetch_channel(MATCH_LOG_CHANNEL_ID)
        if channel is not None and isinstance(channel, discord.TextChannel):
            embed = AdminResolutionEmbed(
                data, reason=reason, admin_name=admin_name, locale="enUS"
            )
            await queue_channel_send_low(channel, embed=embed)
    except Exception:
        logger.warning("Failed to send admin resolve embed to match log channel")


# =========================================================================
# Admin: Resolve 2v2
# =========================================================================


class ResolveConfirmView2v2(discord.ui.View):
    def __init__(
        self,
        caller_id: int,
        match_id: int,
        result: str,
        admin_discord_uid: int,
        reason: str | None,
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    t("error.not_your_button", get_player_locale(interaction.user.id)),
                    ephemeral=True,
                )
                return
            await _send_resolve_request_2v2(
                interaction, match_id, result, admin_discord_uid, reason
            )

        _locale = get_player_locale(caller_id)
        self.add_item(
            ConfirmButton(callback=on_confirm, label=t("button.confirm", _locale))
        )
        self.add_item(CancelButton(locale=_locale))


async def _send_resolve_request_2v2(
    interaction: discord.Interaction,
    match_id: int,
    result: str,
    admin_discord_uid: int,
    reason: str | None,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/admin/matches_2v2/{match_id}/resolve",
        json={
            "result": result,
            "admin_discord_uid": admin_discord_uid,
        },
    ) as response:
        data = await response.json()

    if response.status >= 400:
        _locale = get_player_locale(interaction.user.id)
        error = data.get("detail") or t("error.unexpected_error", _locale)
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title=t("error_embed.title.resolution_failed", _locale),
                description=t(
                    "error_embed.description.with_error", _locale, error=error
                ),
                locale=_locale,
            ),
            view=None,
        )
        return

    resolve_data = data.get("data") or {}
    admin_name = interaction.user.name
    logger.info(
        f"Admin {admin_name} ({interaction.user.id}) resolved "
        f"2v2 match #{match_id}: result={result}"
    )

    player_infos = await _fetch_all_player_infos_2v2(resolve_data)
    admin_embed = AdminResolution2v2Embed(
        resolve_data,
        reason=reason,
        admin_name=admin_name,
        player_infos=player_infos,
        is_admin_confirm=True,
        locale=get_player_locale(interaction.user.id),
    )
    await interaction.response.edit_message(embed=admin_embed, view=None)
    await _notify_players_2v2(
        interaction, resolve_data, player_infos, reason, admin_name
    )
    await _send_to_match_log_2v2(
        interaction, resolve_data, player_infos, reason, admin_name
    )


async def _fetch_all_player_infos_2v2(data: dict) -> dict[int, dict | None]:
    """Fetch nationality info for all four 2v2 players concurrently."""
    uids: list[int] = []
    for team_num in (1, 2):
        for p_num in (1, 2):
            uid = data.get(f"team_{team_num}_player_{p_num}_discord_uid")
            if uid is not None:
                uids.append(uid)
    results = await asyncio.gather(
        *(_fetch_player_info(uid) for uid in uids), return_exceptions=True
    )
    return {uid: (r if isinstance(r, dict) else None) for uid, r in zip(uids, results)}


async def _notify_players_2v2(
    interaction: discord.Interaction,
    data: dict,
    player_infos: dict[int, dict | None],
    reason: str | None,
    admin_name: str,
) -> None:
    """DM all four players with the AdminResolution2v2Embed."""
    uids: list[int] = []
    for team_num in (1, 2):
        for p_num in (1, 2):
            uid = data.get(f"team_{team_num}_player_{p_num}_discord_uid")
            if uid is not None:
                uids.append(uid)

    for uid in uids:
        try:
            locale = get_player_locale(uid)
            user = await interaction.client.fetch_user(uid)
            await queue_user_send_low(
                user,
                embed=AdminResolution2v2Embed(
                    data,
                    reason=reason,
                    admin_name=admin_name,
                    player_infos=player_infos,
                    is_admin_confirm=False,
                    locale=locale,
                ),
            )
        except Exception:
            logger.warning(f"Failed to DM player {uid} about admin resolve 2v2")


async def _send_to_match_log_2v2(
    interaction: discord.Interaction,
    data: dict,
    player_infos: dict[int, dict | None],
    reason: str | None,
    admin_name: str,
) -> None:
    """Send the AdminResolution2v2Embed to the match log channel."""
    try:
        channel = interaction.client.get_channel(MATCH_LOG_CHANNEL_ID)
        if channel is None:
            channel = await interaction.client.fetch_channel(MATCH_LOG_CHANNEL_ID)
        if channel is not None and isinstance(channel, discord.TextChannel):
            embed = AdminResolution2v2Embed(
                data,
                reason=reason,
                admin_name=admin_name,
                player_infos=player_infos,
                is_admin_confirm=False,
                locale="enUS",
            )
            await queue_channel_send_low(channel, embed=embed)
    except Exception:
        logger.warning("Failed to send admin resolve 2v2 embed to match log channel")


# =========================================================================
# Admin: Status Reset
# =========================================================================


class StatusResetConfirmView(discord.ui.View):
    def __init__(
        self, caller_id: int, target_discord_uid: int, target_player_name: str
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    t("error.not_your_button", get_player_locale(interaction.user.id)),
                    ephemeral=True,
                )
                return
            await _send_statusreset_request(
                interaction, target_discord_uid, target_player_name
            )

        _locale = get_player_locale(caller_id)
        self.add_item(
            ConfirmButton(callback=on_confirm, label=t("button.confirm", _locale))
        )
        self.add_item(CancelButton(locale=_locale))


async def _send_statusreset_request(
    interaction: discord.Interaction,
    target_discord_uid: int,
    target_player_name: str,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/admin/statusreset",
        json={
            "discord_uid": target_discord_uid,
            "admin_discord_uid": interaction.user.id,
        },
    ) as response:
        data = await response.json()

    if response.status >= 400:
        _locale = get_player_locale(interaction.user.id)
        error = data.get("detail") or t("error.unexpected_error", _locale)
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title=t("error_embed.title.status_reset_failed", _locale),
                description=t(
                    "error_embed.description.with_error", _locale, error=error
                ),
                locale=_locale,
            ),
            view=None,
        )
        return

    old_status = data.get("old_status")
    logger.info(
        f"Admin {interaction.user.name} ({interaction.user.id}) reset status for "
        f"{target_player_name} ({target_discord_uid}): {old_status} -> idle"
    )

    await interaction.response.edit_message(
        embed=StatusResetSuccessEmbed(
            target_discord_uid,
            target_player_name,
            old_status,
            interaction.user,
            locale=get_player_locale(interaction.user.id),
        ),
        view=None,
    )


# =========================================================================
# Owner: Admin
# =========================================================================


class ToggleAdminConfirmView(discord.ui.View):
    def __init__(
        self,
        caller_id: int,
        target_discord_uid: int,
        target_player_name: str,
        target_discord_username: str,
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    t("error.not_your_button", get_player_locale(interaction.user.id)),
                    ephemeral=True,
                )
                return
            await _send_toggle_admin_request(
                interaction,
                target_discord_uid,
                target_player_name,
                target_discord_username,
            )

        _locale = get_player_locale(caller_id)
        self.add_item(
            ConfirmButton(callback=on_confirm, label=t("button.confirm", _locale))
        )
        self.add_item(CancelButton(locale=_locale))


async def _send_toggle_admin_request(
    interaction: discord.Interaction,
    target_discord_uid: int,
    target_player_name: str,
    target_discord_username: str,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/owner/admin",
        json={
            "discord_uid": target_discord_uid,
            "discord_username": target_discord_username,
            "owner_discord_uid": interaction.user.id,
        },
    ) as response:
        data = await response.json()

    if response.status >= 400:
        _locale = get_player_locale(interaction.user.id)
        error = data.get("detail") or t("error.unexpected_error", _locale)
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title=t("error_embed.title.generic", _locale),
                description=error,
                locale=_locale,
            ),
            view=None,
        )
        return

    action = data.get("action") or "updated"
    new_role = data.get("new_role") or "unknown"

    logger.info(
        f"Owner {interaction.user.name} ({interaction.user.id}) toggled admin for "
        f"{target_player_name} ({target_discord_uid}): action={action}, new_role={new_role}"
    )

    await interaction.response.edit_message(
        embed=ToggleAdminSuccessEmbed(
            target_discord_uid,
            target_player_name,
            action,
            new_role,
            locale=get_player_locale(interaction.user.id),
        ),
        view=None,
    )


# =========================================================================
# Owner: MMR
# =========================================================================


class SetMMRConfirmView(discord.ui.View):
    def __init__(
        self,
        caller_id: int,
        target_discord_uid: int,
        target_player_name: str,
        race: str,
        new_mmr: int,
    ) -> None:
        super().__init__()

        async def on_confirm(interaction: discord.Interaction) -> None:
            if interaction.user.id != caller_id:
                await interaction.response.send_message(
                    t("error.not_your_button", get_player_locale(interaction.user.id)),
                    ephemeral=True,
                )
                return
            await _send_set_mmr_request(
                interaction, target_discord_uid, target_player_name, race, new_mmr
            )

        _locale = get_player_locale(caller_id)
        self.add_item(
            ConfirmButton(callback=on_confirm, label=t("button.confirm", _locale))
        )
        self.add_item(CancelButton(locale=_locale))


async def _send_set_mmr_request(
    interaction: discord.Interaction,
    target_discord_uid: int,
    target_player_name: str,
    race: str,
    new_mmr: int,
) -> None:
    async with get_session().put(
        f"{BACKEND_URL}/owner/mmr",
        json={
            "discord_uid": target_discord_uid,
            "race": race,
            "new_mmr": new_mmr,
            "owner_discord_uid": interaction.user.id,
        },
    ) as response:
        data = await response.json()

    if response.status >= 400:
        _locale = get_player_locale(interaction.user.id)
        await interaction.response.edit_message(
            embed=ErrorEmbed(
                title=t("error_embed.title.generic", _locale),
                description=t("error_embed.description.mmr_failed", _locale),
                locale=_locale,
            ),
            view=None,
        )
        return

    old_mmr = data.get("old_mmr")

    logger.info(
        f"Owner {interaction.user.name} ({interaction.user.id}) set MMR for "
        f"{target_player_name} ({target_discord_uid}): race={race}, {old_mmr} -> {new_mmr}"
    )

    await interaction.response.edit_message(
        embed=SetMMRSuccessEmbed(
            target_discord_uid,
            target_player_name,
            race,
            old_mmr,
            new_mmr,
            locale=get_player_locale(interaction.user.id),
        ),
        view=None,
    )


# =========================================================================
# Queue: player info fetch (also used by ws_listener)
# =========================================================================


async def _fetch_player_info(discord_uid: int) -> dict[str, Any] | None:
    """Fetch a player row from the backend API and seed the locale cache."""
    try:
        async with get_session().get(f"{BACKEND_URL}/players/{discord_uid}") as resp:
            data = await resp.json()
            player: dict[str, Any] | None = data.get("player")
            if player is not None:
                language = player.get("language")
                if language:
                    get_cache().player_locales[discord_uid] = language
            return player
    except Exception:
        logger.warning("Failed to fetch player info", discord_uid=discord_uid)
        return None


# =========================================================================
# Queue: selects
# =========================================================================


class BwRaceSelect(discord.ui.Select):
    def __init__(self, selected: str | None = None, locale: str = "enUS") -> None:
        races = get_races()
        options = [
            discord.SelectOption(
                label=t(f"race.{code}.name", locale),
                value=code,
                emoji=get_race_emote(code),
                default=(code == selected),
            )
            for code in get_bw_race_codes()
            if code in races
        ]
        super().__init__(
            placeholder=t("queue_select.placeholder.bw_race", locale),
            min_values=0,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QueueSetupView1v1 = self.view  # type: ignore[assignment]
        view.bw_race = self.values[0] if self.values else None
        await view.persist_and_refresh(interaction)


class Sc2RaceSelect(discord.ui.Select):
    def __init__(self, selected: str | None = None, locale: str = "enUS") -> None:
        races = get_races()
        options = [
            discord.SelectOption(
                label=t(f"race.{code}.name", locale),
                value=code,
                emoji=get_race_emote(code),
                default=(code == selected),
            )
            for code in get_sc2_race_codes()
            if code in races
        ]
        super().__init__(
            placeholder=t("queue_select.placeholder.sc2_race", locale),
            min_values=0,
            max_values=1,
            options=options,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QueueSetupView1v1 = self.view  # type: ignore[assignment]
        view.sc2_race = self.values[0] if self.values else None
        await view.persist_and_refresh(interaction)


class MapVetoSelect(discord.ui.Select):
    def __init__(self, selected: list[str] | None = None, locale: str = "enUS") -> None:
        maps = get_maps(game_mode="1v1", season=CURRENT_SEASON) or {}
        options = [
            discord.SelectOption(
                label=map_data["short_name"],
                value=map_name,
                emoji=get_game_emote(map_data.get("game", "sc2")),
                default=(map_name in (selected or [])),
            )
            for map_name, map_data in sorted(maps.items())
        ]
        if not options:
            options = [
                discord.SelectOption(
                    label=t("queue_select.no_maps_available", locale), value="none"
                )
            ]

        super().__init__(
            placeholder=t(
                "queue_select.placeholder.map_veto",
                locale,
                max_vetoes=str(MAX_MAP_VETOES),
            ),
            min_values=0,
            max_values=min(MAX_MAP_VETOES, len(options)),
            options=options,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QueueSetupView1v1 = self.view  # type: ignore[assignment]
        view.map_vetoes = [v for v in self.values if v != "none"]
        await view.persist_and_refresh(interaction)


class MatchReportSelect(discord.ui.Select):
    def __init__(
        self, match_id: int, p1_name: str, p2_name: str, locale: str = "enUS"
    ) -> None:
        self.match_id = match_id
        options = [
            discord.SelectOption(
                label=t("match_report_select.victory", locale, name=p1_name),
                value="player_1_win",
            ),
            discord.SelectOption(
                label=t("match_report_select.victory", locale, name=p2_name),
                value="player_2_win",
            ),
            discord.SelectOption(
                label=t("match_report_select.draw", locale), value="draw"
            ),
        ]
        super().__init__(
            placeholder=t("match_report_select.placeholder", locale),
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: MatchReportView1v1 = self.view  # type: ignore[assignment]
        report = self.values[0]
        await view.submit_report(interaction, report)


# =========================================================================
# Queue: views
# =========================================================================

_ACTIVITY_RANGE_TO_TD = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class ActivityChartView(discord.ui.View):
    def __init__(
        self,
        game_mode: str,
        author_id: int,
        locale: str,
        range_key: str = "24h",
    ) -> None:
        super().__init__(timeout=600)
        self.game_mode = game_mode
        self.author_id = author_id
        self.locale = locale
        self.add_item(ActivityRangeSelect(self, range_key))


class ActivityRangeSelect(discord.ui.Select):
    def __init__(
        self, chart_view: ActivityChartView, current_range: str = "24h"
    ) -> None:
        self._activity_chart_view = chart_view
        loc = chart_view.locale
        super().__init__(
            custom_id="activity_chart_range",
            placeholder=t("activity_select.placeholder.1", loc),
            options=[
                discord.SelectOption(
                    label=t("activity_select.option.24h", loc),
                    value="24h",
                    default=(current_range == "24h"),
                ),
                discord.SelectOption(
                    label=t("activity_select.option.7d", loc),
                    value="7d",
                    default=(current_range == "7d"),
                ),
                discord.SelectOption(
                    label=t("activity_select.option.30d", loc),
                    value="30d",
                    default=(current_range == "30d"),
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self._activity_chart_view
        if interaction.user.id != view.author_id:
            await interaction.response.send_message(
                t("activity_command.error.not_yours.1", view.locale),
                ephemeral=True,
            )
            return
        key = self.values[0]
        # Mark the chosen option as default so the menu displays the selection.
        for opt in self.options:
            opt.default = opt.value == key
        delta = _ACTIVITY_RANGE_TO_TD[key]
        end = utc_now()
        start = end - delta
        await interaction.response.defer()
        try:
            data = await fetch_queue_join_analytics(view.game_mode, start, end)
            buckets = data.get("buckets") or []
            title = activity_chart_title(view.locale, view.game_mode, key)
            png = render_queue_join_chart_png(
                buckets, title=title, locale=view.locale, game_mode=view.game_mode
            )
            file = discord.File(png, filename="activity.png")
            embed = discord.Embed(
                title=title,
                description=t(f"activity_embed.description.{key}.1", view.locale),
                color=discord.Color.dark_teal(),
            )
            for name, value, inline in build_activity_embed_fields(
                buckets, key, view.locale
            ):
                embed.add_field(name=name, value=value, inline=inline)
            apply_default_embed_footer(embed, locale=view.locale)
            await interaction.edit_original_response(
                embed=embed,
                attachments=[file],
                view=view,
            )
        except Exception:
            logger.exception("activity range refresh failed")
            await interaction.followup.send(
                t("activity_command.error.refresh_failed.1", view.locale),
                ephemeral=True,
            )


class QueueSetupView1v1(discord.ui.View):
    def __init__(
        self,
        discord_user_id: int,
        bw_race: str | None = None,
        sc2_race: str | None = None,
        map_vetoes: list[str] | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.discord_user_id = discord_user_id
        self.bw_race = bw_race
        self.sc2_race = sc2_race
        self.map_vetoes = map_vetoes or []
        self._build()

    def _build(self) -> None:
        self.clear_items()

        _locale = get_player_locale(self.discord_user_id)

        # Row 0: buttons
        async def on_join(interaction: discord.Interaction) -> None:
            try:
                await check_if_queueing(interaction)
            except AlreadyQueueingError as e:
                _locale = get_player_locale(interaction.user.id)
                await interaction.response.edit_message(
                    embed=ErrorEmbed(
                        title=t("error_embed.title.unauthorized_command", _locale),
                        description=str(e),
                        locale=_locale,
                    ),
                    view=None,
                )
                return
            await _join_queue(
                interaction,
                self.discord_user_id,
                self.bw_race,
                self.sc2_race,
                self.map_vetoes,
            )

        join_btn: discord.ui.Button[QueueSetupView1v1] = discord.ui.Button(
            label=t("button.join_queue", _locale),
            emoji="🚀",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        join_btn.callback = on_join  # type: ignore[method-assign]
        self.add_item(join_btn)

        async def on_clear(interaction: discord.Interaction) -> None:
            self.bw_race = None
            self.sc2_race = None
            self.map_vetoes = []
            await self.persist_and_refresh(interaction)

        clear_btn: discord.ui.Button[QueueSetupView1v1] = discord.ui.Button(
            label=t("button.clear_selections", _locale),
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        clear_btn.callback = on_clear  # type: ignore[method-assign]
        self.add_item(clear_btn)

        async def on_cancel(interaction: discord.Interaction) -> None:
            if interaction.message is not None:
                await interaction.message.delete()

        cancel_btn: discord.ui.Button[QueueSetupView1v1] = discord.ui.Button(
            label=t("button.cancel", _locale),
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        cancel_btn.callback = on_cancel  # type: ignore[method-assign]
        self.add_item(cancel_btn)

        # Row 1-3: selects
        self.add_item(BwRaceSelect(self.bw_race, locale=_locale))
        self.add_item(Sc2RaceSelect(self.sc2_race, locale=_locale))
        self.add_item(MapVetoSelect(self.map_vetoes, locale=_locale))

    async def persist_and_refresh(self, interaction: discord.Interaction) -> None:
        """Save preferences to backend and refresh the embed."""
        try:
            races: list[str] = []
            if self.bw_race:
                races.append(self.bw_race)
            if self.sc2_race:
                races.append(self.sc2_race)
            async with get_session().put(
                f"{BACKEND_URL}/preferences_1v1",
                json={
                    "discord_uid": self.discord_user_id,
                    "last_chosen_races": races,
                    "last_chosen_vetoes": sorted(self.map_vetoes),
                },
            ) as resp:
                await resp.json()
        except Exception:
            logger.warning("Failed to persist preferences", exc_info=True)

        new_view = QueueSetupView1v1(
            self.discord_user_id, self.bw_race, self.sc2_race, self.map_vetoes
        )
        locale = get_player_locale(self.discord_user_id)
        embed = QueueSetupEmbed1v1(
            self.bw_race, self.sc2_race, self.map_vetoes, locale=locale
        )
        await interaction.response.edit_message(embed=embed, view=new_view)


class _CancelQueueButton(discord.ui.Button):
    def __init__(
        self,
        discord_user_id: int,
        bw_race: str | None,
        sc2_race: str | None,
        map_vetoes: list[str],
    ) -> None:
        super().__init__(
            label=t("button.cancel_queue", get_player_locale(discord_user_id)),
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        self.discord_user_id = discord_user_id
        self.bw_race = bw_race
        self.sc2_race = sc2_race
        self.map_vetoes = map_vetoes

    async def callback(self, interaction: discord.Interaction) -> None:
        await _leave_queue(
            interaction,
            self.discord_user_id,
            self.bw_race,
            self.sc2_race,
            self.map_vetoes,
        )


class QueueSearchingView(discord.ui.View):
    def __init__(
        self,
        interaction: discord.Interaction,
        discord_user_id: int,
        bw_race: str | None,
        sc2_race: str | None,
        map_vetoes: list[str],
    ) -> None:
        super().__init__(timeout=None)
        self._interaction = interaction
        self._message: discord.Message | None = None
        self._token_expired: bool = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self.add_item(
            _CancelQueueButton(discord_user_id, bw_race, sc2_race, map_vetoes)
        )

    async def start_heartbeat(self) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Update the searching embed's timestamp at the 15th second of every minute."""
        while True:
            try:
                now = time.time()
                current_minute_start = (now // 60) * 60
                next_beat = current_minute_start + 15
                if next_beat <= now:
                    next_beat += 60
                await asyncio.sleep(next_beat - now)

                stats: dict | None = None
                try:
                    async with get_session().get(
                        f"{BACKEND_URL}/queue_1v1/stats"
                    ) as resp:
                        stats = await resp.json()
                except Exception:
                    pass

                locale = get_player_locale(self._interaction.user.id)
                embed = QueueSearchingEmbed(stats, locale=locale)
                await self._apply_searching_heartbeat_embed(embed)

            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("queue_heartbeat_error", exc_info=True)
                await asyncio.sleep(QUEUE_SEARCHING_HEARTBEAT_SECONDS)

    async def _apply_searching_heartbeat_embed(self, embed: discord.Embed) -> None:
        """Edit the searching DM using the interaction webhook while valid, else bot token."""

        if not self._token_expired:
            try:
                await self._interaction.edit_original_response(embed=embed, view=self)
                return
            except discord.HTTPException as e:
                # Webhook token for interaction responses expires (~15 min). After that,
                # edit_original_response and WebhookMessage.edit both 401 — use channel edit.
                if e.status != 401:
                    raise
                self._token_expired = True
                logger.info(
                    "queue_searching_webhook_token_expired",
                    discord_uid=self._interaction.user.id,
                )

        ref = self._message
        if ref is None:
            logger.warning(
                "queue_heartbeat_no_cached_message",
                discord_uid=self._interaction.user.id,
            )
            return

        ch = ref.channel
        if not isinstance(ch, discord.DMChannel):
            logger.warning(
                "queue_heartbeat_expected_dm",
                channel_type=type(ch).__name__,
                discord_uid=self._interaction.user.id,
            )
            return

        partial = ch.get_partial_message(ref.id)
        updated = await queue_message_edit_low(partial, embed=embed, view=self)
        self._message = updated
        get_cache().active_searching_messages[self._interaction.user.id] = updated

    def stop_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()


class MatchFoundView1v1(discord.ui.View):
    def __init__(self, match_id: int, match_data: dict, locale: str = "enUS") -> None:
        super().__init__(timeout=CONFIRMATION_TIMEOUT)
        self.match_id = match_id
        self.match_data = match_data

        async def on_confirm(interaction: discord.Interaction) -> None:
            await _confirm_match(interaction, match_id)

        confirm_btn: discord.ui.Button[MatchFoundView1v1] = discord.ui.Button(
            label=t("button.confirm_match", locale),
            emoji="✅",
            style=discord.ButtonStyle.green,
            row=0,
        )
        confirm_btn.callback = on_confirm  # type: ignore[method-assign]
        self.add_item(confirm_btn)

        async def on_abort(interaction: discord.Interaction) -> None:
            await _abort_match(interaction, match_id)

        abort_btn: discord.ui.Button[MatchFoundView1v1] = discord.ui.Button(
            label=t("button.abort_match", locale),
            emoji="🛑",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        abort_btn.callback = on_abort  # type: ignore[method-assign]
        self.add_item(abort_btn)


class LobbyGuideToggleButton(
    discord.ui.Button["MatchReportView1v1 | MatchReportView2v2"]
):
    """Blurple/gray button that shows or hides the LobbyGuideEmbed."""

    def __init__(self, locale: str = "enUS", guide_visible: bool = True) -> None:
        label, style = self._attrs(guide_visible, locale)
        super().__init__(label=label, style=style, row=1)
        self._locale = locale

    @staticmethod
    def _attrs(visible: bool, locale: str) -> tuple[str, discord.ButtonStyle]:
        if visible:
            return t("button.hide_lobby_guide", locale), discord.ButtonStyle.primary
        return t("button.expand_lobby_guide", locale), discord.ButtonStyle.secondary

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view: MatchReportView1v1 | MatchReportView2v2 = self.view  # type: ignore[assignment]
        uid = interaction.user.id
        locale = get_player_locale(uid)

        try:
            async with get_session().post(
                f"{BACKEND_URL}/players/{uid}/toggle_lobby_guide"
            ) as resp:
                data = await resp.json()
            # new_value is the new read_lobby_guide flag (True = dismissed),
            # which is the inverse of guide_visible.
            read_lobby_guide: bool = data.get("new_value", view.guide_visible)
        except Exception:
            logger.exception("Failed to toggle lobby guide for %s", uid)
            read_lobby_guide = view.guide_visible

        guide_visible = not read_lobby_guide
        view.guide_visible = guide_visible
        self.label, self.style = self._attrs(guide_visible, locale)
        await interaction.edit_original_response(
            embeds=view._build_embeds(locale), view=view
        )


class MatchReportView1v1(discord.ui.View):
    def __init__(
        self,
        match_id: int,
        p1_name: str,
        p2_name: str,
        match_data: dict | None = None,
        p1_info: dict[str, Any] | None = None,
        p2_info: dict[str, Any] | None = None,
        *,
        report_locked: bool = False,
        locale: str = "enUS",
        guide_visible: bool = True,
    ) -> None:
        super().__init__(timeout=None)
        self.match_id = match_id
        self._match_data = match_data or {}
        self._p1_info = p1_info
        self._p2_info = p2_info
        self._locale = locale
        self.guide_visible = guide_visible
        self.report_select = MatchReportSelect(
            match_id, p1_name, p2_name, locale=locale
        )
        self.report_select.disabled = report_locked
        self.add_item(self.report_select)
        self._toggle_button = LobbyGuideToggleButton(
            locale=locale, guide_visible=guide_visible
        )
        self.add_item(self._toggle_button)

    def _build_embeds(
        self, locale: str, pending_report: str | None = None
    ) -> list[discord.Embed]:
        server_code = self._match_data.get("server_name", "USW")
        return [
            MatchInfoEmbed1v1(
                self._match_data,
                self._p1_info,
                self._p2_info,
                pending_report=pending_report,
                locale=locale,
            ),
            LobbyGuideEmbed(server_code, locale=locale, visible=self.guide_visible),
        ]

    async def submit_report(
        self, interaction: discord.Interaction, report: str
    ) -> None:
        await interaction.response.defer()
        try:
            async with get_session().put(
                f"{BACKEND_URL}/matches_1v1/{self.match_id}/report",
                json={
                    "discord_uid": interaction.user.id,
                    "report": report,
                },
            ) as resp:
                data = await resp.json()

            if resp.status >= 400:
                _locale = get_player_locale(interaction.user.id)
                await interaction.followup.send(
                    embed=QueueErrorEmbed(
                        data.get("detail") or t("error.failed_submit_report", _locale),
                        locale=_locale,
                    ),
                    ephemeral=True,
                )
                return

            for option in self.report_select.options:
                option.default = option.value == report
            self.report_select.disabled = True
            locale = get_player_locale(interaction.user.id)
            await interaction.edit_original_response(
                embeds=self._build_embeds(locale, pending_report=report), view=self
            )

        except Exception:
            logger.exception("Failed to submit match report")
            _locale = get_player_locale(interaction.user.id)
            await interaction.followup.send(
                embed=QueueErrorEmbed(
                    t("error.unexpected_error", _locale), locale=_locale
                ),
                ephemeral=True,
            )


# =========================================================================
# Queue: HTTP action helpers
# =========================================================================


async def _fetch_mmrs(discord_uid: int) -> dict[str, int]:
    """Fetch all MMR rows for a player and return a {race: mmr} mapping."""
    try:
        async with get_session().get(f"{BACKEND_URL}/mmrs_1v1/{discord_uid}") as resp:
            data = await resp.json()
            return {row["race"]: row["mmr"] for row in data.get("mmrs", [])}
    except Exception:
        logger.warning("Failed to fetch MMRs", discord_uid=discord_uid)
        return {}


async def _join_queue(
    interaction: discord.Interaction,
    discord_user_id: int,
    bw_race: str | None,
    sc2_race: str | None,
    map_vetoes: list[str],
) -> None:
    if bw_race is None and sc2_race is None:
        _locale = get_player_locale(discord_user_id)
        await interaction.response.send_message(
            embed=QueueErrorEmbed(
                t("error.select_at_least_one_race", _locale), locale=_locale
            ),
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    try:
        mmrs = await _fetch_mmrs(discord_user_id)

        async with get_session().post(
            f"{BACKEND_URL}/queue_1v1/join",
            json={
                "discord_uid": discord_user_id,
                "discord_username": interaction.user.name,
                "bw_race": bw_race,
                "sc2_race": sc2_race,
                "bw_mmr": mmrs.get(bw_race) if bw_race else None,
                "sc2_mmr": mmrs.get(sc2_race) if sc2_race else None,
                "map_vetoes": map_vetoes,
            },
        ) as resp:
            data = await resp.json()

        if resp.status >= 400:
            _locale = get_player_locale(discord_user_id)
            await interaction.edit_original_response(
                embed=QueueErrorEmbed(
                    data.get("detail") or t("error.failed_join_queue", _locale),
                    locale=_locale,
                ),
                view=None,
            )
            return

        stats: dict | None = None
        try:
            async with get_session().get(f"{BACKEND_URL}/queue_1v1/stats") as resp2:
                stats = await resp2.json()
        except Exception:
            pass

        searching_view = QueueSearchingView(
            interaction, discord_user_id, bw_race, sc2_race, map_vetoes
        )
        locale = get_player_locale(discord_user_id)
        await interaction.edit_original_response(
            embed=QueueSearchingEmbed(stats, locale=locale),
            view=searching_view,
        )
        try:
            msg = await interaction.original_response()
            searching_view._message = msg
            get_cache().active_searching_messages[discord_user_id] = msg
            get_cache().active_searching_views[discord_user_id] = searching_view
        except Exception:
            logger.warning(
                "Could not cache searching message reference",
                discord_user_id=discord_user_id,
            )

        await searching_view.start_heartbeat()

    except Exception:
        logger.exception("Failed to join queue")
        _locale = get_player_locale(discord_user_id)
        await interaction.edit_original_response(
            embed=QueueErrorEmbed(t("error.unexpected_error", _locale), locale=_locale),
            view=None,
        )


async def _leave_queue(
    interaction: discord.Interaction,
    discord_user_id: int,
    bw_race: str | None,
    sc2_race: str | None,
    map_vetoes: list[str],
) -> None:
    await interaction.response.defer()
    try:
        async with get_session().delete(
            f"{BACKEND_URL}/queue_1v1/leave",
            json={"discord_uid": interaction.user.id},
        ) as resp:
            data = await resp.json()

        if resp.status >= 400:
            _locale = get_player_locale(interaction.user.id)
            await interaction.followup.send(
                embed=QueueErrorEmbed(
                    data.get("detail") or t("error.failed_leave_queue", _locale),
                    locale=_locale,
                ),
                ephemeral=True,
            )
            return

        setup_view = QueueSetupView1v1(discord_user_id, bw_race, sc2_race, map_vetoes)
        locale = get_player_locale(discord_user_id)
        embed = QueueSetupEmbed1v1(bw_race, sc2_race, map_vetoes, locale=locale)
        await interaction.edit_original_response(embed=embed, view=setup_view)

        try:
            cache = get_cache()
            cache.active_searching_messages.pop(interaction.user.id, None)
            view = cache.active_searching_views.pop(interaction.user.id, None)
            if view is not None and hasattr(view, "stop_heartbeat"):
                view.stop_heartbeat()
        except Exception:
            pass

    except Exception:
        logger.exception("Failed to leave queue")
        _locale = get_player_locale(interaction.user.id)
        await interaction.followup.send(
            embed=QueueErrorEmbed(t("error.unexpected_error", _locale), locale=_locale),
            ephemeral=True,
        )


async def _confirm_match(interaction: discord.Interaction, match_id: int) -> None:
    await interaction.response.defer()
    try:
        async with get_session().put(
            f"{BACKEND_URL}/matches_1v1/{match_id}/confirm",
            json={"discord_uid": interaction.user.id},
        ) as resp:
            await resp.json()

        locale = get_player_locale(interaction.user.id)
        if resp.status >= 400:
            await interaction.followup.send(
                embed=QueueErrorEmbed(
                    t("error.failed_confirm_match", locale), locale=locale
                ),
                ephemeral=True,
            )
            return

        msg = interaction.message
        if msg and msg.embeds:
            embed = msg.embeds[0]
            embed.add_field(
                name=t("match_found_embed.field_name.confirmed", locale),
                value=t("match_found_embed.field_value.confirmed", locale),
                inline=False,
            )
        else:
            embed = MatchConfirmedEmbed(match_id, locale=locale)
        await interaction.edit_original_response(embed=embed, view=None)

    except Exception:
        logger.exception("Failed to confirm match")
        _locale = get_player_locale(interaction.user.id)
        await interaction.followup.send(
            embed=QueueErrorEmbed(t("error.unexpected_error", _locale), locale=_locale),
            ephemeral=True,
        )


async def _abort_match(interaction: discord.Interaction, match_id: int) -> None:
    await interaction.response.defer()
    try:
        async with get_session().put(
            f"{BACKEND_URL}/matches_1v1/{match_id}/abort",
            json={"discord_uid": interaction.user.id},
        ) as resp:
            data = await resp.json()

        if resp.status >= 400:
            _locale = get_player_locale(interaction.user.id)
            await interaction.followup.send(
                embed=QueueErrorEmbed(
                    data.get("detail") or t("error.failed_abort_match", _locale),
                    locale=_locale,
                ),
                ephemeral=True,
            )
            return

        locale = get_player_locale(interaction.user.id)
        await interaction.edit_original_response(
            embed=MatchAbortAckEmbed(locale=locale),
            view=None,
        )

    except Exception:
        logger.exception("Failed to abort match")
        _locale = get_player_locale(interaction.user.id)
        await interaction.followup.send(
            embed=QueueErrorEmbed(t("error.unexpected_error", _locale), locale=_locale),
            ephemeral=True,
        )


# =========================================================================
# 2v2 Queue: selects
# =========================================================================


class CompSelect2v2(discord.ui.Select):
    """Select for a 2v2 composition slot.

    Each race in *race_codes* appears twice (suffixed ``_1`` / ``_2``) so
    both players can pick the same race.  ``max_values=2``: the first
    selection is the leader's race, the second is the partner's.
    """

    def __init__(
        self,
        comp: str,
        race_codes: list[str],
        selected_leader: str | None = None,
        selected_member: str | None = None,
        locale: str = "enUS",
        row: int = 1,
    ) -> None:
        self._comp = comp  # "pure_bw", "mixed", or "pure_sc2"
        # BW + BW and SC2 + SC2 comps need duplicate options (_1/_2 suffixes)
        # so both players can pick the same race (e.g. BW Terran mirror).
        # BW + SC2 comp has 6 unique races (one per BW/SC2 T/Z/P) — no duplicates needed.
        needs_duplicates = comp != "mixed"
        races = get_races()
        options: list[discord.SelectOption] = []
        for code in race_codes:
            if code not in races:
                continue
            label = t(f"race.{code}.name", locale)
            emoji = get_race_emote(code)
            if needs_duplicates:
                for suffix in ("_1", "_2"):
                    value = f"{code}{suffix}"
                    is_default = (code == selected_leader and suffix == "_1") or (
                        code == selected_member and suffix == "_2"
                    )
                    options.append(
                        discord.SelectOption(
                            label=label,
                            value=value,
                            emoji=emoji,
                            default=is_default,
                        )
                    )
            else:
                is_default = code == selected_leader or code == selected_member
                options.append(
                    discord.SelectOption(
                        label=label,
                        value=code,
                        emoji=emoji,
                        default=is_default,
                    )
                )
        placeholders = {
            "pure_bw": t("comp.bw_bw.1", locale),
            "mixed": t("comp.bw_sc2.1", locale),
            "pure_sc2": t("comp.sc2_sc2.1", locale),
        }
        super().__init__(
            placeholder=placeholders.get(comp, "Select races"),
            min_values=0,
            max_values=2,
            options=options,
            row=row,
        )

    @staticmethod
    def strip_suffix(value: str) -> str:
        """Remove the ``_1`` / ``_2`` uniqueness suffix."""
        if value.endswith(("_1", "_2")):
            return value[:-2]
        return value

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QueueSetupView2v2 = self.view  # type: ignore[assignment]
        if len(self.values) == 2:
            leader = self.strip_suffix(self.values[0])
            member = self.strip_suffix(self.values[1])
        elif len(self.values) == 1:
            leader = self.strip_suffix(self.values[0])
            member = None
        else:
            leader = None
            member = None

        if self._comp == "pure_bw":
            view.pure_bw_leader_race = leader
            view.pure_bw_member_race = member
        elif self._comp == "mixed":
            view.mixed_leader_race = leader
            view.mixed_member_race = member
        else:
            view.pure_sc2_leader_race = leader
            view.pure_sc2_member_race = member
        await view.persist_and_refresh(interaction)


class MapVetoSelect2v2(discord.ui.Select):
    def __init__(self, selected: list[str] | None = None, locale: str = "enUS") -> None:
        maps = get_maps(game_mode="2v2", season=CURRENT_SEASON) or {}
        options = [
            discord.SelectOption(
                label=map_data["short_name"],
                value=map_name,
                emoji=get_game_emote(map_data.get("game", "sc2")),
                default=(map_name in (selected or [])),
            )
            for map_name, map_data in sorted(maps.items())
        ]
        if not options:
            options = [
                discord.SelectOption(
                    label=t("queue_select.no_maps_available", locale), value="none"
                )
            ]
        super().__init__(
            placeholder=t(
                "queue_select.placeholder.map_veto",
                locale,
                max_vetoes=str(MAX_MAP_VETOES),
            ),
            min_values=0,
            max_values=min(MAX_MAP_VETOES, len(options)),
            options=options,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QueueSetupView2v2 = self.view  # type: ignore[assignment]
        view.map_vetoes = [v for v in self.values if v != "none"]
        await view.persist_and_refresh(interaction)


class MatchReportSelect2v2(discord.ui.Select):
    def __init__(self, match_id: int, locale: str = "enUS") -> None:
        self.match_id = match_id
        options = [
            discord.SelectOption(label="Team 1 wins", value="team_1_win"),
            discord.SelectOption(label="Team 2 wins", value="team_2_win"),
            discord.SelectOption(label="Draw", value="draw"),
        ]
        super().__init__(
            placeholder="Report result...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: MatchReportView2v2 = self.view  # type: ignore[assignment]
        await view.submit_report(interaction, self.values[0])


# =========================================================================
# 2v2 Queue: views
# =========================================================================


class QueueSetupView2v2(discord.ui.View):
    def __init__(
        self,
        discord_user_id: int,
        pure_bw_leader_race: str | None = None,
        pure_bw_member_race: str | None = None,
        mixed_leader_race: str | None = None,
        mixed_member_race: str | None = None,
        pure_sc2_leader_race: str | None = None,
        pure_sc2_member_race: str | None = None,
        map_vetoes: list[str] | None = None,
        leader_player_name: str = "Leader",
        member_player_name: str = "Member",
    ) -> None:
        super().__init__(timeout=300)
        self.discord_user_id = discord_user_id
        self.pure_bw_leader_race = pure_bw_leader_race
        self.pure_bw_member_race = pure_bw_member_race
        self.mixed_leader_race = mixed_leader_race
        self.mixed_member_race = mixed_member_race
        self.pure_sc2_leader_race = pure_sc2_leader_race
        self.pure_sc2_member_race = pure_sc2_member_race
        self.map_vetoes = map_vetoes or []
        self.leader_player_name = leader_player_name
        self.member_player_name = member_player_name
        self._build()

    def _build(self) -> None:
        self.clear_items()
        _locale = get_player_locale(self.discord_user_id)

        # Row 0: action buttons
        async def on_join(interaction: discord.Interaction) -> None:
            await _join_queue_2v2(
                interaction,
                self.discord_user_id,
                self.pure_bw_leader_race,
                self.pure_bw_member_race,
                self.mixed_leader_race,
                self.mixed_member_race,
                self.pure_sc2_leader_race,
                self.pure_sc2_member_race,
                self.map_vetoes,
                self.leader_player_name,
                self.member_player_name,
            )

        join_btn: discord.ui.Button[QueueSetupView2v2] = discord.ui.Button(
            label=t("button.join_queue", _locale),
            emoji="🚀",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        join_btn.callback = on_join  # type: ignore[method-assign]
        self.add_item(join_btn)

        async def on_clear(interaction: discord.Interaction) -> None:
            self.pure_bw_leader_race = None
            self.pure_bw_member_race = None
            self.mixed_leader_race = None
            self.mixed_member_race = None
            self.pure_sc2_leader_race = None
            self.pure_sc2_member_race = None
            self.map_vetoes = []
            await self.persist_and_refresh(interaction)

        clear_btn: discord.ui.Button[QueueSetupView2v2] = discord.ui.Button(
            label=t("button.clear_selections", _locale),
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        clear_btn.callback = on_clear  # type: ignore[method-assign]
        self.add_item(clear_btn)

        async def on_cancel(interaction: discord.Interaction) -> None:
            if interaction.message is not None:
                await interaction.message.delete()

        cancel_btn: discord.ui.Button[QueueSetupView2v2] = discord.ui.Button(
            label=t("button.cancel", _locale),
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        cancel_btn.callback = on_cancel  # type: ignore[method-assign]
        self.add_item(cancel_btn)

        bw_codes = get_bw_race_codes()
        sc2_codes = get_sc2_race_codes()

        # Row 1: BW + BW composition
        self.add_item(
            CompSelect2v2(
                "pure_bw",
                bw_codes,
                self.pure_bw_leader_race,
                self.pure_bw_member_race,
                locale=_locale,
                row=1,
            )
        )
        # Row 2: BW + SC2 composition
        self.add_item(
            CompSelect2v2(
                "mixed",
                bw_codes + sc2_codes,
                self.mixed_leader_race,
                self.mixed_member_race,
                locale=_locale,
                row=2,
            )
        )
        # Row 3: SC2 + SC2 composition
        self.add_item(
            CompSelect2v2(
                "pure_sc2",
                sc2_codes,
                self.pure_sc2_leader_race,
                self.pure_sc2_member_race,
                locale=_locale,
                row=3,
            )
        )
        # Row 4: Map vetoes
        self.add_item(MapVetoSelect2v2(self.map_vetoes, locale=_locale))

    async def persist_and_refresh(self, interaction: discord.Interaction) -> None:
        """Save preferences to backend and refresh the embed."""
        try:
            async with get_session().put(
                f"{BACKEND_URL}/preferences_2v2",
                json={
                    "discord_uid": self.discord_user_id,
                    "last_pure_bw_leader_race": self.pure_bw_leader_race,
                    "last_pure_bw_member_race": self.pure_bw_member_race,
                    "last_mixed_leader_race": self.mixed_leader_race,
                    "last_mixed_member_race": self.mixed_member_race,
                    "last_pure_sc2_leader_race": self.pure_sc2_leader_race,
                    "last_pure_sc2_member_race": self.pure_sc2_member_race,
                    "last_chosen_vetoes": sorted(self.map_vetoes),
                },
            ) as resp:
                await resp.json()
        except Exception:
            logger.warning("Failed to persist 2v2 preferences", exc_info=True)

        new_view = QueueSetupView2v2(
            self.discord_user_id,
            self.pure_bw_leader_race,
            self.pure_bw_member_race,
            self.mixed_leader_race,
            self.mixed_member_race,
            self.pure_sc2_leader_race,
            self.pure_sc2_member_race,
            self.map_vetoes,
            leader_player_name=self.leader_player_name,
            member_player_name=self.member_player_name,
        )
        locale = get_player_locale(self.discord_user_id)
        embed = QueueSetupEmbed2v2(
            self.pure_bw_leader_race,
            self.pure_bw_member_race,
            self.mixed_leader_race,
            self.mixed_member_race,
            self.pure_sc2_leader_race,
            self.pure_sc2_member_race,
            self.map_vetoes,
            leader_player_name=self.leader_player_name,
            member_player_name=self.member_player_name,
            locale=locale,
        )
        await interaction.response.edit_message(embed=embed, view=new_view)


class MatchFoundView2v2(discord.ui.View):
    def __init__(self, match_id: int, locale: str = "enUS") -> None:
        super().__init__(timeout=CONFIRMATION_TIMEOUT)
        self.match_id = match_id

        async def on_confirm(interaction: discord.Interaction) -> None:
            await _confirm_match_2v2(interaction, match_id)

        confirm_btn: discord.ui.Button[MatchFoundView2v2] = discord.ui.Button(
            label=t("button.confirm_match", locale),
            emoji="✅",
            style=discord.ButtonStyle.green,
            row=0,
        )
        confirm_btn.callback = on_confirm  # type: ignore[method-assign]
        self.add_item(confirm_btn)

        async def on_abort(interaction: discord.Interaction) -> None:
            await _abort_match_2v2(interaction, match_id)

        abort_btn: discord.ui.Button[MatchFoundView2v2] = discord.ui.Button(
            label=t("button.abort_match", locale),
            emoji="🛑",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        abort_btn.callback = on_abort  # type: ignore[method-assign]
        self.add_item(abort_btn)


class MatchReportView2v2(discord.ui.View):
    def __init__(
        self,
        match_id: int,
        match_data: dict | None = None,
        player_infos: dict | None = None,
        *,
        report_locked: bool = False,
        locale: str = "enUS",
        guide_visible: bool = True,
    ) -> None:
        super().__init__(timeout=None)
        self.match_id = match_id
        self._match_data = match_data or {}
        self._player_infos = player_infos or {}
        self._locale = locale
        self.guide_visible = guide_visible
        self.report_select = MatchReportSelect2v2(match_id, locale=locale)
        self.report_select.disabled = report_locked
        self.add_item(self.report_select)
        self._toggle_button = LobbyGuideToggleButton(
            locale=locale, guide_visible=guide_visible
        )
        self.add_item(self._toggle_button)

    def _build_embeds(
        self, locale: str, pending_report: str | None = None
    ) -> list[discord.Embed]:
        server_code = self._match_data.get("server_name", "USW")
        return list(
            MatchInfoEmbeds2v2(
                self._match_data,
                self._player_infos,
                pending_report=pending_report,
                locale=locale,
            )
        ) + [LobbyGuideEmbed(server_code, locale=locale, visible=self.guide_visible)]

    async def submit_report(
        self, interaction: discord.Interaction, report: str
    ) -> None:
        await interaction.response.defer()
        try:
            async with get_session().put(
                f"{BACKEND_URL}/matches_2v2/{self.match_id}/report",
                json={
                    "discord_uid": interaction.user.id,
                    "report": report,
                },
            ) as resp:
                data = await resp.json()

            if resp.status >= 400:
                _locale = get_player_locale(interaction.user.id)
                await interaction.followup.send(
                    embed=QueueErrorEmbed(
                        data.get("detail") or t("error.failed_submit_report", _locale),
                        locale=_locale,
                    ),
                    ephemeral=True,
                )
                return

            for option in self.report_select.options:
                option.default = option.value == report
            self.report_select.disabled = True
            locale = get_player_locale(interaction.user.id)
            await interaction.edit_original_response(
                embeds=self._build_embeds(locale, pending_report=report), view=self
            )

        except Exception:
            logger.exception("Failed to submit 2v2 match report")
            _locale = get_player_locale(interaction.user.id)
            await interaction.followup.send(
                embed=QueueErrorEmbed(
                    t("error.unexpected_error", _locale), locale=_locale
                ),
                ephemeral=True,
            )


# =========================================================================
# 2v2 Queue: searching view + cancel button
# =========================================================================


class _CancelQueueButton2v2(discord.ui.Button["QueueSearchingView2v2"]):
    def __init__(
        self,
        discord_user_id: int,
        pure_bw_leader_race: str | None,
        pure_bw_member_race: str | None,
        mixed_leader_race: str | None,
        mixed_member_race: str | None,
        pure_sc2_leader_race: str | None,
        pure_sc2_member_race: str | None,
        map_vetoes: list[str],
        leader_player_name: str,
        member_player_name: str,
    ) -> None:
        super().__init__(
            label=t("button.cancel_queue", get_player_locale(discord_user_id)),
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        self.discord_user_id = discord_user_id
        self.pure_bw_leader_race = pure_bw_leader_race
        self.pure_bw_member_race = pure_bw_member_race
        self.mixed_leader_race = mixed_leader_race
        self.mixed_member_race = mixed_member_race
        self.pure_sc2_leader_race = pure_sc2_leader_race
        self.pure_sc2_member_race = pure_sc2_member_race
        self.map_vetoes = map_vetoes
        self.leader_player_name = leader_player_name
        self.member_player_name = member_player_name

    async def callback(self, interaction: discord.Interaction) -> None:
        await _leave_queue_2v2(
            interaction,
            self.discord_user_id,
            self.pure_bw_leader_race,
            self.pure_bw_member_race,
            self.mixed_leader_race,
            self.mixed_member_race,
            self.pure_sc2_leader_race,
            self.pure_sc2_member_race,
            self.map_vetoes,
            self.leader_player_name,
            self.member_player_name,
        )


class QueueSearchingView2v2(discord.ui.View):
    """Searching view for 2v2 queue with heartbeat and cancel button."""

    def __init__(
        self,
        interaction: discord.Interaction,
        discord_user_id: int,
        pure_bw_leader_race: str | None,
        pure_bw_member_race: str | None,
        mixed_leader_race: str | None,
        mixed_member_race: str | None,
        pure_sc2_leader_race: str | None,
        pure_sc2_member_race: str | None,
        map_vetoes: list[str],
        leader_player_name: str,
        member_player_name: str,
    ) -> None:
        super().__init__(timeout=None)
        self._interaction = interaction
        self._message: discord.Message | None = None
        self._token_expired: bool = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self.add_item(
            _CancelQueueButton2v2(
                discord_user_id,
                pure_bw_leader_race,
                pure_bw_member_race,
                mixed_leader_race,
                mixed_member_race,
                pure_sc2_leader_race,
                pure_sc2_member_race,
                map_vetoes,
                leader_player_name,
                member_player_name,
            )
        )

    async def start_heartbeat(self) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Update the searching embed at the 15th second of every minute."""
        while True:
            try:
                now = time.time()
                current_minute_start = (now // 60) * 60
                next_beat = current_minute_start + 15
                if next_beat <= now:
                    next_beat += 60
                await asyncio.sleep(next_beat - now)

                stats: dict | None = None
                try:
                    async with get_session().get(
                        f"{BACKEND_URL}/queue_2v2/stats"
                    ) as resp:
                        stats = await resp.json()
                except Exception:
                    pass

                locale = get_player_locale(self._interaction.user.id)
                embed = QueueSearchingEmbed2v2(stats, locale=locale)
                await self._apply_searching_heartbeat_embed(embed)

            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("queue_2v2_heartbeat_error", exc_info=True)
                await asyncio.sleep(QUEUE_SEARCHING_HEARTBEAT_SECONDS)

    async def _apply_searching_heartbeat_embed(self, embed: discord.Embed) -> None:
        """Edit the searching DM using the interaction webhook while valid, else bot token."""
        if not self._token_expired:
            try:
                await self._interaction.edit_original_response(embed=embed, view=self)
                return
            except discord.HTTPException as e:
                if e.status != 401:
                    raise
                self._token_expired = True
                logger.info(
                    "queue_searching_2v2_webhook_token_expired",
                    discord_uid=self._interaction.user.id,
                )

        ref = self._message
        if ref is None:
            logger.warning(
                "queue_2v2_heartbeat_no_cached_message",
                discord_uid=self._interaction.user.id,
            )
            return

        ch = ref.channel
        if not isinstance(ch, discord.DMChannel):
            logger.warning(
                "queue_2v2_heartbeat_expected_dm",
                channel_type=type(ch).__name__,
                discord_uid=self._interaction.user.id,
            )
            return

        partial = ch.get_partial_message(ref.id)
        updated = await queue_message_edit_low(partial, embed=embed, view=self)
        self._message = updated
        get_cache().active_searching_messages[self._interaction.user.id] = updated

    def stop_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()


# =========================================================================
# 2v2 Queue: HTTP action helpers
# =========================================================================


async def _fetch_mmr_2v2(leader_uid: int, member_uid: int) -> int:
    """Fetch the pair MMR from the backend. Returns 1500 if not found."""
    try:
        async with get_session().get(
            f"{BACKEND_URL}/mmrs_2v2/{leader_uid}/{member_uid}"
        ) as resp:
            data = await resp.json()
            mmr_row = data.get("mmr")
            if mmr_row:
                return int(mmr_row.get("mmr", 1500))
    except Exception:
        logger.warning("Failed to fetch 2v2 MMR", exc_info=True)
    return 1500


async def _join_queue_2v2(
    interaction: discord.Interaction,
    discord_user_id: int,
    pure_bw_leader_race: str | None,
    pure_bw_member_race: str | None,
    mixed_leader_race: str | None,
    mixed_member_race: str | None,
    pure_sc2_leader_race: str | None,
    pure_sc2_member_race: str | None,
    map_vetoes: list[str],
    leader_player_name: str = "Leader",
    member_player_name: str = "Member",
) -> None:
    # At least one comp must have both leader and member selected.
    has_full_comp = (
        (pure_bw_leader_race is not None and pure_bw_member_race is not None)
        or (mixed_leader_race is not None and mixed_member_race is not None)
        or (pure_sc2_leader_race is not None and pure_sc2_member_race is not None)
    )
    if not has_full_comp:
        _locale = get_player_locale(discord_user_id)
        await interaction.response.send_message(
            embed=QueueErrorEmbed(
                t("error.queue_2v2_no_comp", _locale),
                locale=_locale,
            ),
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    try:
        async with get_session().post(
            f"{BACKEND_URL}/queue_2v2/join",
            json={
                "discord_uid": discord_user_id,
                "discord_username": interaction.user.name,
                "pure_bw_leader_race": pure_bw_leader_race,
                "pure_bw_member_race": pure_bw_member_race,
                "mixed_leader_race": mixed_leader_race,
                "mixed_member_race": mixed_member_race,
                "pure_sc2_leader_race": pure_sc2_leader_race,
                "pure_sc2_member_race": pure_sc2_member_race,
                "map_vetoes": map_vetoes,
            },
        ) as resp:
            data = await resp.json()

        if resp.status >= 400:
            _locale = get_player_locale(discord_user_id)
            await interaction.edit_original_response(
                embed=QueueErrorEmbed(
                    data.get("detail") or t("error.failed_join_queue", _locale),
                    locale=_locale,
                ),
                view=None,
            )
            return

        stats: dict | None = None
        try:
            async with get_session().get(f"{BACKEND_URL}/queue_2v2/stats") as resp2:
                stats = await resp2.json()
        except Exception:
            pass

        locale = get_player_locale(discord_user_id)
        searching_view = QueueSearchingView2v2(
            interaction,
            discord_user_id,
            pure_bw_leader_race,
            pure_bw_member_race,
            mixed_leader_race,
            mixed_member_race,
            pure_sc2_leader_race,
            pure_sc2_member_race,
            map_vetoes,
            leader_player_name,
            member_player_name,
        )
        await interaction.edit_original_response(
            embed=QueueSearchingEmbed2v2(stats, locale=locale),
            view=searching_view,
        )
        try:
            msg = await interaction.original_response()
            searching_view._message = msg
            cache = get_cache()
            cache.active_searching_messages[discord_user_id] = msg
            cache.active_searching_views[discord_user_id] = searching_view
        except Exception:
            logger.warning(
                "Could not cache 2v2 searching message reference",
                discord_user_id=discord_user_id,
            )

        await searching_view.start_heartbeat()

    except Exception:
        logger.exception("Failed to join 2v2 queue")
        _locale = get_player_locale(discord_user_id)
        await interaction.edit_original_response(
            embed=QueueErrorEmbed(t("error.unexpected_error", _locale), locale=_locale),
            view=None,
        )


async def _leave_queue_2v2(
    interaction: discord.Interaction,
    discord_user_id: int,
    pure_bw_leader_race: str | None,
    pure_bw_member_race: str | None,
    mixed_leader_race: str | None,
    mixed_member_race: str | None,
    pure_sc2_leader_race: str | None,
    pure_sc2_member_race: str | None,
    map_vetoes: list[str],
    leader_player_name: str = "Leader",
    member_player_name: str = "Member",
) -> None:
    await interaction.response.defer()
    try:
        async with get_session().delete(
            f"{BACKEND_URL}/queue_2v2/leave",
            json={"discord_uid": discord_user_id},
        ) as resp:
            data = await resp.json()

        if resp.status >= 400:
            _locale = get_player_locale(discord_user_id)
            await interaction.followup.send(
                embed=QueueErrorEmbed(
                    data.get("detail") or t("error.failed_leave_queue", _locale),
                    locale=_locale,
                ),
                ephemeral=True,
            )
            return

        _locale = get_player_locale(discord_user_id)
        setup_embed = QueueSetupEmbed2v2(
            pure_bw_leader_race,
            pure_bw_member_race,
            mixed_leader_race,
            mixed_member_race,
            pure_sc2_leader_race,
            pure_sc2_member_race,
            map_vetoes,
            leader_player_name=leader_player_name,
            member_player_name=member_player_name,
            locale=_locale,
        )
        setup_view = QueueSetupView2v2(
            discord_user_id=discord_user_id,
            pure_bw_leader_race=pure_bw_leader_race,
            pure_bw_member_race=pure_bw_member_race,
            mixed_leader_race=mixed_leader_race,
            mixed_member_race=mixed_member_race,
            pure_sc2_leader_race=pure_sc2_leader_race,
            pure_sc2_member_race=pure_sc2_member_race,
            map_vetoes=map_vetoes,
            leader_player_name=leader_player_name,
            member_player_name=member_player_name,
        )
        await interaction.edit_original_response(embed=setup_embed, view=setup_view)

        try:
            cache = get_cache()
            cache.active_searching_messages.pop(discord_user_id, None)
            view = cache.active_searching_views.pop(discord_user_id, None)
            if view is not None and hasattr(view, "stop_heartbeat"):
                view.stop_heartbeat()
        except Exception:
            pass

    except Exception:
        logger.exception("Failed to leave 2v2 queue")
        _locale = get_player_locale(discord_user_id)
        await interaction.followup.send(
            embed=QueueErrorEmbed(t("error.unexpected_error", _locale), locale=_locale),
            ephemeral=True,
        )


async def _confirm_match_2v2(interaction: discord.Interaction, match_id: int) -> None:
    await interaction.response.defer()
    try:
        async with get_session().put(
            f"{BACKEND_URL}/matches_2v2/{match_id}/confirm",
            json={"discord_uid": interaction.user.id},
        ) as resp:
            await resp.json()

        locale = get_player_locale(interaction.user.id)
        if resp.status >= 400:
            await interaction.followup.send(
                embed=QueueErrorEmbed(
                    t("error.failed_confirm_match", locale), locale=locale
                ),
                ephemeral=True,
            )
            return

        msg = interaction.message
        if msg and msg.embeds:
            embed = msg.embeds[0]
            embed.add_field(
                name=t("match_found_embed.field_name.confirmed", locale),
                value=t("match_found_embed.field_value.confirmed", locale),
                inline=False,
            )
        else:
            embed = MatchConfirmedEmbed(match_id, locale=locale)
        await interaction.edit_original_response(embed=embed, view=None)

    except Exception:
        logger.exception("Failed to confirm 2v2 match")
        _locale = get_player_locale(interaction.user.id)
        await interaction.followup.send(
            embed=QueueErrorEmbed(t("error.unexpected_error", _locale), locale=_locale),
            ephemeral=True,
        )


async def _abort_match_2v2(interaction: discord.Interaction, match_id: int) -> None:
    await interaction.response.defer()
    try:
        async with get_session().put(
            f"{BACKEND_URL}/matches_2v2/{match_id}/abort",
            json={"discord_uid": interaction.user.id},
        ) as resp:
            data = await resp.json()

        if resp.status >= 400:
            _locale = get_player_locale(interaction.user.id)
            await interaction.followup.send(
                embed=QueueErrorEmbed(
                    data.get("detail") or t("error.failed_abort_match", _locale),
                    locale=_locale,
                ),
                ephemeral=True,
            )
            return

        locale = get_player_locale(interaction.user.id)
        await interaction.edit_original_response(
            embed=MatchAbortAckEmbed(locale=locale),
            view=None,
        )

    except Exception:
        logger.exception("Failed to abort 2v2 match")
        _locale = get_player_locale(interaction.user.id)
        await interaction.followup.send(
            embed=QueueErrorEmbed(t("error.unexpected_error", _locale), locale=_locale),
            ephemeral=True,
        )
