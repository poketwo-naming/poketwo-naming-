"""
Pokétwo Naming Bot - Core bot functionality for naming Pokémon
"""
from collections import deque
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import asyncio
import json
import os
import re
from time import perf_counter, time
from typing import cast
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands
from geonamescache import GeonamesCache
from PIL import Image, UnidentifiedImageError

from pokemon_recognition import PokemonImageRecognizer
from tools.build_pokemon_types import (
    CUSTOM_SPRITE_IDENTIFIERS,
    normalize as normalize_pokemon_alias,
)


POKETWO_BOT_ID = 716390085896962058
MISSINGNO_ALERT_ROLE_ID = 1573065640762151003
TRAINING_REVIEW_CHANNEL_ID = 1531476097970212915
INCENSE_INACTIVITY_SECONDS = float(
    os.getenv("INCENSE_INACTIVITY_SECONDS", "90")
)
TRAINING_ROOT = "pokemon_images/training_data"
TRAINING_COLLECTION_FILE = "pokemon_images/new_training_images.json"
MODEL_READ_VERSION = "V2.0.0"
TRAINING_REVIEWER_USER_IDS = {217819108329259008}
BOT_STATE_FILE = os.getenv("BOT_STATE_FILE", "bot_state.json")
PREMIUM_MAIN_GUILD_ID = 1530949341013868635
REVIEW_CONFIDENCE_THRESHOLD = float(
    os.getenv("REVIEW_CONFIDENCE_THRESHOLD", "50")
)
PREMIUM_CAPACITIES = {
    "bronze": 100,
    "silver": 200,
    "gold": 300,
}
REGIONAL_PREFIXES = ("Alolan ", "Galarian ", "Hisuian ", "Paldean ")
TIMEZONE_PHASE_EMOJIS = {
    "day": "☀️",
    "night": "🌙",
    "dawn": "🌅",
    "dusk": "🌇",
}
COMMAND_CATALOG = (
    ("General", "v!ping", "Shows the bot's gateway latency."),
    (
        "General",
        "v!tz <day|night|dawn|dusk>",
        "Finds one place currently in that local-time phase and gives a Pokétwo command.",
    ),
    ("General", "v!help [page]", "Shows all commands with descriptions, paginated."),
    ("General", "v!commands [page]", "Shows categorized command names, paginated."),
    (
        "Recognition",
        "v!api",
        "Shows global incense, recognition, inference, and response metrics.",
    ),
    ("Recognition", "v!servers", "Lists every server where the bot is connected."),
    (
        "Reservations",
        "v!resume",
        "Resumes Pokétwo in a channel paused after MissingNo. Restricted.",
    ),
    (
        "Reservations",
        "v!r add [all] <pokemon,...> <@user>",
        "Reserves comma-separated Pokémon/forms for a member. Restricted.",
    ),
    (
        "Reservations",
        "v!r remove <pokemon,...> [@user]",
        "Removes Pokémon or a category of reservations. Restricted.",
    ),
    (
        "Reservations",
        "v!r search <pokemon>",
        "Shows who has a Pokémon reserved in an embed.",
    ),
    (
        "Reservations",
        "v!r list [@user]",
        "Lists server reservations, optionally filtered to one member.",
    ),
    (
        "Reservations",
        "v!reserve list [@user]",
        "Lists server reservations using the long-form command.",
    ),
    (
        "Reservations",
        "v!r clear",
        "Asks for confirmation before clearing every server reservation. Restricted.",
    ),
    (
        "Reservations",
        "v!grab",
        "Replies to a reserve list with sorting, form, copy, and reserve controls.",
    ),
    (
        "Reservations",
        "h!grab",
        "Uses the grab UI and delegates each reserve through h!r before v!r.",
    ),
    (
        "Shiny Hunts",
        "v!sh [all] [pokemon]",
        "Starts/switches a hunt (optionally all forms), or shows your current Pokémon.",
    ),
    ("Shiny Hunts", "v!sh clear", "Clears your current shiny hunt."),
    (
        "Shiny Hunts",
        "v!afk",
        "Opens buttons to turn shiny hunt/collection pings on or off.",
    ),
    (
        "Collections",
        "v!cl add [all] <pokemon,...>",
        "Adds comma-separated Pokémon/forms to your collection.",
    ),
    (
        "Collections",
        "v!cl remove <pokemon,...>",
        "Removes comma-separated Pokémon from your collection.",
    ),
    ("Collections", "v!cl list", "Lists your own collection."),
    ("Collections", "v!cl clear", "Clears your own collection."),
    (
        "Administration",
        "v!permission <role_id>",
        "Assigns the restricted-command role. Server administrators only.",
    ),
    (
        "Premium",
        "v!premium",
        "Shows the current server's Bronze, Silver, or Gold tier.",
    ),
    (
        "Premium",
        "v!premium add <tier> <server_id>",
        "Grants a server tier. Bot owner from the main server only.",
    ),
    (
        "Premium",
        "v!premiumservers [alias: v!ps]",
        "Lists connected servers and their premium tiers.",
    ),
    (
        "Training",
        "v!training",
        "Shows the count of reviewed images waiting for model training.",
    ),
    (
        "Training",
        "v!export_training",
        "Downloads newly reviewed training images as a ZIP.",
    ),
)
TYPE_EMOJIS = {
    "water": "<:water:1560303864094130357>",
    "rock": "<:rock:1564789532384174100>",
    "grass": "<:grass:1560307079896502282>",
    "fire": "<:fire:1560301436074729532>",
    "dark": "<:dark:1564786204699005129>",
    "bug": "<:bug:1564785932496797757>",
    "steel": "<:Steel:1564789710440898610>",
    "psychic": "<:Psychic:1564788957437366342>",
    "poison": "<:Poison:1564788700687114310>",
    "normal": "<:Normal:1560305235279482930>",
    "ice": "<:Ice:1560307867200782386>",
    "ground": "<:Ground:1564789353648230441>",
    "ghost": "<:Ghost:1564787837306540213>",
    "flying": "<:Flying:1564787610143162489>",
    "fighting": "<:Fighting:1564787413547483156>",
    "fairy": "<:Fairy:1564786928631677068>",
    "electric": "<:Electric:1560306053164572732>",
    "dragon": "<:Dragon:1564786673840160818>",
}


def phase_at_location_time(
    now: datetime,
    timezone_name: str,
) -> str:
    """Return a place's Pokétwo time phase based on its local clock."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_hour = now.astimezone(ZoneInfo(timezone_name)).hour
    if 5 <= local_hour < 7:
        return "dawn"
    if 7 <= local_hour < 17:
        return "day"
    if 17 <= local_hour < 19:
        return "dusk"
    return "night"


@lru_cache(maxsize=1)
def timezone_locations() -> tuple[tuple[str, str], ...]:
    """Return common cities and their IANA timezones."""
    cities = GeonamesCache().get_cities().values()
    return tuple(
        (
            str(city["name"]),
            str(city["timezone"]),
        )
        for city in sorted(
            cities,
            key=lambda city: (
                -int(city.get("population") or 0),
                city["name"],
            ),
        )
        if city.get("timezone")
    )


def find_place_for_phase(
    phase: str,
    now: datetime | None = None,
) -> str | None:
    """Return one known place currently in the requested local-time phase."""
    current_time = now or datetime.now(timezone.utc)
    for place, timezone_name in timezone_locations():
        if phase_at_location_time(current_time, timezone_name) == phase:
            return place
    return None


def shiny_hunt_label(pokemon_name: str, all_forms: bool) -> str:
    return f"all {pokemon_name}" if all_forms else pokemon_name


def normalize_pokemon_name(name: str) -> str:
    """Validate a Pokémon name before using it as a training folder."""
    normalized = name.strip()
    if not normalized or normalized in {".", ".."}:
        raise ValueError("Enter a Pokémon name.")
    if "/" in normalized or "\\" in normalized or "\x00" in normalized:
        raise ValueError("Pokémon names cannot contain path separators.")
    if len(normalized) > 100:
        raise ValueError("Pokémon names must be 100 characters or fewer.")
    return normalized


class CorrectPokemonModal(discord.ui.Modal, title="Correct Pokémon Name"):
    """Collect the correct label after a rejected prediction."""

    pokemon_name = discord.ui.TextInput(
        label="Correct Pokémon name",
        placeholder="For example: Eevee",
        max_length=100,
    )

    def __init__(self, review):
        super().__init__()
        self.review = review

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.review.confirm(interaction, self.pokemon_name.value)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)


class SpawnReviewView(discord.ui.View):
    """Yes/No controls for reviewing a predicted Pokétwo spawn."""

    def __init__(self, cog, pokemon_name: str, image_data: bytes):
        super().__init__(timeout=None)
        self.cog = cog
        self.pokemon_name = pokemon_name
        self.image_data = image_data
        self.completed = False

    @staticmethod
    def can_review(interaction: discord.Interaction) -> bool:
        """Allow configured reviewers and server administrators."""
        if interaction.user.id in TRAINING_REVIEWER_USER_IDS:
            return True
        return bool(
            isinstance(interaction.user, discord.Member)
            and (
                interaction.user.guild_permissions.administrator
                or interaction.user.guild_permissions.manage_guild
            )
        )

    async def reject_unauthorized(self, interaction: discord.Interaction) -> bool:
        if self.can_review(interaction):
            return False
        await interaction.response.send_message(
            "Only an authorized reviewer can label this spawn.",
            ephemeral=True,
        )
        return True

    async def confirm(self, interaction: discord.Interaction, pokemon_name: str):
        if await self.reject_unauthorized(interaction):
            return
        if self.completed:
            await interaction.response.send_message(
                "This spawn has already been reviewed.",
                ephemeral=True,
            )
            return

        saved_name, saved_path = self.cog.save_training_image(
            pokemon_name,
            self.image_data,
        )
        self.completed = True
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Saved as **{saved_name}** for future recognition.\n`{saved_path}`",
            view=self,
        )

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm_prediction(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        if await self.reject_unauthorized(interaction):
            return
        await self.confirm(interaction, self.pokemon_name)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def correct_prediction(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        if await self.reject_unauthorized(interaction):
            return
        if self.completed:
            await interaction.response.send_message(
                "This spawn has already been reviewed.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(CorrectPokemonModal(self))


class ShinyHuntSwitchView(discord.ui.View):
    """Confirm replacing one shiny hunt with another."""

    def __init__(
        self,
        cog,
        guild_id: int,
        user_id: int,
        old_pokemon: str,
        new_pokemon: str,
        new_all_forms: bool = False,
    ):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.old_pokemon = old_pokemon
        self.new_pokemon = new_pokemon
        self.new_all_forms = new_all_forms
        self.completed = False

    async def reject_other_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return False
        await interaction.response.send_message(
            "Only the person starting this shiny hunt can answer.",
            ephemeral=True,
        )
        return True

    def disable_buttons(self):
        self.completed = True
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm_switch(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        if await self.reject_other_user(interaction):
            return
        if self.completed:
            await interaction.response.send_message(
                "This shiny-hunt change has already been handled.",
                ephemeral=True,
            )
            return
        self.cog.set_shiny_hunt(
            self.guild_id,
            self.user_id,
            self.new_pokemon,
            self.new_all_forms,
        )
        self.disable_buttons()
        await interaction.response.edit_message(
            content=(
                f"✅ Switched your shiny hunt from **{self.old_pokemon}** "
                f"to **{shiny_hunt_label(self.new_pokemon, self.new_all_forms)}**."
            ),
            view=self,
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def cancel_switch(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        if await self.reject_other_user(interaction):
            return
        if self.completed:
            await interaction.response.send_message(
                "This shiny-hunt change has already been handled.",
                ephemeral=True,
            )
            return
        self.disable_buttons()
        await interaction.response.edit_message(
            content=f"Kept your **{self.old_pokemon}** shiny hunt.",
            view=self,
        )


class AfkView(discord.ui.View):
    """On/Off buttons for shiny hunt and collection pings."""

    KINDS = (("shiny_hunt", "Shiny Hunt"), ("collection", "Collection"))

    class ToggleButton(discord.ui.Button):
        def __init__(self, owner: "AfkView", kind: str, enabled: bool):
            super().__init__(
                label="On" if enabled else "Off",
                style=discord.ButtonStyle.success
                if enabled
                else discord.ButtonStyle.danger,
            )
            self.owner = owner
            self.kind = kind

        async def callback(self, interaction: discord.Interaction) -> None:
            await self.owner.toggle_pings(interaction, self.kind)

    def __init__(self, cog, user_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.message: discord.Message | None = None
        self.refresh_buttons()

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(color=discord.Color.blurple())
        for kind, label in self.KINDS:
            on = self.cog.pings_enabled(self.user_id, kind)
            embed.add_field(
                name=f"{label} {'✅' if on else '❌'}",
                value="Receiving pings" if on else "AFK (muted)",
                inline=False,
            )
        return embed

    def refresh_buttons(self):
        self.clear_items()
        for kind, _ in self.KINDS:
            on = self.cog.pings_enabled(self.user_id, kind)
            self.add_item(self.ToggleButton(self, kind, on))

    async def toggle_pings(
        self,
        interaction: discord.Interaction,
        kind: str,
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran v!afk can use these buttons.",
                ephemeral=True,
            )
            return
        settings = self.cog.bot_state["afk"].setdefault(str(self.user_id), {})
        settings[kind] = not settings.get(kind, False)
        self.cog.save_bot_state()
        self.refresh_buttons()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    async def on_timeout(self):
        if self.message is not None:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class HelpPagesView(discord.ui.View):
    """Navigate paginated help and command-list embeds."""

    def __init__(self, author_id: int, pages: list[discord.Embed]):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.pages = pages
        self.page = 0
        self.update_buttons()

    def update_buttons(self):
        self.previous_button.disabled = len(self.pages) < 2 or self.page == 0
        self.next_button.disabled = (
            len(self.pages) < 2 or self.page == len(self.pages) - 1
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Only the person who opened this help menu can change pages.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        self.page = max(0, self.page - 1)
        self.update_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.page],
            view=self,
        )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        self.page = min(len(self.pages) - 1, self.page + 1)
        self.update_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.page],
            view=self,
        )


class ReserveListView(discord.ui.View):
    """Paginate a server or member reserve list."""

    def __init__(self, author_id: int, pages: list[discord.Embed]):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.pages = pages
        self.page = 0
        self.refresh_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Only the person who opened this reserve list can change pages.",
            ephemeral=True,
        )
        return False

    def refresh_buttons(self):
        self.previous_button.disabled = len(self.pages) < 2 or self.page == 0
        self.next_button.disabled = (
            len(self.pages) < 2 or self.page == len(self.pages) - 1
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        self.page = max(0, self.page - 1)
        self.refresh_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.page],
            view=self,
        )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        self.page = min(len(self.pages) - 1, self.page + 1)
        self.refresh_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.page],
            view=self,
        )


class ClearReservesView(discord.ui.View):
    """Confirm clearing every reservation in one server."""

    def __init__(self, cog, guild_id: int, user_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self.completed = False

    async def reject_other_user(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return False
        await interaction.response.send_message(
            "Only the person who requested this clear can answer.",
            ephemeral=True,
        )
        return True

    def disable_buttons(self):
        self.completed = True
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def confirm_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        if await self.reject_other_user(interaction):
            return
        if self.completed:
            return
        reserves = self.cog.bot_state["reserves"].setdefault(
            str(self.guild_id),
            {},
        )
        count = len(reserves)
        reserves.clear()
        self.cog.save_bot_state()
        self.disable_buttons()
        await interaction.response.edit_message(
            content=f"✅ Cleared **{count}** Pokémon reserve(s).",
            view=self,
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel_clear(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        if await self.reject_other_user(interaction):
            return
        if self.completed:
            return
        self.disable_buttons()
        await interaction.response.edit_message(
            content="Reservation clear cancelled.",
            view=self,
        )


class ExchangeReservesView(discord.ui.View):
    """Confirm moving reserves from one user to the users in a replied list."""

    def __init__(self, cog, guild_id, author_id, from_id, entries):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = str(guild_id)
        self.author_id = author_id
        self.from_id = str(from_id)
        self.entries = entries
        self.completed = False

    def missing(self) -> list[str]:
        return [
            name
            for _, name in self.entries
            if self.from_id not in self.cog.reserve_user_ids(self.guild_id, name)
        ]

    def build_embed(self) -> discord.Embed:
        grouped: dict[str, list[str]] = {}
        for user_id, name in self.entries:
            grouped.setdefault(user_id, []).append(name)
        lines = [
            f"• <@{user_id}> - {', '.join(names)}"
            for user_id, names in grouped.items()
        ]
        description = (
            f"**Remove from:** <@{self.from_id}>\n\n**Add to:**\n"
            + "\n".join(lines)
        )
        missing = self.missing()
        if missing:
            shown = ", ".join(missing[:15])
            if len(missing) > 15:
                shown += f" (+{len(missing) - 15} more)"
            description += (
                "\n\n⚠️ This user does not currently have these reserves:\n"
                f"{shown}\nThese will be skipped. Please make sure you used "
                "the right original user before confirming."
            )
        description += "\n\n**Green check exchanges these reserves. Red check cancels.**"
        return discord.Embed(
            title="Confirm Reserve Exchange",
            description=description[:4096],
        )

    def finish(self):
        self.completed = True
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def allowed(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id or self.completed:
            await interaction.response.send_message(
                "Only the person who ran this command can answer.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="✔", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button):
        del button
        if not await self.allowed(interaction):
            return
        moved = 0
        for user_id, name in self.entries:
            if self.cog.remove_reserve_owner(self.guild_id, name, self.from_id):
                self.cog.add_reserve_owner(self.guild_id, name, user_id)
                moved += 1
        self.cog.save_bot_state()
        self.finish()
        await interaction.response.edit_message(
            content=f"✅ Exchanged **{moved}** reserve(s) from <@{self.from_id}>.",
            embed=None,
            view=self,
        )

    @discord.ui.button(label="✖", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button):
        del button
        if not await self.allowed(interaction):
            return
        self.finish()
        await interaction.response.edit_message(
            content="Reserve exchange cancelled.", embed=None, view=self
        )


class ServerSettingsView(discord.ui.LayoutView):
    """Settings menu; the Open buttons are placeholders for now."""

    SECTIONS = (
        ("Naming", "Naming `On` · Mode `Assisted`"),
        (
            "Roles & Pings",
            "Configure ping roles and rare, regional, hunt, collection, "
            "reserve, and quest output.",
        ),
        ("Starboard", "Configure the main starboard and the separate shinyboard system."),
        ("Modules", "Control server-level Profile Tracking and Analytics data collection."),
        ("Appearance", "Set the bot's server profile, banner, and embed color."),
    )

    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        container = discord.ui.Container()
        container.add_item(
            discord.ui.TextDisplay(
                "## Server Settings\n"
                "Pick a section to configure. Changes inside each section save immediately."
            )
        )
        container.add_item(discord.ui.Separator())
        for name, description in self.SECTIONS:
            button = discord.ui.Button(label="Open", style=discord.ButtonStyle.primary)
            button.callback = self.placeholder
            container.add_item(
                discord.ui.Section(
                    f"**{name}**\n{description}",
                    accessory=button,
                )
            )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "Server settings are kept for this server's setup."
            )
        )
        self.add_item(container)

    async def placeholder(self, interaction: discord.Interaction):
        await interaction.response.defer()


class GrabReservesView(discord.ui.View):
    """Preview and confirm reservations parsed from a replied list."""

    def __init__(
        self,
        cog,
        author_id: int,
        channel_id: int,
        entries: list[tuple[str, str, bool, bool, str]],
        h_mode: bool = False,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.author_id = author_id
        self.channel_id = channel_id
        self.entries = entries
        self.h_mode = h_mode
        self.alphabetical = False
        self.has_all_form_entries = any(
            all_forms for _, _, all_forms, _, _ in entries
        )
        self.all_forms = self.has_all_form_entries
        self.custom_emoji = False
        self.processing = False
        self.refresh_button_labels()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Only the person who ran grab can use these controls.",
            ephemeral=True,
        )
        return False

    def expanded_entries(self) -> list[tuple[str, str, bool, str]]:
        entries = []
        for (
            user_id,
            pokemon_name,
            requested_all_forms,
            is_category,
            custom_emoji,
        ) in self.entries:
            if is_category:
                entries.append((user_id, pokemon_name, True, custom_emoji))
                continue
            names = (
                self.cog.resolve_pokemon_family(
                    pokemon_name,
                    include_regionals=False,
                )
                if self.all_forms and requested_all_forms
                else [pokemon_name]
            )
            entries.extend(
                (user_id, str(name), False, custom_emoji) for name in names
            )
        if self.alphabetical:
            entries.sort(key=lambda entry: (entry[1].casefold(), entry[0]))
        return entries

    def format_line(
        self,
        user_id: str,
        pokemon_name: str,
        is_category: bool = False,
        custom_emoji: str = "",
        include_user: bool = True,
    ) -> str:
        prefix = f"{custom_emoji} " if self.custom_emoji and custom_emoji else ""
        suffix = f" — <@{user_id}>" if include_user else ""
        return f"{prefix}{pokemon_name}{suffix}"

    def copy_text(self) -> str:
        return "\n".join(
            self.format_line(
                user_id,
                pokemon_name,
                is_category,
                custom_emoji,
                include_user=False,
            )
            for (
                user_id,
                pokemon_name,
                is_category,
                custom_emoji,
            ) in self.expanded_entries()
        )

    def build_embed(self) -> discord.Embed:
        entries = self.expanded_entries()
        description = "\n".join(
            self.format_line(
                user_id,
                pokemon_name,
                is_category,
                custom_emoji,
                include_user=False,
            )
            for (
                user_id,
                pokemon_name,
                is_category,
                custom_emoji,
            ) in entries[:50]
        )
        if len(entries) > 50:
            description += f"\n…and {len(entries) - 50} more"
        return discord.Embed(
            title="Grabbed Reserve List",
            description=description or "No valid entries.",
            color=discord.Color.purple(),
        ).set_footer(
            text=(
                f"{len(entries)} entry(s) • "
                f"{'Alphabetical' if self.alphabetical else 'Original order'} • "
                f"{'All forms on' if self.all_forms else 'All forms off'}"
            )
        )

    def refresh_button_labels(self):
        self.order_button.label = "Original" if self.alphabetical else "Alphabetical"
        self.forms_button.disabled = not self.has_all_form_entries
        self.forms_button.label = (
            "All forms on" if self.all_forms else "All forms off"
        )
        self.emoji_button.label = (
            "Hide custom emoji" if self.custom_emoji else "Custom emoji"
        )

    async def redraw(self, interaction: discord.Interaction):
        self.refresh_button_labels()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    @discord.ui.button(label="Order", style=discord.ButtonStyle.secondary)
    async def order_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        self.alphabetical = not self.alphabetical
        await self.redraw(interaction)

    @discord.ui.button(label="All forms off", style=discord.ButtonStyle.secondary)
    async def forms_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        self.all_forms = not self.all_forms
        await self.redraw(interaction)

    @discord.ui.button(label="Custom emoji", style=discord.ButtonStyle.secondary)
    async def emoji_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        self.custom_emoji = not self.custom_emoji
        await self.redraw(interaction)

    @discord.ui.button(label="Copy", style=discord.ButtonStyle.secondary)
    async def copy_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        text = self.copy_text()
        await interaction.response.send_message(
            f"```text\n{text[:1900]}\n```",
            ephemeral=True,
        )

    @discord.ui.button(label="Add reserves", style=discord.ButtonStyle.primary)
    async def add_reserves_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        if self.processing:
            await interaction.response.send_message(
                "Reservations are already being added.",
                ephemeral=True,
            )
            return
        if not interaction.guild or not self.cog.has_restricted_interaction_permission(
            interaction
        ):
            await interaction.response.send_message(
                "You do not have permission to add reserves.",
                ephemeral=True,
            )
            return
        self.processing = True
        entries = self.expanded_entries()
        preview = "\n".join(
            self.format_line(
                user_id,
                pokemon_name,
                is_category,
                custom_emoji,
                include_user=True,
            )
            for (
                user_id,
                pokemon_name,
                is_category,
                custom_emoji,
            ) in entries[:25]
        )
        if len(entries) > 25:
            preview += f"\n…and {len(entries) - 25} more"
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Add reserves?",
                description=preview,
                color=discord.Color.orange(),
            ),
            view=GrabConfirmView(
                self.cog,
                self.author_id,
                self.channel_id,
                entries,
                self.h_mode,
            ),
        )


class GrabConfirmView(discord.ui.View):
    """Confirm a parsed reserve batch."""

    def __init__(
        self,
        cog,
        author_id: int,
        channel_id: int,
        entries: list[tuple[str, str, bool, str]],
        h_mode: bool,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.author_id = author_id
        self.channel_id = channel_id
        self.entries = entries
        self.h_mode = h_mode
        self.completed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Only the person who opened this confirmation can answer.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button):
        del button
        if self.completed:
            return
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message(
                "This confirmation must be used in a message channel.",
                ephemeral=True,
            )
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Reservations can only be added inside a server.",
                ephemeral=True,
            )
            return
        self.completed = True
        await interaction.response.edit_message(
            content="Adding reserves…",
            embed=None,
            view=None,
        )
        for user_id, pokemon_name, is_category, _custom_emoji in self.entries:
            reserve_names = (
                self.cog.guild_categories(guild.id).get(pokemon_name, [])
                if is_category
                else [pokemon_name]
            )
            for reserve_name in reserve_names:
                if self.h_mode:
                    await channel.send(f"h!r add {reserve_name} <@{user_id}>")
                    try:
                        await self.cog.bot.wait_for(
                            "message",
                            check=lambda response: (
                                response.channel.id == self.channel_id
                                and response.author.bot
                                and response.author.id != self.cog.bot.user.id
                            ),
                            timeout=5,
                        )
                    except TimeoutError:
                        pass
                await self.cog.add_reserve_direct(
                    guild,
                    reserve_name,
                    user_id,
                )
            await channel.send(
                f"v!r add {pokemon_name} <@{user_id}>"
                f"\nReserve **{pokemon_name}** added to <@{user_id}>."
            )

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button):
        del button
        if self.completed:
            return
        self.completed = True
        await interaction.response.edit_message(
            content="Reserve import cancelled.",
            embed=None,
            view=None,
        )


class PokéTwoNamingBot(commands.Cog):
    """Pokétwo naming bot cog with commands for naming Pokémon"""

    def __init__(self, bot):
        self.bot = bot
        model_started = perf_counter()
        self.recognizer = PokemonImageRecognizer()
        self.model_load_seconds = perf_counter() - model_started
        self.json_load_seconds = 0.0
        self.http_session = None
        self.spawn_response_times = deque(maxlen=100)
        self.inference_times = deque(maxlen=100)
        self.store_times = deque(maxlen=100)
        self.last_spawn_metrics = None
        self.recognized_spawn_count = 0
        self.recent_spawn_times = {}
        self.class_names = {name.casefold(): name for name in self.recognizer.classes}
        self.pokemon_types = self.load_pokemon_types()
        self.pokemon_sprite_ids = self.load_pokemon_sprite_ids()
        self.pokemon_best_names = self.load_pokemon_best_names()
        self.pokemon_aliases = self.load_pokemon_aliases()
        self.pokemon_species = self.load_pokemon_species()
        self.reviewed_spawn_count = self.load_collected_training_count()
        self.bot_state = self.load_bot_state()
        self.seed_restricted_roles()
        self.active_incenses = {
            int(channel_id): float(expires_at)
            for channel_id, expires_at in self.bot_state["active_incenses"].items()
        }
        self.premium_servers_file = os.getenv(
            "PREMIUM_SERVERS_FILE",
            "data/premium_servers.json",
        )
        self.premium_servers = self.load_premium_servers()

    def load_pokemon_types(self):
        """Load and validate the type metadata for every model class."""
        with open("pokemon_types.json", "r", encoding="utf-8") as f:
            pokemon_types = json.load(f)
        missing_classes = [
            name for name in self.recognizer.classes if name not in pokemon_types
        ]
        if missing_classes:
            raise ValueError(
                "Missing Pokémon type mappings: " + ", ".join(missing_classes[:10])
            )
        return pokemon_types

    def load_pokemon_aliases(self):
        """Load localized and romanized Pokémon-name aliases."""
        with open("pokemon_aliases.json", "r", encoding="utf-8") as f:
            return json.load(f)

    def load_pokemon_species(self):
        """Load the species ID for each recognition class."""
        with open("pokemon_species.json", "r", encoding="utf-8") as f:
            species = json.load(f)
        missing_classes = [
            name for name in self.recognizer.classes if name not in species
        ]
        if missing_classes:
            raise ValueError(
                "Missing Pokémon species mappings: " + ", ".join(missing_classes[:10])
            )
        return species

    def load_pokemon_sprite_ids(self):
        """Load PokéAPI IDs used for transparent official artwork thumbnails."""
        with open("pokemon_sprite_ids.json", "r", encoding="utf-8") as f:
            return json.load(f)

    def resolve_pokemon_name(self, name: str) -> str | None:
        """Resolve English, localized, or romanized Pokémon input."""
        stripped = name.strip()
        canonical = self.class_names.get(stripped.casefold())
        if canonical is not None:
            return canonical
        return self.pokemon_aliases.get(normalize_pokemon_alias(stripped))

    def resolve_pokemon_family(
        self,
        name: str,
        include_regionals: bool = True,
    ) -> list[str]:
        """Resolve every trained class belonging to a Pokémon family."""
        canonical = self.resolve_pokemon_name(name)
        if canonical is None:
            return []
        is_regional = canonical.startswith(REGIONAL_PREFIXES)
        family_matches = []
        canonical_normalized = normalize_pokemon_alias(canonical)
        for class_name in self.class_names.values():
            class_normalized = normalize_pokemon_alias(class_name)
            matches_family = (
                canonical_normalized in class_normalized
                or class_name == canonical
            )
            if (
                matches_family
                and (
                    include_regionals
                    or is_regional
                    or not class_name.startswith(REGIONAL_PREFIXES)
                )
            ):
                family_matches.append(class_name)
        return sorted(set(family_matches), key=str.casefold)

    def resolve_pokemon_list(
        self,
        entry: str,
        include_all_regionals: bool = True,
    ) -> tuple[list[str], list[str]]:
        """Resolve a comma-separated list, with optional all-family terms."""
        pokemon_names = []
        unknown = []
        for raw_term in entry.split(","):
            term = raw_term.strip()
            if not term:
                continue
            add_all = term.casefold().startswith("all ")
            pokemon_input = term[4:].strip() if add_all else term
            if add_all:
                resolved = self.resolve_pokemon_family(
                    pokemon_input,
                    include_regionals=include_all_regionals,
                )
            else:
                pokemon_name = self.resolve_pokemon_name(pokemon_input)
                resolved = [pokemon_name] if pokemon_name else []
            if resolved:
                pokemon_names.extend(str(name) for name in resolved)
            else:
                unknown.append(pokemon_input)
        return list(dict.fromkeys(pokemon_names)), unknown

    def format_spawn_prediction(
        self,
        pokemon_name: str,
        confidence: float,
        guild_id: int | None = None,
        shiny_hunters: list[str] | None = None,
    ) -> tuple[str, discord.Embed]:
        """Build a copyable catch command and Pokémon embed."""
        icons = "".join(
            TYPE_EMOJIS[pokemon_type]
            for pokemon_type in self.pokemon_types[pokemon_name]
        )
        best_name = self.pokemon_best_names[pokemon_name]
        copy_command = f"@Pokétwo#8236 c {best_name.casefold()}"
        content = [
            f"{pokemon_name} {icons} {confidence:.2f}%",
            f"Best name: {best_name}",
        ]
        embed = discord.Embed(
            title=f"Catch {pokemon_name}",
            color=discord.Color.blurple(),
        )
        is_missingno = pokemon_name.casefold() == "missingno"
        if is_missingno:
            content.append("Do not catch this Pokémon.")
            embed.title = "MissingNo detected"
            embed.description = "**Do not catch this Pokémon.**"
        else:
            embed.description = f"**Copy Below**\n```\n{copy_command}\n```"

        if guild_id is not None:
            reserved_user_ids = self.reserve_user_ids(guild_id, pokemon_name)
            if reserved_user_ids:
                mentions = ", ".join(
                    f"<@{user_id}>" for user_id in reserved_user_ids
                )
                content.append(f"Reserved: {mentions}")
            elif not is_missingno:
                current_hunters = self.shiny_hunters_for_spawn(
                    guild_id,
                    pokemon_name,
                )
                shiny_hunters = list(
                    dict.fromkeys((shiny_hunters or []) + current_hunters)
                )
                if shiny_hunters:
                    mentions = ", ".join(
                        f"<@{user_id}>" for user_id in shiny_hunters
                    )
                    content.append(f"Shiny hunt pings: {mentions}")
                collection_owners = self.collection_owners_for_spawn(
                    guild_id,
                    pokemon_name,
                )
                if collection_owners:
                    mentions = ", ".join(
                        f"<@{user_id}>" for user_id in collection_owners
                    )
                    content.append(f"Collection pings: {mentions}")
            if not is_missingno:
                content.append(f"Click to Copy -> `{copy_command}`")
        elif not is_missingno:
            content.append(f"Click to Copy -> `{copy_command}`")
        return "\n".join(content), embed

    def set_shiny_hunt(
        self,
        guild_id: int,
        user_id: int,
        pokemon_name: str,
        all_forms: bool = False,
    ):
        """Create or replace a member's shiny hunt."""
        guild_hunts = self.bot_state["shiny_hunts"].setdefault(
            str(guild_id),
            {},
        )
        guild_hunts[str(user_id)] = {
            "pokemon": str(pokemon_name),
            "all_forms": all_forms,
        }
        self.save_bot_state()

    def shiny_hunters_for_spawn(
        self,
        guild_id: int,
        pokemon_name: str,
    ) -> list[str]:
        """Return members hunting a spawned Pokémon."""
        guild_hunts = self.bot_state["shiny_hunts"].get(str(guild_id), {})
        return [
            user_id
            for user_id, hunt in guild_hunts.items()
            if (
                hunt.get("pokemon") == pokemon_name
                or (
                    hunt.get("all_forms", False)
                    and self.pokemon_species.get(hunt.get("pokemon"))
                    == self.pokemon_species[pokemon_name]
                )
            )
            and self.pings_enabled(user_id, "shiny_hunt")
        ]

    def collection_owners_for_spawn(
        self,
        guild_id: int,
        pokemon_name: str,
    ) -> list[str]:
        """Return members collecting a spawned Pokémon who receive pings."""
        return [
            user_id
            for user_id, pokemon_names in self.bot_state.get(
                "collections",
                {},
            ).get(str(guild_id), {}).items()
            if pokemon_name in pokemon_names
            and self.pings_enabled(user_id, "collection")
        ]

    def pings_enabled(self, user_id, kind: str) -> bool:
        """Return whether a user receives pings of this kind (default: yes)."""
        muted = self.bot_state.get("afk", {}).get(str(user_id), {})
        return not muted.get(kind, False)

    def reserve_user_ids(self, guild_id, pokemon_name: str) -> list[str]:
        """Return all reserving user IDs, accepting legacy single-ID values."""
        stored = self.bot_state.get("reserves", {}).get(str(guild_id), {}).get(
            pokemon_name
        )
        if isinstance(stored, str):
            user_ids = [stored]
        elif isinstance(stored, list):
            user_ids = [str(user_id) for user_id in stored]
        else:
            return []
        return list(dict.fromkeys(user_ids))

    def add_reserve_owner(self, guild_id, pokemon_name: str, user_id) -> bool:
        """Add a reserving user without replacing existing owners."""
        guild_reserves = self.bot_state["reserves"].setdefault(str(guild_id), {})
        user_ids = self.reserve_user_ids(guild_id, pokemon_name)
        normalized_user_id = str(user_id)
        if normalized_user_id in user_ids:
            return False
        user_ids.append(normalized_user_id)
        guild_reserves[pokemon_name] = user_ids
        return True

    def remove_reserve_owner(self, guild_id, pokemon_name: str, user_id=None) -> bool:
        """Remove one owner, or every owner when no user ID is specified."""
        guild_reserves = self.bot_state["reserves"].get(str(guild_id), {})
        user_ids = self.reserve_user_ids(guild_id, pokemon_name)
        if not user_ids:
            return False
        if user_id is None:
            guild_reserves.pop(pokemon_name, None)
            return True
        normalized_user_id = str(user_id)
        if normalized_user_id not in user_ids:
            return False
        user_ids.remove(normalized_user_id)
        if user_ids:
            guild_reserves[pokemon_name] = user_ids
        else:
            guild_reserves.pop(pokemon_name, None)
        return True

    def load_pokemon_best_names(self):
        """Load and validate the shortest localized name for each model class."""
        with open("pokemon_best_names.json", "r", encoding="utf-8") as f:
            best_names = json.load(f)
        missing_classes = [
            name for name in self.recognizer.classes if name not in best_names
        ]
        if missing_classes:
            raise ValueError(
                "Missing Pokémon best-name mappings: "
                + ", ".join(missing_classes[:10])
            )
        return best_names

    async def cog_load(self):
        """Create shared HTTP resources for spawn image downloads."""
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )

    async def cog_unload(self):
        """Close shared resources."""
        if self.http_session is not None:
            await self.http_session.close()

    def load_collected_training_count(self):
        """Return the number of feedback images collected for retraining."""
        if not os.path.exists(TRAINING_COLLECTION_FILE):
            return 0
        with open(TRAINING_COLLECTION_FILE, "r", encoding="utf-8") as f:
            collected = json.load(f)
        return len(collected)

    def load_bot_state(self):
        """Load persistent restricted roles and paused channel overwrites."""
        default_state = {
            "restricted_roles": {},
            "paused_channels": {},
            "reserves": {},
            "active_incenses": {},
            "shiny_hunts": {},
            "collections": {},
            "categories": {},
            "afk": {},
        }
        if not os.path.exists(BOT_STATE_FILE):
            return default_state
        try:
            with open(BOT_STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            if not isinstance(state, dict):
                raise ValueError("bot state must be a JSON object")
        except (json.JSONDecodeError, OSError, ValueError) as error:
            backup_path = f"{BOT_STATE_FILE}.corrupt"
            try:
                with open(BOT_STATE_FILE, "rb") as source, open(
                    backup_path,
                    "wb",
                ) as backup:
                    backup.write(source.read())
            except OSError as backup_error:
                print(f"Could not back up corrupt bot state: {backup_error}")
            print(
                f"Recovered corrupt bot state file ({error}); "
                f"backup: {backup_path}"
            )
            state = default_state
        state.setdefault("restricted_roles", {})
        state.setdefault("paused_channels", {})
        state.setdefault("reserves", {})
        state.setdefault("active_incenses", {})
        state.setdefault("shiny_hunts", {})
        state.setdefault("collections", {})
        state.setdefault("categories", {})
        state.setdefault("afk", {})
        return state

    def seed_restricted_roles(self):
        """Merge roles from RESTRICTED_ROLES ("guild_id:role_id,...") so they survive state loss."""
        changed = False
        for pair in os.getenv("RESTRICTED_ROLES", "").split(","):
            guild_id, _, role_id = pair.strip().partition(":")
            if not (guild_id.isdigit() and role_id.isdigit()):
                continue
            ids = self.restricted_role_ids(guild_id)
            if int(role_id) not in ids:
                ids.add(int(role_id))
                self.bot_state["restricted_roles"][guild_id] = sorted(
                    str(rid) for rid in ids
                )
                changed = True
        if changed:
            self.save_bot_state()

    def save_bot_state(self):
        """Persist state atomically so interruptions cannot leave empty JSON."""
        directory = os.path.dirname(BOT_STATE_FILE)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary_file = f"{BOT_STATE_FILE}.tmp"
        with open(temporary_file, "w", encoding="utf-8") as f:
            json.dump(self.bot_state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_file, BOT_STATE_FILE)

    def load_premium_servers(self):
        """Load persistent server tier assignments."""
        if not os.path.exists(self.premium_servers_file):
            return {}
        with open(self.premium_servers_file, "r", encoding="utf-8") as f:
            assignments = json.load(f)
        invalid = {
            guild_id: tier
            for guild_id, tier in assignments.items()
            if tier not in PREMIUM_CAPACITIES
        }
        if invalid:
            raise ValueError(
                f"Invalid premium tiers in {self.premium_servers_file}: {invalid}"
            )
        return assignments

    def save_premium_servers(self):
        """Atomically persist premium assignments."""
        directory = os.path.dirname(self.premium_servers_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary_file = f"{self.premium_servers_file}.tmp"
        with open(temporary_file, "w", encoding="utf-8") as f:
            json.dump(
                self.premium_servers,
                f,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        os.replace(temporary_file, self.premium_servers_file)

    def premium_tier(self, guild_id: int) -> str | None:
        """Return a server's configured premium tier."""
        return self.premium_servers.get(str(guild_id))

    def premium_capacity(self, guild_id: int) -> int | None:
        """Return a server's simultaneous incense naming capacity."""
        tier = self.premium_tier(guild_id)
        return PREMIUM_CAPACITIES[tier] if tier else None

    def channel_within_incense_capacity(self, message) -> bool:
        """Check whether a spawn channel is within its server's tier capacity."""
        guild = message.guild
        if guild is None:
            return True
        capacity = self.premium_capacity(guild.id)
        if capacity is None:
            return True

        now = time()
        active_channel_ids = sorted(
            channel_id
            for channel_id, expires_at in self.active_incenses.items()
            if expires_at > now
            and self.bot.get_channel(channel_id)
            and self.bot.get_channel(channel_id).guild
            and self.bot.get_channel(channel_id).guild.id == guild.id
        )
        if message.channel.id not in active_channel_ids:
            return True
        return active_channel_ids.index(message.channel.id) < capacity

    @staticmethod
    def is_administrator(ctx) -> bool:
        return bool(
            ctx.guild
            and (
                ctx.author.id == ctx.guild.owner_id
                or ctx.author.guild_permissions.administrator
                or ctx.author.guild_permissions.manage_guild
            )
        )

    def has_restricted_permission(self, ctx) -> bool:
        """Check whether a member can use commands marked restricted."""
        if self.is_administrator(ctx):
            return True
        role_ids = self.restricted_role_ids(ctx.guild.id)
        return any(role.id in role_ids for role in ctx.author.roles)

    def restricted_role_ids(self, guild_id) -> set[int]:
        """Return all role IDs allowed to use restricted commands."""
        value = self.bot_state["restricted_roles"].get(str(guild_id))
        if not value:
            return set()
        values = value if isinstance(value, list) else [value]
        return {int(role_id) for role_id in values}

    def has_restricted_interaction_permission(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        """Check restricted access for a button interaction."""
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return False
        if (
            member.id == guild.owner_id
            or member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
        ):
            return True
        role_ids = self.restricted_role_ids(guild.id)
        return any(role.id in role_ids for role in member.roles)

    def pokemon_names_from_grab_segment(
        self,
        text: str,
    ) -> list[tuple[str, bool, str]]:
        """Resolve Pokémon while retaining all-form intent and source emojis."""
        chunks = re.split(r"\s*(?:\||—|–|\n|;|/|,|\s-\s)\s*", text)
        pokemon_names = []
        for chunk in chunks:
            custom_emojis = re.findall(r"<a?:[^:>]+:\d+>", chunk)
            cleaned = re.sub(r"<a?:[^:>]+:\d+>", "", chunk)
            value = re.sub(
                r"^[\s:*\-–—]+|[\s*_.,!]+$",
                "",
                cleaned,
            ).strip()
            if not value:
                continue
            requested_all_forms = value.casefold().startswith("all ")
            if requested_all_forms:
                value = value[4:].strip()
            pokemon_name = self.resolve_pokemon_name(value)
            if pokemon_name:
                pokemon_names.append(
                    (
                        str(pokemon_name),
                        requested_all_forms,
                        "".join(custom_emojis),
                    )
                )
                continue
            normalized = normalize_pokemon_alias(value)
            contained_matches = [
                (len(alias), class_name)
                for alias, class_name in self.pokemon_aliases.items()
                if alias and alias in normalized
            ]
            if contained_matches:
                pokemon_names.append(
                    (
                        str(max(contained_matches, key=lambda item: item[0])[1]),
                        requested_all_forms,
                        "".join(custom_emojis),
                    )
                )
        return list(dict.fromkeys(pokemon_names))

    def parse_grab_list(
        self,
        message,
        guild_id: int | None = None,
    ) -> list[tuple[str, str, bool, bool, str]]:
        """Parse Pokémon and category labels associated with each user mention."""
        if guild_id is None and message.guild is not None:
            guild_id = message.guild.id
        text_sources = [message]
        text_sources.extend(getattr(message, "message_snapshots", []) or [])
        text = ""
        for source in text_sources:
            text += "\n" + (source.content or "")
            for embed in source.embeds:
                text += "\n" + (embed.title or "")
                text += "\n" + (embed.description or "")
                for field in embed.fields:
                    text += f"\n{field.name}\n{field.value}"
        entries: list[tuple[str, str, bool, bool]] = []
        for line in text.splitlines():
            mentions = list(re.finditer(r"<@!?(\d+)>", line))
            for index, mention in enumerate(mentions):
                category_key = None
                category_emoji = ""
                if guild_id is not None:
                    prefix_segments = re.split(
                        r"\s*(?:\||—|–|;|/|,|\s-\s)\s*",
                        line[: mention.start()],
                    )
                    prefix_segments = [
                        cleaned
                        for segment in prefix_segments
                        if (
                            cleaned := re.sub(
                            r"^[\s:*\-–—]+|[\s*_.,!]+$",
                            "",
                            segment,
                            ).strip()
                        )
                    ]
                    if prefix_segments:
                        category_emoji = "".join(
                            re.findall(
                                r"<a?:[^:>]+:\d+>",
                                prefix_segments[-1],
                            )
                        )
                        category_text = re.sub(
                            r"<a?:[^:>]+:\d+>",
                            "",
                            prefix_segments[-1],
                        ).strip()
                        category_key = self.find_category(
                            guild_id,
                            category_text,
                        )
                if category_key is not None:
                    entry = (
                        mention.group(1),
                        category_key,
                        False,
                        True,
                        category_emoji,
                    )
                    if entry not in entries:
                        entries.append(entry)
                end = (
                    mentions[index + 1].start()
                    if index + 1 < len(mentions)
                    else len(line)
                )
                pokemon_names = self.pokemon_names_from_grab_segment(
                    line[mention.end() : end]
                )
                for pokemon_name, requested_all_forms, custom_emoji in pokemon_names:
                    entry = (
                        mention.group(1),
                        str(pokemon_name),
                        requested_all_forms,
                        False,
                        custom_emoji,
                    )
                    if entry not in entries:
                        entries.append(entry)
        return entries

    async def referenced_grab_message(self, ctx):
        """Return the list message referenced by a grab command."""
        reference = ctx.message.reference
        if reference is None:
            return None
        if reference.resolved is not None:
            return reference.resolved
        try:
            return await ctx.channel.fetch_message(reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def grab_reserves(self, ctx, h_mode: bool = False):
        """Show a parsed reserve list and batch reservation controls."""
        if ctx.guild is None:
            await ctx.send("This command can only be used inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to grab reserves.")
            return
        source = await self.referenced_grab_message(ctx)
        if source is None:
            await ctx.send(
                "❌ Reply to the reserve list message when using "
                f"`{'h!grab' if h_mode else 'v!grab'}`."
            )
            return
        entries = self.parse_grab_list(source, ctx.guild.id)
        if not entries:
            await ctx.send(
                "❌ This list doesn't work. I couldn't find any "
                "`<@user> Pokémon` pairs."
            )
            return
        view = GrabReservesView(
            self,
            ctx.author.id,
            ctx.channel.id,
            entries,
            h_mode=h_mode,
        )
        await ctx.send(embed=view.build_embed(), view=view)

    async def add_reserve_direct(
        self,
        guild: discord.Guild,
        pokemon_name: str,
        user_id: str,
    ) -> bool:
        """Add one reserve from a parsed grab entry."""
        resolved_name = self.resolve_pokemon_name(pokemon_name)
        if resolved_name is None:
            return False
        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return False
        self.add_reserve_owner(guild.id, str(resolved_name), member.id)
        self.save_bot_state()
        return True

    def save_training_image(self, pokemon_name: str, image_data: bytes):
        """Save a reviewed image and track it for a later training export."""
        started = perf_counter()
        requested_name = normalize_pokemon_name(pokemon_name)
        pokemon_name = self.class_names.setdefault(
            requested_name.casefold(),
            requested_name,
        )
        pokemon_directory = os.path.join(TRAINING_ROOT, pokemon_name)
        os.makedirs(pokemon_directory, exist_ok=True)

        digest = sha256(image_data).hexdigest()
        try:
            with Image.open(BytesIO(image_data)) as image:
                image_format = (image.format or "JPEG").casefold()
                extension = {
                    "jpeg": ".jpg",
                    "jpg": ".jpg",
                    "png": ".png",
                    "webp": ".webp",
                }.get(image_format, ".jpg")
        except (UnidentifiedImageError, OSError):
            extension = ".jpg"

        saved_path = os.path.join(pokemon_directory, f"feedback-{digest}{extension}")
        if not os.path.exists(saved_path):
            with open(saved_path, "wb") as image_file:
                image_file.write(image_data)

            os.makedirs(os.path.dirname(TRAINING_COLLECTION_FILE), exist_ok=True)
            collected = []
            if os.path.exists(TRAINING_COLLECTION_FILE):
                with open(TRAINING_COLLECTION_FILE, "r", encoding="utf-8") as f:
                    collected = json.load(f)
            if saved_path not in collected:
                collected.append(saved_path)
                with open(
                    TRAINING_COLLECTION_FILE,
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(collected, f, indent=2, ensure_ascii=False)
                self.reviewed_spawn_count += 1

        self.store_times.append(perf_counter() - started)
        return pokemon_name, saved_path

    def track_incense(self, message):
        """Track incense activation, updates, and completion in a channel."""
        channel_id = int(message.channel.id)
        now = time()
        text_parts = [message.content or ""]
        for embed in message.embeds:
            text_parts.extend(
                filter(
                    None,
                    [
                        embed.title,
                        embed.description,
                        embed.footer.text if embed.footer else None,
                    ],
                )
            )
        text = " ".join(text_parts).lower()

        if "incense" in text:
            end_phrases = (
                r"\b0\s+(?:spawn|pokemon|pokémon)s?\s+remaining\b",
                r"\bincense\s+(?:has\s+|is\s+)?(?:end|ended|finish|finished|expired|stopped|inactive)",
                r"\bno\s+longer\s+(?:spawn|spawning|active)\b",
                r"\bincense\s+(?:no\s+longer\s+active|ran\s+out|ran\s+off)\b",
                r"\bremaining\s+incense\s+:\s*0\b",
            )
            if any(re.search(pattern, text) for pattern in end_phrases):
                removed = self.active_incenses.pop(channel_id, None)
                if removed is not None or str(channel_id) in self.bot_state["active_incenses"]:
                    self.bot_state["active_incenses"].pop(str(channel_id), None)
                    self.save_bot_state()
                return
            self.active_incenses[channel_id] = now + INCENSE_INACTIVITY_SECONDS
            self.bot_state["active_incenses"][str(channel_id)] = (
                self.active_incenses[channel_id]
            )
            self.save_bot_state()

        if self.is_spawn_message(message):
            recent = self.recent_spawn_times.setdefault(
                channel_id,
                deque(maxlen=20),
            )
            recent.append(now)
            recent_count = sum(now - spawned < 90 for spawned in recent)
            if channel_id in self.active_incenses or recent_count >= 3:
                self.active_incenses[channel_id] = (
                    now + INCENSE_INACTIVITY_SECONDS
                )
                self.bot_state["active_incenses"][str(channel_id)] = (
                    self.active_incenses[channel_id]
                )
                self.save_bot_state()

    def active_incense_count(self, guild_id: int | None = None) -> int:
        """Count unexpired incense channels, optionally within one guild."""
        now = time()
        changed = False
        for channel_id, expires_at in list(self.active_incenses.items()):
            if expires_at <= now:
                self.active_incenses.pop(channel_id, None)
                self.bot_state["active_incenses"].pop(str(channel_id), None)
                changed = True
        if changed:
            self.save_bot_state()
        if guild_id is None:
            return sum(
                self.bot.get_channel(channel_id) is not None
                for channel_id in self.active_incenses
            )
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return 0
        channel_ids = {channel.id for channel in guild.channels}
        return sum(channel_id in channel_ids for channel_id in self.active_incenses)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for Pokétwo spawn messages"""
        # Ignore bot's own messages
        if message.author.id == self.bot.user.id:
            return
        if re.fullmatch(r"[hH]!grab\s*", message.content):
            ctx = await self.bot.get_context(message)
            await self.grab_reserves(ctx, h_mode=True)
            return
        # Check if message is from Pokétwo bot
        if message.author.id == POKETWO_BOT_ID:
            self.track_incense(message)
            if message.guild and self.premium_tier(message.guild.id) is None:
                return
            if self.is_spawn_message(message) and self.channel_within_incense_capacity(
                message
            ):
                await self.handle_poketwo_spawn(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Update incense state when Pokétwo edits a status/countdown embed."""
        del before
        if after.author.id == self.bot.user.id:
            return
        if after.author.id == POKETWO_BOT_ID:
            self.track_incense(after)

    @staticmethod
    def is_spawn_message(message) -> bool:
        """Return whether a Pokétwo message is an image-guessing spawn."""
        text_parts = [message.content or ""]
        for embed in message.embeds:
            text_parts.extend(
                filter(
                    None,
                    [
                        embed.title,
                        embed.description,
                        embed.footer.text if embed.footer else None,
                    ],
                )
            )
        text = " ".join(text_parts).casefold()
        return "guess the" in text and "pok" in text

    async def handle_poketwo_spawn(self, message):
        """Identify a Pokétwo spawn and report the predicted Pokémon."""
        started = perf_counter()
        image_data, download_seconds = await self._get_spawn_image(message)
        if image_data is None:
            return

        try:
            pokemon_name, confidence, inference_seconds = await asyncio.to_thread(
                self.recognize_spawn_image,
                image_data,
            )
        except (UnidentifiedImageError, OSError) as error:
            print(f"Could not read Pokétwo spawn image: {error}")
            return

        missingno_pause = False
        if pokemon_name.casefold() == "missingno":
            missingno_pause = await self.pause_missingno_channel(message.channel)

        shiny_hunters = (
            self.shiny_hunters_for_spawn(message.guild.id, pokemon_name)
            if message.guild
            else []
        )
        if (
            message.channel.id == TRAINING_REVIEW_CHANNEL_ID
            and confidence < REVIEW_CONFIDENCE_THRESHOLD
        ):
            embed = discord.Embed(
                title="Is this Pokémon correct?",
                color=discord.Color.blurple(),
            )
            type_icons = "".join(
                TYPE_EMOJIS[pokemon_type]
                for pokemon_type in self.pokemon_types[pokemon_name]
            )
            embed.add_field(
                name="Guess",
                value=f"{type_icons} {pokemon_name}",
                inline=True,
            )
            embed.add_field(
                name="Confidence",
                value=f"{confidence:.2f}%",
                inline=True,
            )
            reserved_user_ids = (
                self.reserve_user_ids(message.guild.id, pokemon_name)
                if message.guild
                else []
            )
            if reserved_user_ids:
                embed.add_field(
                    name="Reserved",
                    value=" ".join(
                        f"<@{user_id}>" for user_id in reserved_user_ids
                    ),
                    inline=True,
                )
            elif shiny_hunters:
                embed.add_field(
                    name="Shiny hunt",
                    value=" ".join(f"<@{user_id}>" for user_id in shiny_hunters),
                    inline=True,
                )
            if not reserved_user_ids:
                collection_owners = self.collection_owners_for_spawn(
                    message.guild.id,
                    pokemon_name,
                )
                if collection_owners:
                    embed.add_field(
                        name="Collection",
                        value=" ".join(
                            f"<@{user_id}>" for user_id in collection_owners
                        ),
                        inline=True,
                    )
            embed.set_image(url="attachment://spawn-review.webp")
            with Image.open(BytesIO(image_data)) as image:
                review_buffer = BytesIO()
                image.convert("RGB").save(
                    review_buffer,
                    format="WEBP",
                    quality=85,
                )
            review_buffer.seek(0)
            await message.channel.send(
                embed=embed,
                file=discord.File(review_buffer, filename="spawn-review.webp"),
                view=SpawnReviewView(self, pokemon_name, image_data),
            )
        else:
            content, embed = self.format_spawn_prediction(
                pokemon_name,
                confidence,
                message.guild.id if message.guild else None,
                shiny_hunters,
            )
            custom_sprite_path = os.path.join(
                "pokemon_sprites",
                f"{pokemon_name}.png",
            )
            if os.path.isfile(custom_sprite_path):
                embed.set_thumbnail(url="attachment://pokemon.png")
                await message.channel.send(
                    content=content,
                    embed=embed,
                    file=discord.File(custom_sprite_path, filename="pokemon.png"),
                )
            elif pokemon_name in CUSTOM_SPRITE_IDENTIFIERS:
                thumbnail_buffer = BytesIO()
                with Image.open(BytesIO(image_data)) as image:
                    image.convert("RGB").save(
                        thumbnail_buffer,
                        format="WEBP",
                        quality=85,
                    )
                thumbnail_buffer.seek(0)
                embed.set_thumbnail(url="attachment://pokemon.webp")
                await message.channel.send(
                    content=content,
                    embed=embed,
                    file=discord.File(
                        thumbnail_buffer,
                        filename="pokemon.webp",
                    ),
                )
            else:
                sprite_id = self.pokemon_sprite_ids.get(pokemon_name)
                if sprite_id is not None:
                    embed.set_thumbnail(
                        url=(
                            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                            "sprites/pokemon/other/official-artwork/"
                            f"{sprite_id}.png"
                        )
                    )
                await message.channel.send(
                    content=content,
                    embed=embed,
                )

        if pokemon_name.casefold() == "missingno":
            staff_mention = f"<@&{MISSINGNO_ALERT_ROLE_ID}>"
            pause_note = (
                " The channel is paused for Pokétwo."
                if missingno_pause
                else " I could not pause Pokétwo automatically."
            )
            await message.channel.send(
                f"⚠️ Don't catch this Pokémon! Ping a staff member: {staff_mention}."
                f"{pause_note} Use `v!resume` to resume."
            )
        total_seconds = perf_counter() - started
        self.spawn_response_times.append(total_seconds)
        self.inference_times.append(inference_seconds)
        self.last_spawn_metrics = {
            "download": download_seconds,
            "inference": inference_seconds,
            "total": total_seconds,
        }
        self.recognized_spawn_count += 1

    def recognize_spawn_image(self, image_data: bytes):
        """Recognize an image without blocking the Discord event loop."""
        with Image.open(BytesIO(image_data)) as image:
            return self.recognizer.recognize(image)

    async def _get_spawn_image(self, message):
        """Return the spawn image bytes and download duration."""
        started = perf_counter()
        for attachment in message.attachments:
            if (attachment.content_type or "").startswith("image/"):
                return await attachment.read(), perf_counter() - started

        image_url = None
        for embed in message.embeds:
            if embed.image and embed.image.url:
                image_url = embed.image.url
                break
            if embed.thumbnail and embed.thumbnail.url:
                image_url = embed.thumbnail.url
                break

        if image_url is None:
            return None, perf_counter() - started

        if self.http_session is None:
            raise RuntimeError("Pokétwo image HTTP session is not initialized")

        try:
            async with self.http_session.get(image_url) as response:
                response.raise_for_status()
                return await response.read(), perf_counter() - started
        except (aiohttp.ClientError, TimeoutError) as error:
            print(f"Could not download Pokétwo spawn image: {error}")
            return None, perf_counter() - started

    async def pause_missingno_channel(self, channel):
        """Deny only Pokétwo permission to send in a MissingNo channel."""
        if not channel.guild or not channel.permissions_for(channel.guild.me).manage_channels:
            return False
        poketwo = channel.guild.get_member(POKETWO_BOT_ID)
        if poketwo is None:
            try:
                poketwo = await channel.guild.fetch_member(POKETWO_BOT_ID)
            except discord.NotFound:
                return False
        channel_key = str(channel.id)
        if channel_key not in self.bot_state["paused_channels"]:
            previous = channel.overwrites_for(poketwo)
            allow, deny = previous.pair()
            self.bot_state["paused_channels"][channel_key] = {
                "guild_id": str(channel.guild.id),
                "existed": poketwo in channel.overwrites,
                "allow": allow.value,
                "deny": deny.value,
            }
            self.save_bot_state()

        overwrite = channel.overwrites_for(poketwo)
        overwrite.send_messages = False
        await channel.set_permissions(
            poketwo,
            overwrite=overwrite,
            reason="MissingNo spawned; waiting for staff to resume",
        )
        return True

    @commands.command(name="settings")
    async def settings(self, ctx):
        """Show the server settings menu."""
        await ctx.send(view=ServerSettingsView(ctx.author.id))

    def guild_categories(self, guild_id) -> dict:
        """Get categories for a guild."""
        return self.bot_state["categories"].setdefault(str(guild_id), {})

    def find_category(self, guild_id, name: str) -> str | None:
        """Find a category by name (case-insensitive)."""
        for key in self.guild_categories(guild_id):
            if key.casefold() == name.casefold():
                return key
        return None

    @commands.command(name="addcategory", aliases=["ac"])
    async def add_category(self, ctx, *, name: str = ""):
        """Create an empty Pokémon category."""
        if ctx.guild is None:
            await ctx.send("Categories can only be managed inside a server.")
            return
        name = name.strip()
        if not name:
            await ctx.send("Usage: `v!ac <name>`")
            return
        if self.find_category(ctx.guild.id, name):
            await ctx.send(f"❌ Category **{name}** already exists.")
            return
        self.guild_categories(ctx.guild.id)[name] = []
        self.save_bot_state()
        await ctx.send(f"✅ Created category **{name}**.")

    @commands.command(name="createcategory", aliases=["cc"])
    async def fill_category(self, ctx, category: str = "", *, pokemon_input: str = ""):
        """Add Pokémon to an existing category."""
        if ctx.guild is None:
            await ctx.send("Categories can only be managed inside a server.")
            return
        if not category or not pokemon_input.strip():
            await ctx.send("Usage: `v!cc <category> <pokemon>, <pokemon>`")
            return
        key = self.find_category(ctx.guild.id, category)
        if key is None:
            await ctx.send(
                f"❌ Category **{category}** doesn't exist. Create it with "
                f"`v!ac {category}` first."
            )
            return
        pokemon_names, unknown = self.resolve_pokemon_list(pokemon_input)
        if unknown:
            await ctx.send(
                "❌ Unknown Pokémon: " + ", ".join(f"`{n}`" for n in unknown)
            )
            return
        members = self.guild_categories(ctx.guild.id)[key]
        added = [str(n) for n in pokemon_names if str(n) not in members]
        members.extend(added)
        self.save_bot_state()
        if added:
            await ctx.send(f"✅ Added to **{key}**: {', '.join(added)}.")
        else:
            await ctx.send(f"Those Pokémon are already in **{key}**.")

    @commands.command(name="categorylist", aliases=["cal"])
    async def category_list(self, ctx):
        """Show every category and its Pokémon."""
        if ctx.guild is None:
            await ctx.send("Categories can only be managed inside a server.")
            return
        categories = self.guild_categories(ctx.guild.id)
        if not categories:
            await ctx.send("No categories yet. Create one with `v!ac <name>`.")
            return
        embed = discord.Embed(title="Categories")
        for name, members in categories.items():
            embed.add_field(name=name, value=f"{len(members)} Pokémon", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check if the bot is responsive"""
        await ctx.send(f"Pong! {self.bot.latency * 1000:.2f}ms")

    @commands.command(name="tz")
    async def timezone_command(self, ctx, *, phase: str = ""):
        """Find one place currently experiencing the requested local-time phase."""
        phase = phase.strip().casefold()
        if phase not in TIMEZONE_PHASE_EMOJIS:
            await ctx.send("Use `v!tz day`, `v!tz night`, `v!tz dawn`, or `v!tz dusk`.")
            return

        place = find_place_for_phase(phase)
        if place is None:
            await ctx.send(f"I couldn't find a place currently experiencing {phase}.")
            return

        await ctx.send(
            f"This {place} is {phase}.\n"
            f"Copy and paste: `<@{POKETWO_BOT_ID}> tz {place}` "
            f"{TIMEZONE_PHASE_EMOJIS[phase]}"
        )

    @commands.group(name="premium", invoke_without_command=True)
    async def premium(self, ctx):
        """Display this server's premium tier."""
        if ctx.invoked_subcommand is not None:
            return
        tier = (
            self.premium_tier(ctx.guild.id)
            if ctx.guild
            else None
        )
        tier_icons = {"bronze": "🥉", "silver": "🥈", "gold": "🥇"}
        tier_colors = {
            "bronze": 0xCD7F32,
            "silver": 0xC0C0C0,
            "gold": 0xFFD700,
        }
        if tier:
            embed = discord.Embed(
                title=f"{tier_icons[tier]} {tier.title()} Premium",
                description=(
                    f"This server has **{tier.title()}** access and can name "
                    f"**{PREMIUM_CAPACITIES[tier]} simultaneous incense channels**."
                ),
                color=tier_colors[tier],
            )
        else:
            embed = discord.Embed(
                title="Standard Tier",
                description="This server does not currently have a premium tier.",
                color=discord.Color.dark_gray(),
            )
        await ctx.send(embed=embed)

    @premium.command(name="add")
    async def add_premium(self, ctx, tier: str, server_id: int):
        """Grant a premium tier to a server from the main server."""
        if ctx.guild is None or ctx.guild.id != PREMIUM_MAIN_GUILD_ID:
            await ctx.send(
                f"❌ Premium grants can only be issued in the main server "
                f"(`{PREMIUM_MAIN_GUILD_ID}`)."
            )
            return
        if not await self.bot.is_owner(ctx.author):
            await ctx.send("❌ Only the bot owner can grant premium access.")
            return

        normalized_tier = tier.casefold()
        if normalized_tier not in PREMIUM_CAPACITIES:
            await ctx.send("❌ Tier must be `bronze`, `silver`, or `gold`.")
            return
        if server_id <= 0:
            await ctx.send("❌ Enter a valid server ID.")
            return

        self.premium_servers[str(server_id)] = normalized_tier
        self.save_premium_servers()
        await ctx.send(
            f"✅ Server `{server_id}` is now on **{normalized_tier.title()}** "
            f"({PREMIUM_CAPACITIES[normalized_tier]} simultaneous incense channels)."
        )

    @commands.command(name="premiumservers", aliases=["ps"])
    async def premium_servers_list(self, ctx):
        """List connected servers and their premium tier."""
        guilds = sorted(self.bot.guilds, key=lambda guild: guild.name.casefold())
        if not guilds:
            await ctx.send("This bot is not connected to any servers.")
            return

        lines = []
        for guild in guilds:
            name = discord.utils.escape_mentions(
                discord.utils.escape_markdown(guild.name)
            )
            tier = self.premium_tier(guild.id)
            tier_label = f"**{tier.title()}**" if tier else "**No premium**"
            lines.append(f"**{name}** (`{guild.id}`) — {tier_label}")

        page_size = 20
        page_count = (len(lines) + page_size - 1) // page_size
        for page_index in range(page_count):
            page_lines = lines[page_index * page_size : (page_index + 1) * page_size]
            embed = discord.Embed(
                title="Premium Servers",
                description="\n".join(page_lines),
                color=discord.Color.purple(),
            )
            if page_count > 1:
                embed.set_footer(text=f"Page {page_index + 1}/{page_count}")
            await ctx.send(embed=embed)

    @commands.command(name="permission")
    async def set_restricted_role(self, ctx, role_id: int):
        """Set the role allowed to use restricted commands."""
        if not self.is_administrator(ctx):
            await ctx.send("❌ Only a server administrator can set this role.")
            return
        role = ctx.guild.get_role(role_id)
        if role is None:
            await ctx.send("❌ That role is not in this server.")
            return
        role_ids = self.restricted_role_ids(ctx.guild.id)
        role_ids.add(role.id)
        self.bot_state["restricted_roles"][str(ctx.guild.id)] = sorted(
            str(rid) for rid in role_ids
        )
        self.save_bot_state()
        mentions = " ".join(f"<@&{rid}>" for rid in sorted(role_ids))
        await ctx.send(
            f"✅ Restricted commands are available to: {mentions}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="afk")
    async def afk(self, ctx):
        """Toggle shiny hunt and collection pings with buttons."""
        view = AfkView(self, ctx.author.id)
        view.message = await ctx.send(embed=view.build_embed(), view=view)

    @commands.group(name="sh", invoke_without_command=True)
    async def shiny_hunt(self, ctx, *, pokemon_name: str = ""):
        """Start or change the caller's shiny hunt."""
        if ctx.invoked_subcommand is not None:
            return
        if ctx.guild is None:
            await ctx.send("Shiny hunts can only be managed inside a server.")
            return
        pokemon_name = pokemon_name.strip()
        if not pokemon_name:
            hunt = self.bot_state["shiny_hunts"].get(
                str(ctx.guild.id),
                {},
            ).get(str(ctx.author.id))
            if hunt:
                label = shiny_hunt_label(
                    hunt.get("pokemon"), hunt.get("all_forms", False)
                )
                await ctx.send(
                    f"✨ Added to your shinyhunt: **{label}**."
                )
            else:
                await ctx.send("You are not currently shiny hunting a Pokémon.")
            return
        all_forms = pokemon_name.casefold().startswith("all ")
        pokemon_input = pokemon_name[4:].strip() if all_forms else pokemon_name
        resolved_name = self.resolve_pokemon_name(pokemon_input)
        if resolved_name is None:
            await ctx.send(f"❌ Unknown Pokémon: `{pokemon_input}`")
            return

        new_label = shiny_hunt_label(resolved_name, all_forms)
        hunt = self.bot_state["shiny_hunts"].get(
            str(ctx.guild.id),
            {},
        ).get(str(ctx.author.id))
        if (
            hunt
            and hunt.get("pokemon") == resolved_name
            and hunt.get("all_forms", False) == all_forms
        ):
            await ctx.send(
                f"Already in your shinyhunt: **{new_label}**."
            )
            return
        if hunt:
            old_pokemon = shiny_hunt_label(
                hunt.get("pokemon"), hunt.get("all_forms", False)
            )
            await ctx.send(
                (
                    f"You are currently shiny hunting **{old_pokemon}**.\n"
                    f"Switch to **{new_label}**?"
                ),
                view=ShinyHuntSwitchView(
                    self,
                    ctx.guild.id,
                    ctx.author.id,
                    old_pokemon,
                    str(resolved_name),
                    all_forms,
                ),
            )
            return

        self.set_shiny_hunt(
            ctx.guild.id,
            ctx.author.id,
            str(resolved_name),
            all_forms,
        )
        await ctx.send(
            f"✨ Added to your shinyhunt: **{new_label}**."
        )

    @cast(commands.Group, shiny_hunt).command(name="clear")
    async def clear_shiny_hunt(self, ctx):
        """Clear the caller's current shiny hunt."""
        if ctx.guild is None:
            await ctx.send("Shiny hunts can only be managed inside a server.")
            return
        guild_hunts = self.bot_state["shiny_hunts"].get(
            str(ctx.guild.id),
            {},
        )
        hunt = guild_hunts.pop(str(ctx.author.id), None)
        if hunt is None:
            await ctx.send("You are not currently shiny hunting a Pokémon.")
            return
        self.save_bot_state()
        label = shiny_hunt_label(
            hunt.get("pokemon"), hunt.get("all_forms", False)
        )
        await ctx.send(
            f"✅ Cleared your **{label}** shiny hunt."
        )

    @commands.command(name="resume")
    async def resume_poketwo_channel(self, ctx):
        """Restore Pokétwo's previous permissions after a MissingNo spawn."""
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to resume this channel.")
            return
        saved = self.bot_state["paused_channels"].get(str(ctx.channel.id))
        if saved is None:
            await ctx.send("This channel is not paused for MissingNo.")
            return
        if not ctx.channel.permissions_for(ctx.guild.me).manage_channels:
            await ctx.send("❌ I need **Manage Channels** permission to resume it.")
            return
        poketwo = ctx.guild.get_member(POKETWO_BOT_ID)
        if poketwo is None:
            try:
                poketwo = await ctx.guild.fetch_member(POKETWO_BOT_ID)
            except discord.NotFound:
                await ctx.send("❌ Pokétwo is no longer in this server.")
                return

        if saved["existed"]:
            previous = discord.PermissionOverwrite.from_pair(
                discord.Permissions(int(saved["allow"])),
                discord.Permissions(int(saved["deny"])),
            )
            await ctx.channel.set_permissions(
                poketwo,
                overwrite=previous,
                reason="Staff resumed Pokétwo after MissingNo",
            )
        else:
            await ctx.channel.set_permissions(
                poketwo,
                overwrite=None,
                reason="Staff resumed Pokétwo after MissingNo",
            )
        del self.bot_state["paused_channels"][str(ctx.channel.id)]
        self.save_bot_state()
        await ctx.send("✅ Channel resumed. Pokétwo can send messages again.")

    @commands.command(name="r")
    async def reservations(self, ctx, *, entry: str = ""):
        """Dispatch reservation actions without Discord group parsing."""
        await self.dispatch_reservations(ctx, entry)

    @commands.command(name="reserve")
    async def reserve_command(self, ctx, *, entry: str = ""):
        """Long-form reservation command dispatcher."""
        await self.dispatch_reservations(ctx, entry)

    async def dispatch_reservations(self, ctx, entry: str = ""):
        """Dispatch reserve/reservation actions from either command alias."""
        raw_entry = re.sub(
            r"^\s*[vV]!(?:r|reserve)\b",
            "",
            ctx.message.content,
            count=1,
        ).strip()
        action_entry = raw_entry or entry.strip()
        parts = action_entry.split(maxsplit=1)
        action = parts[0].casefold() if parts else ""
        remainder = parts[1].strip() if len(parts) > 1 else ""

        if action == "add":
            await self.add_reserve(ctx, entry=remainder)
        elif action == "remove":
            await self.remove_reserve(ctx, entry=remainder)
        elif action in ("e", "exchange"):
            await self.exchange_reserves(ctx, remainder)
        elif action == "list":
            await self.show_reserve_list(ctx, remainder)
        elif action == "search":
            await self.search_reserve(ctx, remainder)
        elif action == "clear":
            if remainder:
                await ctx.send("Usage: `v!r clear`")
                return
            await self.clear_reserves(ctx)
        elif not action_entry:
            await ctx.send(
                "Use `v!r list [@user]` / `v!reserve list [@user]`, "
                "`v!r add <pokemon,...> <@user>`, "
                "`v!r remove <pokemon,...|category> [@user]`, "
                "`v!r search <pokemon>`, or `v!r clear`."
            )
        else:
            await ctx.send(
                "Unknown reservation action. Use `add`, `remove`, `search`, "
                "`list`, or `clear`."
            )

    async def exchange_reserves(self, ctx, remainder: str):
        """Move reserves from the given user to those in a replied list."""
        if ctx.guild is None:
            await ctx.send("This command can only be used inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to exchange reserves.")
            return
        match = re.search(r"<@!?(\d+)>|\b(\d{15,20})\b", remainder)
        source = await self.referenced_grab_message(ctx)
        if match is None or source is None:
            await ctx.send(
                "Reply to a `user - pokemon` list with `v!r e <@user>` "
                "(the user the reserves currently belong to)."
            )
            return
        from_id = match.group(1) or match.group(2)
        parsed_entries = self.parse_grab_list(source, ctx.guild.id)
        entries = []
        for (
            user_id,
            pokemon_name,
            requested_all_forms,
            is_category,
            _custom_emoji,
        ) in parsed_entries:
            if is_category:
                entries.extend(
                    (user_id, str(category_member))
                    for category_member in self.guild_categories(ctx.guild.id).get(
                        pokemon_name,
                        [],
                    )
                )
            elif requested_all_forms:
                entries.extend(
                    (user_id, str(family_member))
                    for family_member in self.resolve_pokemon_family(
                        pokemon_name,
                        include_regionals=False,
                    )
                )
            else:
                entries.append((user_id, pokemon_name))
        if not entries:
            await ctx.send(
                "❌ This list doesn't work. I couldn't find any "
                "`<@user> Pokémon` pairs."
            )
            return
        view = ExchangeReservesView(
            self, ctx.guild.id, ctx.author.id, from_id, entries
        )
        await ctx.send(embed=view.build_embed(), view=view)

    async def add_reserve(self, ctx, *, entry: str):
        """Reserve a Pokémon for a member. Restricted command."""
        if ctx.guild is None:
            await ctx.send("Reservations can only be managed inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to add reserves.")
            return

        match = re.search(r"(?:<@!?)?(\d+)>?\s*$", entry)
        if match is None:
            await ctx.send("Usage: `v!r add <pokémon name> <@user>`")
            return
        pokemon_input = entry[: match.start()].strip()
        user_id = int(match.group(1))
        member = ctx.guild.get_member(user_id)
        if member is None:
            try:
                member = await ctx.guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden):
                member = None
        if member is None:
            await ctx.send("❌ That user is not in this server.")
            return
        
        pokemon_names = []
        unknown = []
        
        category_key = self.find_category(ctx.guild.id, pokemon_input)
        if category_key:
            pokemon_names = self.guild_categories(ctx.guild.id)[category_key]
        else:
            collection_dict = self.bot_state["collections"].get(str(ctx.guild.id), {})
            if pokemon_input.casefold() == "collection" and str(ctx.author.id) in collection_dict:
                pokemon_names = collection_dict[str(ctx.author.id)]
            else:
                pokemon_names, unknown = self.resolve_pokemon_list(pokemon_input)
        
        if unknown:
            await ctx.send(
                "❌ Unknown Pokémon: "
                + ", ".join(f"`{name}`" for name in unknown)
            )
            return

        for pokemon_name in pokemon_names:
            self.add_reserve_owner(ctx.guild.id, str(pokemon_name), member.id)
        self.save_bot_state()
        if len(pokemon_names) == 1:
            await ctx.send(
                f"✅ **{pokemon_names[0]}** added to {member.mention}'s reserves."
            )
        else:
            suffix = f" added to {member.mention}'s reserves."
            requested_names = [
                term.strip()
                for term in pokemon_input.split(",")
                if term.strip()
            ]
            batch = []
            batch_length = 0
            for name in requested_names:
                if batch and batch_length + len(name) + 2 > 1800:
                    await ctx.send(", ".join(batch))
                    batch = []
                    batch_length = 0
                batch.append(name)
                batch_length += len(name) + 2
            if batch:
                await ctx.send(
                    "✅ " + ", ".join(batch) + suffix
                )

    async def remove_reserve(self, ctx, *, entry: str):
        """Remove a server Pokémon reservation. Restricted command."""
        if ctx.guild is None:
            await ctx.send("Reservations can only be managed inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to remove reserves.")
            return

        match = re.search(r"\s+(?:<@!?)?(\d+)>?\s*$", entry)
        member = None
        if match is None:
            pokemon_input = entry.strip()
        else:
            pokemon_input = entry[: match.start()].strip()
            user_id = int(match.group(1))
            member = ctx.guild.get_member(user_id)
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden):
                    member = None
            if member is None:
                await ctx.send("❌ That user is not in this server.")
                return

        guild_id = ctx.guild.id
        category_key = self.find_category(guild_id, pokemon_input)
        if category_key is not None:
            pokemon_names = self.guild_categories(guild_id)[category_key]
            unknown = []
            if not pokemon_names:
                await ctx.send(f"❌ Category **{category_key}** is empty.")
                return
        else:
            pokemon_names, unknown = self.resolve_pokemon_list(pokemon_input)
        if unknown:
            await ctx.send(
                "❌ Unknown Pokémon: "
                + ", ".join(f"`{name}`" for name in unknown)
            )
            return

        removed = []
        skipped = []
        for pokemon_name in pokemon_names:
            reserved_user_ids = self.reserve_user_ids(guild_id, pokemon_name)
            if not reserved_user_ids:
                skipped.append(f"{pokemon_name} is not reserved")
                continue
            if member is not None and str(member.id) not in reserved_user_ids:
                skipped.append(f"{pokemon_name} belongs to another user")
                continue
            self.remove_reserve_owner(
                guild_id,
                pokemon_name,
                member.id if member is not None else None,
            )
            removed.append(pokemon_name)
        if not removed:
            await ctx.send("❌ " + "; ".join(skipped))
            return
        self.save_bot_state()
        result = f"✅ Removed **{len(removed)} reserve(s)**: {', '.join(removed)}."
        if skipped:
            result += " Skipped: " + "; ".join(skipped)
        await ctx.send(result)

    async def search_reserve(self, ctx, pokemon_input: str):
        """Show who has a Pokémon reserved, without requiring restricted access."""
        if ctx.guild is None:
            await ctx.send("Reservations can only be viewed inside a server.")
            return
        if not pokemon_input.strip():
            await ctx.send("Usage: `v!r search <pokemon>`")
            return
        pokemon_name = self.resolve_pokemon_name(pokemon_input)
        if pokemon_name is None:
            await ctx.send(f"❌ Unknown Pokémon: `{pokemon_input.strip()}`")
            return
        user_ids = self.reserve_user_ids(ctx.guild.id, pokemon_name)
        description = (
            "\n".join(f"• <@{user_id}>" for user_id in user_ids)
            if user_ids
            else "No members have reserved this Pokémon."
        )
        embed = discord.Embed(
            title=f"{pokemon_name} Reservations",
            description=description,
            color=discord.Color.purple(),
        )
        if user_ids:
            member_count = len(user_ids)
            member_label = "member" if member_count == 1 else "members"
            embed.set_footer(text=f"{member_count} reserving {member_label}")
        await ctx.send(embed=embed)

    async def show_reserve_list(self, ctx, member_input: str = ""):
        """Fresh server reserve list implementation."""
        if ctx.guild is None:
            await ctx.send("Reservations can only be viewed inside a server.")
            return

        member = None
        member_id = None
        member_text = member_input.strip()
        if member_text:
            mention_match = re.search(r"<@!?(\d+)>", member_text)
            if mention_match:
                member_id = int(mention_match.group(1))
            elif member_text.isdigit():
                member_id = int(member_text)
            elif ctx.message.mentions:
                member_id = ctx.message.mentions[0].id

            if member_id is not None:
                member = ctx.guild.get_member(member_id)
                if member is None:
                    try:
                        member = await ctx.guild.fetch_member(member_id)
                    except (
                        discord.NotFound,
                        discord.Forbidden,
                        discord.HTTPException,
                    ):
                        member = None
            if member is None:
                await ctx.send("❌ I couldn't find that server member.")
                return

        guild_reserves = self.bot_state["reserves"].get(
            str(ctx.guild.id),
            {},
        )
        filtered = sorted(
            (
                (pokemon_name, user_id)
                for pokemon_name in guild_reserves
                for user_id in self.reserve_user_ids(ctx.guild.id, pokemon_name)
                if member is None or user_id == str(member.id)
            ),
            key=lambda reserve: reserve[0].casefold(),
        )
        if not filtered:
            target = f" for {member.display_name}" if member else ""
            empty_embed = discord.Embed(
                title=(
                    f"{member.display_name}'s Pokémon Reserves"
                    if member
                    else f"{ctx.guild.name} Pokémon Reserves"
                ),
                description=f"No Pokémon are currently reserved{target}.",
                color=discord.Color.purple(),
            )
            await ctx.send(embed=empty_embed)
            return

        lines = [
            f"• **{pokemon_name}** — <@{user_id}>"
            for pokemon_name, user_id in filtered
        ]
        title = (
            f"{member.display_name}'s Pokémon Reserves"
            if member
            else f"{ctx.guild.name} Pokémon Reserves"
        )
        embeds = []
        chunk_size = 20
        for start in range(0, len(lines), chunk_size):
            description = "\n".join(lines[start : start + chunk_size])
            embeds.append(
                discord.Embed(
                    title=title,
                    description=description,
                    color=discord.Color.purple(),
                ).set_footer(
                    text=(
                        f"{start + 1}-{min(start + chunk_size, len(lines))} "
                        f"of {len(lines)} reserves"
                    )
                )
            )
        await ctx.send(
            embed=embeds[0],
            view=ReserveListView(ctx.author.id, embeds),
        )

    async def clear_reserves(self, ctx):
        """Clear every reservation in the current server after confirmation."""
        if ctx.guild is None:
            await ctx.send("Reservations can only be managed inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to clear reserves.")
            return
        count = len(
            self.bot_state["reserves"].get(str(ctx.guild.id), {})
        )
        if count == 0:
            await ctx.send("There are no reserves to clear.")
            return
        await ctx.send(
            (
                f"⚠️ Are you sure you want to clear all **{count}** "
                "Pokémon reserves in this server?"
            ),
            view=ClearReservesView(
                self,
                ctx.guild.id,
                ctx.author.id,
            ),
        )

    @commands.command(name="grab")
    async def grab_reserves_command(self, ctx):
        """Import reservations from the replied-to user/Pokémon list."""
        await self.grab_reserves(ctx, h_mode=False)

    @commands.group(name="cl", invoke_without_command=True)
    async def collection(self, ctx):
        """Show the caller's collection help."""
        if ctx.invoked_subcommand is not None:
            return
        await ctx.send(
            "Usage: `v!cl add <pokemon>`, `v!cl remove <pokemon>`, "
            "`v!cl list`, or `v!cl clear`."
        )

    @collection.command(name="add")
    async def add_collection(self, ctx, *, pokemon_input: str):
        """Add one Pokémon or an entire family to the caller's collection."""
        if ctx.guild is None:
            await ctx.send("Collections can only be managed inside a server.")
            return
        pokemon_names, unknown = self.resolve_pokemon_list(pokemon_input)
        if unknown:
            await ctx.send(
                "❌ Unknown Pokémon: "
                + ", ".join(f"`{name}`" for name in unknown)
            )
            return

        guild_collections = self.bot_state["collections"].setdefault(
            str(ctx.guild.id),
            {},
        )
        collection = guild_collections.setdefault(str(ctx.author.id), [])
        added = [
            str(pokemon_name)
            for pokemon_name in pokemon_names
            if str(pokemon_name) not in collection
        ]
        collection.extend(added)
        self.save_bot_state()
        await ctx.send(
            f"✅ Added to your collection: {', '.join(added)}."
        )

    @collection.command(name="remove")
    async def remove_collection(self, ctx, *, pokemon_input: str):
        """Remove one Pokémon from the caller's collection."""
        if ctx.guild is None:
            await ctx.send("Collections can only be managed inside a server.")
            return
        pokemon_names, unknown = self.resolve_pokemon_list(pokemon_input)
        if unknown:
            await ctx.send(
                "❌ Unknown Pokémon: "
                + ", ".join(f"`{name}`" for name in unknown)
            )
            return
        collection = self.bot_state["collections"].get(
            str(ctx.guild.id),
            {},
        ).get(str(ctx.author.id), [])
        removed = [name for name in pokemon_names if name in collection]
        skipped = [name for name in pokemon_names if name not in collection]
        if not removed:
            await ctx.send(
                "❌ None of those Pokémon are in your collection: "
                + ", ".join(skipped)
            )
            return
        for pokemon_name in removed:
            collection.remove(pokemon_name)
        self.save_bot_state()
        result = (
            f"✅ Removed **{len(removed)}** from your collection: "
            + ", ".join(removed)
        )
        if skipped:
            result += ". Skipped: " + ", ".join(skipped)
        await ctx.send(result)

    @collection.command(name="list")
    async def list_collection(self, ctx):
        """List the caller's collection."""
        if ctx.guild is None:
            await ctx.send("Collections can only be viewed inside a server.")
            return
        collection = sorted(
            self.bot_state["collections"].get(
                str(ctx.guild.id),
                {},
            ).get(str(ctx.author.id), []),
            key=str.casefold,
        )
        if not collection:
            await ctx.send("Your collection is empty.")
            return
        lines = [f"• {pokemon_name}" for pokemon_name in collection]
        embeds = []
        chunk_size = 20
        for start in range(0, len(lines), chunk_size):
            embeds.append(
                discord.Embed(
                    title=f"{ctx.author.display_name}'s Collection",
                    description="\n".join(lines[start : start + chunk_size]),
                    color=discord.Color.blue(),
                ).set_footer(
                    text=(
                        f"{start + 1}-{min(start + chunk_size, len(lines))} "
                        f"of {len(lines)} Pokémon"
                    )
                )
            )
        await ctx.send(
            embed=embeds[0],
            view=ReserveListView(ctx.author.id, embeds),
        )

    @collection.command(name="clear")
    async def clear_collection(self, ctx):
        """Clear the caller's collection."""
        if ctx.guild is None:
            await ctx.send("Collections can only be managed inside a server.")
            return
        guild_collections = self.bot_state["collections"].get(
            str(ctx.guild.id),
            {},
        )
        collection = guild_collections.pop(str(ctx.author.id), None)
        if not collection:
            await ctx.send("Your collection is already empty.")
            return
        self.save_bot_state()
        await ctx.send(
            f"✅ Cleared **{len(collection)}** Pokémon from your collection."
        )

    @commands.command(name="api")
    async def api_status(self, ctx):
        """Display live recognition, latency, and model performance."""
        def timing(values, mode="avg"):
            if not values:
                return 0.0
            if mode == "latest":
                return values[-1]
            if mode == "fastest":
                return min(values)
            if mode == "slowest":
                return max(values)
            return sum(values) / len(values)

        embed = discord.Embed(
            title="API Status",
            color=0x000000,
        )
        if self.bot.user:
            embed.set_author(
                name=self.bot.user.display_name,
                icon_url=self.bot.user.display_avatar.url,
            )

        fields = [
            (
                "Activity",
                (
                    "🟢 Waiting for spawns"
                    if not self.spawn_response_times
                    else (
                        "🟢 Very High Activity"
                        if timing(self.spawn_response_times) < 0.2
                        else "🟡 Active"
                    )
                ),
            ),
            (
                "Active Incense",
                str(self.active_incense_count()),
            ),
            (
                "Store (latest)",
                f"{timing(self.store_times, 'latest') * 1000:.0f} ms",
            ),
            (
                "Store (avg)",
                f"{timing(self.store_times) * 1000:.0f} ms",
            ),
            (
                "JSON load",
                f"{self.json_load_seconds * 1000:.0f} ms",
            ),
            (
                "CSV load",
                f"{self.model_load_seconds * 1000:.0f} ms",
            ),
            (
                "Inference Fastest",
                f"{timing(self.inference_times, 'fastest') * 1000:.0f} ms",
            ),
            (
                "Inference Slowest",
                f"{timing(self.inference_times, 'slowest') * 1000:.0f} ms",
            ),
            (
                "Inference Avg",
                f"{timing(self.inference_times) * 1000:.0f} ms",
            ),
            (
                "Inference Latest",
                f"{timing(self.inference_times, 'latest') * 1000:.0f} ms",
            ),
            (
                "Response Fastest",
                f"{timing(self.spawn_response_times, 'fastest') * 1000:.0f} ms",
            ),
            (
                "Response Slowest",
                f"{timing(self.spawn_response_times, 'slowest') * 1000:.0f} ms",
            ),
            (
                "Response Avg",
                f"{timing(self.spawn_response_times) * 1000:.2f} ms",
            ),
            (
                "Response Latest",
                f"{timing(self.spawn_response_times, 'latest') * 1000:.0f} ms",
            ),
            (
                "Pokémons Named",
                str(self.recognized_spawn_count),
            ),
        ]
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=True)
        server_names = ", ".join(sorted(guild.name for guild in self.bot.guilds))
        server_summary = server_names if server_names else "No connected servers"
        if len(server_summary) > 700:
            server_summary = f"{server_summary[:697]}..."
        embed.set_footer(
            text=(
                f"Model: {MODEL_READ_VERSION} | ONNX fp32 "
                f"| Window: latest 100 recognitions"
                f"\nServers ({len(self.bot.guilds)}): {server_summary}"
            )
        )
        await ctx.send(embed=embed)

    @commands.command(name="servers")
    async def servers(self, ctx):
        """List every Discord server this bot is connected to."""
        guilds = sorted(self.bot.guilds, key=lambda guild: guild.name.casefold())
        if not guilds:
            await ctx.send("This bot is not connected to any servers.")
            return
        lines = [
            f"• **{discord.utils.escape_markdown(guild.name)}** — `{guild.id}`"
            for guild in guilds
        ]
        await ctx.send(
            f"Connected to **{len(guilds)}** server(s):\n" + "\n".join(lines)
        )

    @commands.command(name="training")
    async def training_status(self, ctx):
        """Show how many reviewed images are waiting to be trained."""
        if ctx.channel.id != TRAINING_REVIEW_CHANNEL_ID:
            await ctx.send(
                f"Training review is only available in <#{TRAINING_REVIEW_CHANNEL_ID}>."
            )
            return
        await ctx.send(
            f"📚 **{self.reviewed_spawn_count}** reviewed image(s) collected. "
            "Use `v!export_training` to download them before retraining."
        )

    @commands.command(name="export_training")
    async def export_training(self, ctx):
        """Export only newly reviewed images for local retraining."""
        if ctx.channel.id != TRAINING_REVIEW_CHANNEL_ID:
            await ctx.send(
                f"Training export is only available in <#{TRAINING_REVIEW_CHANNEL_ID}>."
            )
            return
        if not os.path.exists(TRAINING_COLLECTION_FILE):
            await ctx.send("No reviewed training images have been collected yet.")
            return

        with open(TRAINING_COLLECTION_FILE, "r", encoding="utf-8") as f:
            collected = json.load(f)
        existing = [path for path in collected if os.path.exists(path)]
        if not existing:
            await ctx.send("The collected training images are no longer available.")
            return

        archive = BytesIO()
        with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
            for path in existing:
                zip_file.write(path, os.path.relpath(path, "pokemon_images"))
        if archive.tell() > 25 * 1024 * 1024:
            await ctx.send(
                "The training export exceeds Discord's 25 MB attachment limit. "
                "Export a smaller batch from the host."
            )
            return
        archive.seek(0)
        await ctx.send(
            content=f"📦 {len(existing)} reviewed image(s) ready for retraining.",
            file=discord.File(archive, filename="new_training_images.zip"),
        )

    def command_pages(self, command_only: bool = False) -> list[discord.Embed]:
        """Build help pages with no more than 20 commands per page."""
        entries = list(COMMAND_CATALOG)
        documented_paths = set()
        categories_by_root = {}
        for category, syntax, _ in COMMAND_CATALOG:
            command_text = re.sub(r"^[vVhH]!", "", syntax.strip())
            path_parts = []
            for part in command_text.split():
                if part.startswith(("<", "[")):
                    break
                path_parts.append(part)
            if not path_parts:
                continue
            command_path = " ".join(path_parts)
            documented_paths.add(command_path)
            categories_by_root.setdefault(path_parts[0], category)

        for command in self.bot.walk_commands():
            command_path = command.qualified_name
            if command_path in documented_paths:
                continue
            if any(path.startswith(f"{command_path} ") for path in documented_paths):
                continue
            syntax = f"v!{command_path}"
            if command.signature:
                syntax += f" {command.signature}"
            description = command.help or command.brief or "No description available."
            category = categories_by_root.get(command_path.split()[0], "Other")
            entries.append((category, syntax, description))

        page_size = 20
        page_count = (len(entries) + page_size - 1) // page_size
        pages = []
        for page_index in range(page_count):
            page_entries = entries[
                page_index * page_size : (page_index + 1) * page_size
            ]
            embed = discord.Embed(
                title=(
                    "Command List"
                    if command_only
                    else "🎀 Pokétwo Naming Bot Help"
                ),
                description=(
                    "Commands grouped by category."
                    if command_only
                    else "All commands and what each one does."
                ),
                color=discord.Color.purple(),
            )
            categories = {}
            for category, syntax, description in page_entries:
                categories.setdefault(category, []).append(
                    f"`{syntax}`"
                    if command_only
                    else f"`{syntax}`\n{description}"
                )
            for category, commands in categories.items():
                embed.add_field(
                    name=category,
                    value="\n".join(commands),
                    inline=False,
                )
            embed.set_footer(
                text=(
                    f"Page {page_index + 1}/{page_count} • "
                    f"{len(page_entries)} commands"
                )
            )
            pages.append(embed)
        return pages

    @commands.command(name="help")
    async def help_command(self, ctx, page: int = 1):
        """Display paginated command explanations."""
        pages = self.command_pages(command_only=False)
        if page < 1 or page > len(pages):
            await ctx.send(f"Choose a page from 1 to {len(pages)}.")
            return
        view = HelpPagesView(ctx.author.id, pages)
        view.page = page - 1
        view.update_buttons()
        await ctx.send(embed=pages[view.page], view=view)

    @commands.command(name="commands")
    async def commands_list(self, ctx, page: int = 1):
        """Display paginated command names by category."""
        pages = self.command_pages(command_only=True)
        if page < 1 or page > len(pages):
            await ctx.send(f"Choose a page from 1 to {len(pages)}.")
            return
        view = HelpPagesView(ctx.author.id, pages)
        view.page = page - 1
        view.update_buttons()
        await ctx.send(embed=pages[view.page], view=view)


async def setup(bot):
    """Load the bot cog"""
    await bot.add_cog(PokéTwoNamingBot(bot))
