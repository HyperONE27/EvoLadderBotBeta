import discord
from typing import Callable


class ConfirmButton(discord.ui.Button):
    def __init__(
        self,
        *,
        callback: Callable,
        label: str = "Confirm",
        style: discord.ButtonStyle = discord.ButtonStyle.green,
        row: int = 0,
    ):
        super().__init__(label=label, style=style, emoji="✅", row=row)
        self.callback_func = callback

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            for item in self.view.children:
                if hasattr(item, "disabled"):
                    item.disabled = True

        await self.callback_func(interaction)


class RestartButton(discord.ui.Button):
    def __init__(
        self,
        *,
        callback: Callable,
        label: str = "Restart",
        style: discord.ButtonStyle = discord.ButtonStyle.gray,
        row: int = 0,
    ):
        super().__init__(label=label, style=style, emoji="🔄", row=row)
        self.callback_func = callback

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            for item in self.view.children:
                if hasattr(item, "disabled"):
                    item.disabled = True

        await self.callback_func(interaction)


class CancelButton(discord.ui.Button):
    def __init__(
        self,
        *,
        label: str = "Cancel",
        style: discord.ButtonStyle = discord.ButtonStyle.red,
        row: int = 0,
    ):
        super().__init__(label=label, style=style, emoji="✖️", row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            for item in self.view.children:
                if hasattr(item, "disabled"):
                    item.disabled = True

        if interaction.message is not None:
            await interaction.message.delete()
