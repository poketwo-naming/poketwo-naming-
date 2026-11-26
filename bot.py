"""
Pokétwo Naming Bot - Core bot functionality for naming Pokémon
"""
from collections import OrderedDict, deque
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import asyncio
import csv
import json
import logging
import os
import re
from time import perf_counter, time
from types import CoroutineType
from typing import Any, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from geonamescache import GeonamesCache
from PIL import Image, UnidentifiedImageError

from breeding_boxes import BreedingBoxService
from dex_tracking import (
    DexSettingsView,
    DexTrackingService,
    dex_ping_owners,
    remove_caught_dex_entry,
)
from pokemon_recognition import PokemonImageRecognizer
from starboard import StarboardService, StarboardSettingsView
from roles_channels import RolesChannelsSettingsView
from tools.build_pokemon_types import (
    CUSTOM_SPRITE_IDENTIFIERS,
    normalize as normalize_pokemon_alias,
)


POKETWO_BOT_ID = 716390085896962058
BREEDING_BOX_LIMIT = 7_500
MISSINGNO_ALERT_ROLE_ID = 1573065640762151003
TIMEZONE_ROLE_ID = 1553235133119598652
TRAINING_REVIEW_CHANNEL_ID = 1531476097970212915
RESERVE_REPORT_CHANNEL_ID = 1532512015703085147
RESERVE_TRADE_THREAD_ID = 1538294047095922748
FFA_REVIEW_CHANNEL_ID = 1572693324815667270
FFA_REVIEW_ROLE_ID = 1574935908153557103
FFA_ANNOUNCEMENT_CHANNEL_ID = 1531481080618680556
FFA_ROLE_ID = 1532824522120495296
INCENSE_INACTIVITY_SECONDS = float(
    os.getenv("INCENSE_INACTIVITY_SECONDS", "90")
)
INCENSE_PURCHASE_PAUSE_WINDOW_SECONDS = 10 * 60 * 60
TRAINING_ROOT = "pokemon_images/training_data"
TRAINING_COLLECTION_FILE = "pokemon_images/new_training_images.json"
SPAWN_DOWNLOAD_SIZE = 232
MODEL_READ_VERSION = "V2.0.0"
TRAINING_REVIEWER_USER_IDS = {217819108329259008}
BOT_STATE_FILE = os.getenv("BOT_STATE_FILE", "bot_state.json")
CUSTOM_SPRITE_BASE_URL = (
    "https://raw.githubusercontent.com/"
    "poketwo-naming/poketwo-naming-/main/pokemon_sprites"
)
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
REGIONS = {
    "Kanto": None,
    "Johto": None,
    "Hoenn": None,
    "Sinnoh": None,
    "Unova": None,
    "Kalos": None,
    "Alola": "Alolan ",
    "Galar": "Galarian ",
    "Hisui": "Hisuian ",
    "Paldea": "Paldean ",
    "Kitakami": None,
    "Paradox": None,
}
QUEST_ORIGIN_RANGES = (
    (1, 151, "Kanto"),
    (152, 251, "Johto"),
    (252, 386, "Hoenn"),
    (387, 493, "Sinnoh"),
    (494, 649, "Unova"),
    (650, 721, "Kalos"),
    (722, 809, "Alola"),
    (810, 898, "Galar"),
    (899, 905, "Hisui"),
    (906, 1025, "Paldea"),
)
PARADOX_SPECIES_IDS = set(range(984, 996)) | {
    1005, 1006, 1007, 1008, 1009, 1010, 1020, 1021, 1022, 1023,
}
PALDEAN_TAUROS_FORMS = {
    "Combat Breed Tauros",
    "Blaze Breed Tauros",
    "Aqua Breed Tauros",
}
TIMEZONE_PHASE_EMOJIS = {
    "day": "☀️",
    "night": "🌙",
    "dawn": "🌅",
    "dusk": "🌇",
}
RESERVE_CATEGORY_PRICES = {
    "gmax": 35_000,
    "eevos": 35_000,
    "paradox": 35_000,
    "rare": 45_000,
    "regional": 45_000,
    "events": 45_000,
}
EVENT_FORM_PRICES = {
    "Enchanted Applin": 45_000,
    "Rotten Applin": 45_000,
    "Oracle Meowscarada": 45_000,
    "Witch Meowscarada": 45_000,
    "Medusa Simipour": 45_000,
    "Statue Simipour": 45_000,
    "Elixir Reuniclus": 45_000,
    "Cauldron Reuniclus": 45_000,
}
EVENT_FORM_BASES = {
    "Enchanted Applin": "Applin",
    "Rotten Applin": "Applin",
    "Oracle Meowscarada": "Meowscarada",
    "Witch Meowscarada": "Meowscarada",
    "Medusa Simipour": "Simipour",
    "Statue Simipour": "Simipour",
    "Elixir Reuniclus": "Reuniclus",
    "Cauldron Reuniclus": "Reuniclus",
}
SPAWN_RATE_PRICES = (
    (255, 2_500),
    (337, 5_000),
    (674, 10_000),
    (899, 15_000),
    (1_349, 20_000),
    (3_596, 30_000),
    (5_394, 35_000),
    (15_196, 40_000),
    (30_000, 50_000),
)
COMMAND_CATALOG = (
    ("General", "v!ping", "Shows the bot's gateway latency."),
    (
        "General",
        "v!typeping",
        "Manage type pings with v!tp water fire, v!tp remove water fire, or /tp add/remove.",
    ),
    (
        "General",
        "v!questping",
        "Manage quest pings with v!qp kanto johto, v!qp remove kanto johto, or /qp add/remove.",
    ),
    (
        "Breeding Boxes & Daycare",
        "v!box",
        "Shows all of your boxes and how full they are (limit 7,500 each).",
    ),
    (
        "Breeding Boxes & Daycare",
        "v!box create <name>",
        "Makes a new box.",
    ),
    (
        "Breeding Boxes & Daycare",
        "v!box append [box] [--c]",
        "Replies to a Pokétwo list to store its Pokémon; page arrows keep adding.",
    ),
    (
        "Breeding Boxes & Daycare",
        "v!box list / remove / transfer / copy",
        "Browses, deletes, moves, or duplicates stored Pokémon and boxes.",
    ),
    (
        "Breeding Boxes & Daycare",
        "v!box tag / untag / tags / tagged",
        "Tracks egg moves on stored Pokémon.",
    ),
    (
        "Breeding Boxes & Daycare",
        "v!box rename / delete / clear / reset",
        "Manages or wipes boxes.",
    ),
    (
        "Breeding Boxes & Daycare",
        "v!dc [box]",
        "Pulls one breedable pair with a ready-to-paste daycare command.",
    ),
    (
        "Breeding Boxes & Daycare",
        "v!dc menu",
        "Opens the daycare settings menu to customize pair selection and output.",
    ),
    (
        "Breeding Boxes & Daycare",
        "v!boxhelp",
        "Shows the full list of box commands.",
    ),
    (
        "General",
        "v!support",
        "Shows how to support Vivillon's running and development costs.",
    ),
    (
        "General",
        "v!tz <day|night|dawn|dusk>",
        "Finds one place currently in that local-time phase and gives a Pokétwo command.",
    ),
    ("General", "v!sr <pokemon>", "Shows a Pokémon's spawn rate and artwork."),
    (
        "Reservations",
        "v!report",
        "Replies to a Pokétwo catch announcement to report a stolen reserve.",
    ),
    ("General", "v!help [page]", "Shows all commands with descriptions, paginated."),
    ("General", "v!commands [page]", "Shows categorized command names, paginated."),
    (
        "Recognition",
        "v!api",
        "Shows global incense, recognition, inference, and response metrics.",
    ),
    (
        "Recognition",
        "v!apislow",
        "Breaks down the slowest recent spawn response.",
    ),
    ("Recognition", "v!servers", "Lists every server where the bot is connected."),
    (
        "Channel Controls",
        "v!resume",
        "Resumes Pokétwo in the current channel. Restricted.",
    ),
    (
        "Channel Controls",
        "v!r all",
        "Resumes Pokétwo in every tracked paused channel in this server. Restricted.",
    ),
    (
        "Channel Controls",
        "v!pause (alias: v!p)",
        "Pauses Pokétwo in the current channel. Restricted.",
    ),
    (
        "Channel Controls",
        "v!p all",
        "Pauses channels with a confirmed incense purchase in the last 10 hours. Restricted.",
    ),
    (
        "Channel Controls",
        "v!poff / v!pon",
        "Disable or enable automatic pausing after confirmed incense purchases. Restricted.",
    ),
    (
        "Reservations",
        "v!r add [all] <pokemon,...> <@user> [<@user2> ...]",
        "Reserves comma-separated Pokémon/forms for one or more members. Restricted.",
    ),
    (
        "Reservations",
        "v!r remove <pokemon,...> [@user]",
        "Removes Pokémon or a category of reservations. Restricted.",
    ),
    (
        "Reservations",
        "v!r search <pokemon|category>",
        "Shows reservations and, for categories, unreserved Pokémon.",
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
        "v!rafk",
        "Release your reserves or a category and request a staff-approved FFA announcement.",
    ),
    (
        "Reservations",
        "v!r clear",
        "Asks for confirmation before clearing every server reservation. Restricted.",
    ),
    (
        "Reservations",
        "v!grab",
        "Replies to a reserve list with sorting, form, copy, reserve, and ready-up "
        "controls.",
    ),
    (
        "Reservations",
        "v!readyup",
        "Starts a ready check for users added from v!grab. Restricted.",
    ),
    (
        "Reservations",
        "v!readyup clear",
        "Clears the ready-up queue and ends its active check. Restricted.",
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
        "v!cl add [all] <pokemon,...|category>",
        "Adds Pokémon/forms or every member of a server category to your collection.",
    ),
    (
        "Collections",
        "v!cl remove <pokemon,...|category>",
        "Removes Pokémon/forms or every member of a server category from your collection.",
    ),
    (
        "Collections",
        "v!cl search <pokemon>",
        "Checks whether a Pokémon is in your collection.",
    ),
    ("Collections", "v!cl list", "Lists your own collection."),
    ("Collections", "v!cl clear", "Clears your own collection."),
    (
        "Collections",
        "v!dex append",
        "Replies to a Pokétwo Pokédex to track missing entries and visited pages.",
    ),
    (
        "Collections",
        "v!dexhelp",
        "Manages dex pings, target count, and the missing-Pokémon queue.",
    ),
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
TYPE_NAMES = tuple(sorted(TYPE_EMOJIS))


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

    def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> CoroutineType[Any, Any, None]:
        return self._handle_submit(interaction)

    async def _handle_submit(self, interaction: discord.Interaction) -> None:
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


def save_ping_selection(
    cog,
    state_key: str,
    user_id: int,
    selected: list[str],
    guild_id: int | None = None,
) -> None:
    settings = cog.bot_state.setdefault(state_key, {})
    if guild_id is not None:
        settings = settings.setdefault(str(guild_id), {})
    user_key = str(user_id)
    previous = settings.get(user_key)
    settings[user_key] = sorted(set(selected))
    try:
        cog.save_bot_state()
    except OSError:
        if previous is None:
            settings.pop(user_key, None)
        else:
            settings[user_key] = previous
        raise


class TypePingView(discord.ui.View):
    """Choose which Pokémon types trigger spawn pings."""

    class TypeSelect(discord.ui.Select):
        def __init__(self, owner: "TypePingView"):
            self.owner = owner
            selected = owner.cog.type_ping_types(owner.user_id, owner.guild_id)
            super().__init__(
                placeholder="Select type(s) to receive pings...",
                min_values=0,
                max_values=len(TYPE_NAMES),
                options=[
                    discord.SelectOption(
                        label=pokemon_type.title(),
                        value=pokemon_type,
                        emoji=TYPE_EMOJIS[pokemon_type],
                        default=pokemon_type in selected,
                    )
                    for pokemon_type in TYPE_NAMES
                ],
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            await self.owner.update_types(interaction, self.values)

    class ToggleButton(discord.ui.Button):
        def __init__(self, owner: "TypePingView", enabled: bool):
            super().__init__(
                label="All On" if enabled else "All Off",
                style=discord.ButtonStyle.success
                if enabled
                else discord.ButtonStyle.danger,
            )
            self.owner = owner
            self.enabled = enabled

        async def callback(self, interaction: discord.Interaction) -> None:
            types = TYPE_NAMES if self.enabled else ()
            await self.owner.update_types(interaction, types)

    def __init__(self, cog, user_id: int, guild_id: int | None = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.refresh_components()

    def build_embed(self) -> discord.Embed:
        selected = set(self.cog.type_ping_types(self.user_id, self.guild_id))
        lines = [
            f"{TYPE_EMOJIS[pokemon_type]} {pokemon_type.title()} "
            f"{'✅' if pokemon_type in selected else '❌'}"
            for pokemon_type in TYPE_NAMES
        ]
        return discord.Embed(
            title="Type Pings",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )

    def refresh_components(self) -> None:
        self.clear_items()
        self.add_item(self.TypeSelect(self))
        self.add_item(self.ToggleButton(self, enabled=True))
        self.add_item(self.ToggleButton(self, enabled=False))

    async def update_types(
        self,
        interaction: discord.Interaction,
        selected_types: list[str] | tuple[str, ...],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who opened these type-ping settings can change them.",
                ephemeral=True,
            )
            return

        selected = sorted(set(selected_types) & set(TYPE_NAMES))
        try:
            save_ping_selection(
                self.cog,
                "type_pings",
                self.user_id,
                selected,
                self.guild_id,
            )
        except OSError:
            logging.getLogger(__name__).exception("Could not save type-ping settings")
            await interaction.response.send_message(
                "❌ I couldn't save your type-ping settings. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.refresh_components()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )


class QuestPingView(discord.ui.View):
    """Choose which regions trigger quest pings."""

    class RegionSelect(discord.ui.Select):
        def __init__(self, owner: "QuestPingView"):
            self.owner = owner
            selected = owner.cog.quest_ping_regions(owner.user_id, owner.guild_id)
            super().__init__(
                placeholder="Select regions to receive quest pings...",
                min_values=0,
                max_values=len(REGIONS),
                options=[
                    discord.SelectOption(
                        label=region,
                        value=region,
                        default=region in selected,
                    )
                    for region in REGIONS
                ],
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            await self.owner.update_regions(interaction, self.values)

    class ToggleButton(discord.ui.Button):
        def __init__(self, owner: "QuestPingView", enabled: bool):
            super().__init__(
                label="All On" if enabled else "All Off",
                style=discord.ButtonStyle.success
                if enabled
                else discord.ButtonStyle.danger,
            )
            self.owner = owner
            self.enabled = enabled

        async def callback(self, interaction: discord.Interaction) -> None:
            regions = tuple(REGIONS.keys()) if self.enabled else ()
            await self.owner.update_regions(interaction, regions)

    def __init__(self, cog, user_id: int, guild_id: int | None = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.refresh_components()

    def build_embed(self) -> discord.Embed:
        selected = set(self.cog.quest_ping_regions(self.user_id, self.guild_id))
        lines = [
            f"{region} {'✅' if region in selected else '❌'}"
            for region in REGIONS
        ]
        return discord.Embed(
            title="Quest Pings",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )

    def refresh_components(self) -> None:
        self.clear_items()
        self.add_item(self.RegionSelect(self))
        self.add_item(self.ToggleButton(self, enabled=True))
        self.add_item(self.ToggleButton(self, enabled=False))

    async def update_regions(
        self,
        interaction: discord.Interaction,
        selected_regions: list[str] | tuple[str, ...],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who opened these quest-ping settings can change them.",
                ephemeral=True,
            )
            return

        selected = sorted(set(selected_regions) & set(REGIONS.keys()))
        try:
            save_ping_selection(
                self.cog,
                "quest_pings",
                self.user_id,
                selected,
                self.guild_id,
            )
        except OSError:
            logging.getLogger(__name__).exception("Could not save quest-ping settings")
            await interaction.response.send_message(
                "❌ I couldn't save your quest-ping settings. Check the bot logs.",
                ephemeral=True,
            )
            return

        self.refresh_components()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )


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


class FFANameModal(discord.ui.Modal, title="Release a reserve"):
    pokemon_name = discord.ui.TextInput(
        label="Pokémon names or category",
        placeholder="Pikachu, Eevee or a server category",
        max_length=1000,
    )

    def __init__(self, view):
        super().__init__()
        self.reserve_view = view

    async def on_submit(self, interaction: discord.Interaction):
        await self.reserve_view.release(interaction, self.pokemon_name.value)


class FFAReserveView(discord.ui.View):
    """Release the command author's reserves and request an announcement."""

    def __init__(
        self, cog, guild_id: int, guild_name: str, user_id: int,
        released: str | None = None,
    ):
        super().__init__(timeout=None if released else 300)
        self.cog = cog
        self.guild_id = guild_id
        self.guild_name = guild_name
        self.user_id = user_id
        self.released = released
        self.submitting = False
        self.page = 0
        self.announcement.disabled = released is None
        self.ffa.disabled = released is not None or not self.own_reserves()
        self.all_ffa.disabled = self.ffa.disabled
        if len(self.own_reserves()) <= 20:
            self.remove_item(self.previous)
            self.remove_item(self.next)
        self.update_pages()

    def own_reserves(self) -> list[str]:
        reserves = self.cog.bot_state["reserves"].get(str(self.guild_id), {})
        return sorted(
            (
                name for name in reserves
                if str(self.user_id) in self.cog.reserve_user_ids(self.guild_id, name)
            ),
            key=str.casefold,
        )

    def build_embed(self) -> discord.Embed:
        names = self.own_reserves()
        self.page = min(self.page, max(0, (len(names) - 1) // 20))
        shown = names[self.page * 20 : (self.page + 1) * 20]
        description = (
            "\n".join(f"• {name}" for name in shown)
            if shown else "You have no reserves."
        )
        if self.released:
            description += (
                f"\n\nReleased: **{discord.utils.escape_markdown(self.released[:500])}**. "
                "Use Announcement to request staff approval."
            )
        embed = discord.Embed(
            title="Your Pokémon Reserves",
            description=description,
            color=discord.Color.purple(),
        )
        if names:
            embed.set_footer(text=f"Page {self.page + 1} of {(len(names) + 19) // 20}")
        return embed

    def update_pages(self):
        names = self.own_reserves()
        self.page = min(self.page, max(0, (len(names) - 1) // 20))
        self.previous.disabled = self.page == 0
        self.next.disabled = (self.page + 1) * 20 >= len(names)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only the person who ran v!rafk can use these buttons.", ephemeral=True
        )
        return False

    async def release(self, interaction: discord.Interaction, name: str, *, all_reserves=False):
        if not await self.interaction_check(interaction):
            return
        message = interaction.message
        if message is None:
            await interaction.response.send_message(
                "❌ The reserve message is unavailable. Run v!rafk again.",
                ephemeral=True,
            )
            return
        if self.released is not None:
            await interaction.response.send_message(
                "Run v!rafk again to release another Pokémon.", ephemeral=True
            )
            return
        names = self.own_reserves()
        names_by_key = {item.casefold(): item for item in names}
        category = None
        exceptions = []
        if all_reserves:
            chosen = names
        else:
            category = self.cog.find_category(self.guild_id, name.strip())
            if category is not None:
                members = list(dict.fromkeys(
                    self.cog.guild_categories(self.guild_id)[category]
                ))
                chosen = [
                    names_by_key[item.casefold()] for item in members
                    if item.casefold() in names_by_key
                ]
                exceptions = [
                    item for item in members if item.casefold() not in names_by_key
                ]
            else:
                terms = [item.strip() for item in name.split(",")]
                invalid = [item for item in terms if item.casefold() not in names_by_key]
                if invalid:
                    await interaction.response.send_message(
                        "❌ These Pokémon are not in your current reserves: "
                        + ", ".join(discord.utils.escape_markdown(item or "(empty)") for item in invalid),
                        ephemeral=True,
                    )
                    return
                chosen = list(dict.fromkeys(names_by_key[item.casefold()] for item in terms))
        if not chosen:
            await interaction.response.send_message(
                "❌ You have no reserves to release for that selection.",
                ephemeral=True,
            )
            return
        label = category if category else ", ".join(chosen)
        reserves = self.cog.bot_state["reserves"][str(self.guild_id)]
        previous = {item: reserves[item] for item in chosen}
        releases = self.cog.bot_state.setdefault("ffa_releases", {})
        message_id = str(message.id)
        for item in chosen:
            self.cog.remove_reserve_owner(self.guild_id, item, self.user_id)
        release_data = {
            "guild_id": self.guild_id, "guild_name": self.guild_name,
            "user_id": self.user_id, "pokemon": label,
            "pokemon_names": chosen, "category": category, "exceptions": exceptions,
        }
        releases[message_id] = release_data
        try:
            self.cog.save_bot_state()
        except OSError:
            reserves.update(previous)
            releases.pop(message_id, None)
            logging.getLogger(__name__).exception("Could not save FFA reserve release")
            await interaction.response.send_message(
                "❌ I couldn't remove your reserve. Check the bot logs.", ephemeral=True
            )
            return
        self.released = label
        self.timeout = None
        self.ffa.disabled = True
        self.all_ffa.disabled = True
        self.announcement.disabled = False
        self.update_pages()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(
        label="FFA", style=discord.ButtonStyle.danger, custom_id="rafk_release"
    )
    async def ffa(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        names = self.own_reserves()
        if not names:
            await interaction.response.send_message(
                "❌ You have no reserves to release.", ephemeral=True
            )
        elif len(names) == 1 and not self.cog.bot_state.get("categories", {}).get(str(self.guild_id)):
            await self.release(interaction, names[0])
        else:
            await interaction.response.send_modal(FFANameModal(self))

    @discord.ui.button(
        label="All FFA", style=discord.ButtonStyle.danger, custom_id="rafk_all"
    )
    async def all_ffa(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        await self.release(interaction, "", all_reserves=True)

    @discord.ui.button(
        label="Announcement", style=discord.ButtonStyle.primary, custom_id="rafk_announcement"
    )
    async def announcement(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        origin_message = interaction.message
        if origin_message is None:
            await interaction.response.send_message(
                "❌ The reserve message is unavailable. Check the original v!rafk message.",
                ephemeral=True,
            )
            return
        if self.released is None:
            await interaction.response.send_message(
                "❌ Release a reserve with FFA first.", ephemeral=True
            )
            return
        name = self.released
        requests = self.cog.bot_state.setdefault("ffa_requests", {})
        releases = self.cog.bot_state.setdefault("ffa_releases", {})
        if str(origin_message.id) not in releases:
            await interaction.response.send_message(
                "❌ An announcement has already been requested for this release.",
                ephemeral=True,
            )
            return
        release_data = releases[str(origin_message.id)]
        names = release_data.get("pokemon_names", [name])
        category = release_data.get("category")
        unavailable = [
            item for item in names if self.cog.reserve_user_ids(self.guild_id, item)
        ]
        available = [item for item in names if item not in unavailable]
        if not available:
            await interaction.response.send_message(
                "❌ This selection is still reserved by someone. "
                "Nothing can be announced as FFA yet.",
                ephemeral=True,
            )
            return
        keys = {(self.guild_id, item) for item in available}
        if self.submitting or keys & self.cog.ffa_requests_in_flight or any(
            request["guild_id"] == self.guild_id
            and set(request.get("pokemon_names", [request["pokemon"]])) & set(available)
            and request["status"] in ("pending", "sending")
            for request in requests.values()
        ):
            await interaction.response.send_message(
                "❌ An announcement request for this Pokémon is already pending.",
                ephemeral=True,
            )
            return
        self.submitting = True
        self.cog.ffa_requests_in_flight.update(keys)
        try:
            await interaction.response.defer(ephemeral=True)
            guild_settings = self.cog.bot_state.get("guild_settings", {}).get(
                str(self.guild_id), {}
            ).get("roles_channels", {})
            ffa_review_role_id = guild_settings.get("ffa_review_role", FFA_REVIEW_ROLE_ID)
            ffa_review_channel_id = guild_settings.get("ffa_review_channel", FFA_REVIEW_CHANNEL_ID)
            channel = self.cog.bot.get_channel(ffa_review_channel_id)
            if channel is None:
                channel = await self.cog.bot.fetch_channel(ffa_review_channel_id)
            if any(self.cog.reserve_user_ids(self.guild_id, item) for item in available):
                await interaction.followup.send(
                    "❌ This Pokémon is reserved again, so no request was sent.",
                    ephemeral=True,
                )
                return
            exceptions = list(dict.fromkeys(release_data.get("exceptions", []) + unavailable))
            summary = (
                f"{category} FFA" + (f" except {', '.join(exceptions)}" if exceptions else "")
                if category else ", ".join(available)
            )
            view = FFAReviewView(self.cog)
            escaped_summary = discord.utils.escape_markdown(summary)
            review_details = {}
            if len(escaped_summary) > 1400:
                escaped_summary = "See the attached FFA details"
                review_details["file"] = discord.File(
                    BytesIO(summary.encode("utf-8")), filename="ffa-details.txt"
                )
            message = await channel.send(
                f"<@&{ffa_review_role_id}> FFA announcement request for **{escaped_summary}**\n"
                f"Requested by: `{self.user_id}`\n"
                f"Source server: {discord.utils.escape_markdown(self.guild_name)} "
                f"(`{self.guild_id}`)\n"
                "A member with restricted-command permission must approve or deny.",
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    roles=[discord.Object(id=ffa_review_role_id)],
                    users=False,
                    everyone=False,
                ),
                **review_details,
            )
            requests[str(message.id)] = {
                "guild_id": self.guild_id, "guild_name": self.guild_name,
                "user_id": self.user_id, "pokemon": name, "status": "pending",
                "pokemon_names": available, "category": category, "exceptions": exceptions,
            }
            submitted_releases = {}
            for message_id, release in list(releases.items()):
                if release["guild_id"] != self.guild_id:
                    continue
                release_names = release.get("pokemon_names", [release["pokemon"]])
                overlap = [item for item in release_names if item in available]
                if message_id != str(origin_message.id) and not overlap:
                    continue
                submitted_releases[message_id] = release
                remaining = [item for item in release_names if item not in available]
                if message_id == str(origin_message.id) or not remaining:
                    releases.pop(message_id)
                else:
                    updated: dict = dict(release)
                    updated["pokemon_names"] = remaining
                    if release.get("category"):
                        updated["exceptions"] = list(dict.fromkeys(
                            release.get("exceptions", []) + overlap
                        ))
                    else:
                        updated["pokemon"] = ", ".join(remaining)
                    releases[message_id] = updated
            try:
                self.cog.save_bot_state()
            except OSError:
                requests.pop(str(message.id), None)
                releases.update(submitted_releases)
                try:
                    await message.edit(view=None)
                except discord.HTTPException:
                    logging.getLogger(__name__).exception("Could not disable unsaved FFA review")
                raise
            button.disabled = True
            try:
                await origin_message.edit(embed=self.build_embed(), view=self)
            except discord.HTTPException:
                logging.getLogger(__name__).exception("Could not update FFA request controls")
            self.stop()
            await interaction.followup.send(
                "✅ Your FFA announcement was sent for approval."
                + (
                    " Pokémon still reserved by someone else were excluded: "
                    + ", ".join(discord.utils.escape_markdown(item) for item in unavailable)
                    if unavailable else ""
                )[:1500],
                ephemeral=True,
            )
        except (discord.DiscordException, aiohttp.ClientError, OSError, asyncio.TimeoutError):
            logging.getLogger(__name__).exception("Could not submit FFA review request")
            await interaction.followup.send(
                "❌ The FFA request could not be completed. Check the bot logs; "
                "your reserve remains removed.",
                ephemeral=True,
            )
        finally:
            self.submitting = False
            self.cog.ffa_requests_in_flight.difference_update(keys)

    @discord.ui.button(
        label="Previous", style=discord.ButtonStyle.secondary, custom_id="rafk_previous"
    )
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self.update_pages()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(
        label="Next", style=discord.ButtonStyle.secondary, custom_id="rafk_next"
    )
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self.update_pages()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class FFAReviewView(discord.ui.View):
    """Persistent staff controls for an FFA announcement request."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.lock = asyncio.Lock()

    async def decide(self, interaction: discord.Interaction, approve: bool):
        if not self.cog.has_restricted_interaction_permission(interaction):
            await interaction.response.send_message(
                "❌ You need restricted-command permission to review this request.",
                ephemeral=True,
            )
            return
        message = interaction.message
        if message is None:
            await interaction.response.send_message(
                "❌ The review message is unavailable. Please use the original review message.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            request = self.cog.bot_state.get("ffa_requests", {}).get(
                str(message.id)
            )
            if request is None or request["status"] != "pending":
                await interaction.followup.send(
                    "❌ This request is already handled or its delivery needs checking.",
                    ephemeral=True,
                )
                return
            names = request.get("pokemon_names", [request["pokemon"]])
            if approve and any(
                self.cog.reserve_user_ids(request["guild_id"], name) for name in names
            ):
                await interaction.followup.send(
                    "❌ This Pokémon is reserved again in the source server; "
                    "it cannot be announced as FFA.",
                    ephemeral=True,
                )
                return
            channel = None
            if approve:
                guild_settings = self.cog.bot_state.get("guild_settings", {}).get(
                    str(request["guild_id"]), {}
                ).get("roles_channels", {})
                ffa_announcement_channel_id = guild_settings.get(
                    "ffa_announcement_channel", FFA_ANNOUNCEMENT_CHANNEL_ID
                )
                try:
                    channel = self.cog.bot.get_channel(ffa_announcement_channel_id)
                    if channel is None:
                        channel = await self.cog.bot.fetch_channel(
                            ffa_announcement_channel_id
                        )
                except (
                    discord.DiscordException, aiohttp.ClientError, OSError, asyncio.TimeoutError
                ):
                    logging.getLogger(__name__).exception("Could not find FFA announcement channel")
                    await interaction.followup.send(
                        "❌ Could not access the announcement channel. Please retry.",
                        ephemeral=True,
                    )
                    return
                if channel is None:
                    logging.getLogger(__name__).error("FFA announcement channel was not found")
                    await interaction.followup.send(
                        "❌ Could not access the announcement channel. Please retry.",
                        ephemeral=True,
                    )
                    return
                if any(
                    self.cog.reserve_user_ids(request["guild_id"], name) for name in names
                ):
                    await interaction.followup.send(
                        "❌ This Pokémon is reserved again in the source server.",
                        ephemeral=True,
                    )
                    return
            request["status"] = "sending" if approve else "denied"
            reserves = None
            if not approve:
                reserves = self.cog.bot_state["reserves"].setdefault(
                    str(request["guild_id"]), {}
                )
                for pokemon_name in names:
                    if pokemon_name not in reserves:
                        reserves[pokemon_name] = []
                    if str(request["user_id"]) not in reserves[pokemon_name]:
                        reserves[pokemon_name].append(str(request["user_id"]))
            try:
                self.cog.save_bot_state()
            except OSError:
                request["status"] = "pending"
                if reserves is not None:
                    for pokemon_name in names:
                        if str(request["user_id"]) in reserves.get(pokemon_name, []):
                            reserves[pokemon_name].remove(str(request["user_id"]))
                logging.getLogger(__name__).exception("Could not save FFA review decision")
                await interaction.followup.send(
                    "❌ Could not save the review decision. Please retry.", ephemeral=True
                )
                return
            if approve and channel is not None:
                try:
                    guild_settings = self.cog.bot_state.get("guild_settings", {}).get(
                        str(request["guild_id"]), {}
                    ).get("roles_channels", {})
                    ffa_role_id = guild_settings.get("ffa_role", FFA_ROLE_ID)
                    category = request.get("category")
                    if category:
                        summary = f"{category} FFA"
                        if request.get("exceptions"):
                            summary += f" except {', '.join(request['exceptions'])}"
                    else:
                        summary = (
                            f"{', '.join(names)} is now FFA, "
                            "you're now free to catch this Pokémon."
                            if len(names) == 1 else f"{', '.join(names)} are now FFA."
                        )
                    escaped_summary = discord.utils.escape_markdown(summary)
                    announcement_details = {}
                    if len(escaped_summary) > 1800:
                        escaped_summary = "FFA details are in the attached file."
                        announcement_details["file"] = discord.File(
                            BytesIO(summary.encode("utf-8")), filename="ffa-details.txt"
                        )
                    await channel.send(
                        f"<@&{ffa_role_id}> {escaped_summary}",
                        allowed_mentions=discord.AllowedMentions(
                            roles=[discord.Object(id=ffa_role_id)],
                            users=False,
                            everyone=False,
                        ),
                        **announcement_details,
                    )
                except (
                    discord.DiscordException, aiohttp.ClientError, OSError, asyncio.TimeoutError
                ):
                    logging.getLogger(__name__).exception("FFA announcement delivery failed")
                    await interaction.followup.send(
                        "❌ Delivery could not be confirmed. Check the announcement channel "
                        "before sending anything manually; this request cannot be retried.",
                        ephemeral=True,
                    )
                    return
                request["status"] = "approved"
                try:
                    self.cog.save_bot_state()
                except OSError:
                    request["status"] = "sending"
                    logging.getLogger(__name__).exception("Could not save sent FFA announcement")
                    await interaction.followup.send(
                        "⚠️ The announcement was sent, but its status could not be saved. "
                        "Do not send it again; check the bot logs.",
                        ephemeral=True,
                    )
                    return
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            result = "Approved and announced" if approve else "Denied"
            try:
                await message.edit(
                    content=f"{message.content}\n\n{result} by `{interaction.user.id}`.",
                    view=self,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                logging.getLogger(__name__).exception("Could not update FFA review message")
                await interaction.followup.send(
                    f"⚠️ {result}, but the review message could not be updated.",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(f"✅ {result}.", ephemeral=True)

    @discord.ui.button(
        label="Approve", style=discord.ButtonStyle.success, custom_id="ffa_review_approve"
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.decide(interaction, True)

    @discord.ui.button(
        label="Deny", style=discord.ButtonStyle.danger, custom_id="ffa_review_deny"
    )
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.decide(interaction, False)


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


class NamingSettingsView(discord.ui.LayoutView):
    """Naming configuration settings."""

    class SettingButton(discord.ui.Button):
        def __init__(
            self,
            owner: "NamingSettingsView",
            setting: str,
            label: str,
            enabled: bool,
            style: discord.ButtonStyle | None = None,
        ):
            self.owner = owner
            self.setting = setting
            super().__init__(
                label=label,
                style=style
                or (
                    discord.ButtonStyle.green
                    if enabled
                    else discord.ButtonStyle.red
                ),
            )

        async def callback(self, interaction: discord.Interaction) -> None:
            await self.owner.toggle_setting(interaction, self.setting)

    def __init__(self, cog: "PokéTwoNamingBot", user_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.rebuild()

    def get_naming_settings(self) -> dict:
        """Get naming settings for this guild."""
        guild_settings = self.cog.bot_state.setdefault("guild_settings", {})
        return guild_settings.setdefault(str(self.guild_id), {}).setdefault(
            "naming", {}
        )

    def rebuild(self) -> None:
        """Rebuild the V2 layout from the latest settings."""
        self.clear_items()
        settings = self.get_naming_settings()
        naming_enabled = settings.get("enabled", True)
        naming_mode = settings.get("mode", "assisted")  # 'assisted' or 'embed'
        only_pings = settings.get("only_pings", False)
        best_name = settings.get("best_name", True)

        container = discord.ui.Container()
        container.add_item(
            discord.ui.TextDisplay(
                "## Server Settings · Naming\n"
                "Configure this section. Changes save immediately."
            )
        )
        container.add_item(discord.ui.Separator())

        container.add_item(
            discord.ui.Section(
                "**Naming**\n"
                f"{'Enabled' if naming_enabled else 'Disabled'} · "
                "Allow the bot to send Pokémon predictions.",
                accessory=self.SettingButton(
                    self,
                    "enabled",
                    "On" if naming_enabled else "Off",
                    naming_enabled,
                ),
            )
        )
        container.add_item(
            discord.ui.Section(
                "**Naming Mode**\n"
                + (
                    "Assisted adds copy-ready catch commands beneath predictions."
                    if naming_mode == "assisted"
                    else "Embed Mode puts the catch command in a copyable code block."
                ),
                accessory=self.SettingButton(
                    self,
                    "mode",
                    "Assisted" if naming_mode == "assisted" else "Embed Mode",
                    True,
                    discord.ButtonStyle.primary,
                ),
            )
        )
        container.add_item(
            discord.ui.Section(
                "**Only Pings**\n"
                f"{'Enabled' if only_pings else 'Disabled'} · "
                "Suppress naming output unless a configured ping applies.",
                accessory=self.SettingButton(
                    self,
                    "only_pings",
                    "On" if only_pings else "Off",
                    only_pings,
                ),
            )
        )
        container.add_item(
            discord.ui.Section(
                "**Best Name**\n"
                f"{'Enabled' if best_name else 'Disabled'} · "
                "Use the fastest normalized catch alias when one is available.",
                accessory=self.SettingButton(
                    self,
                    "best_name",
                    "On" if best_name else "Off",
                    best_name,
                ),
            )
        )
        back_button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
        )
        back_button.callback = self.go_back
        back_row = discord.ui.ActionRow()
        back_row.add_item(back_button)
        container.add_item(back_row)
        self.add_item(container)

    async def toggle_setting(
        self, interaction: discord.Interaction, setting: str
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran v!settings can change these settings.",
                ephemeral=True,
            )
            return
        settings = self.get_naming_settings()
        if setting == "mode":
            settings["mode"] = (
                "embed" if settings.get("mode", "assisted") == "assisted"
                else "assisted"
            )
        elif setting in {"enabled", "best_name"}:
            settings[setting] = not settings.get(setting, True)
        elif setting == "only_pings":
            settings[setting] = not settings.get(setting, False)
        else:
            await interaction.response.send_message(
                "This setting is not available.",
                ephemeral=True,
            )
            return
        self.cog.save_bot_state()
        self.rebuild()
        await interaction.response.edit_message(view=self)

    async def go_back(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran v!settings can use this menu.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            view=ServerSettingsView(
                interaction.user.id,
                cog=self.cog,
                guild_id=self.guild_id,
            )
        )


class ServerSettingsView(discord.ui.LayoutView):
    """Server settings section menu."""

    SECTIONS = (
        ("Naming", "Naming `On` · Mode `Assisted`"),
        (
            "Roles & Channels",
            "Configure ping roles and rare, regional, hunt, collection, "
            "reserve, and quest output.",
        ),
        ("Starboard", "Configure the main, shiny, and Vivillon starboards."),
        ("Modules", "Control server-level Profile Tracking and Analytics data collection."),
        ("Appearance", "Set the bot's server profile, banner, and embed color."),
    )

    def __init__(self, user_id: int, cog: "PokéTwoNamingBot | None" = None, guild_id: int | None = None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.cog = cog
        self.guild_id = guild_id
        container = discord.ui.Container()
        container.add_item(
            discord.ui.TextDisplay(
                "## Server Settings\n"
                "Pick a section to configure. Changes inside each section save immediately."
            )
        )
        container.add_item(discord.ui.Separator())
        for name, description in self.SECTIONS:
            if name == "Naming" and cog is not None and guild_id is not None:
                naming = (
                    cog.bot_state.get("guild_settings", {})
                    .get(str(guild_id), {})
                    .get("naming", {})
                )
                enabled = "On" if naming.get("enabled", True) else "Off"
                mode = (
                    "Assisted"
                    if naming.get("mode", "assisted") == "assisted"
                    else "Embed Mode"
                )
                description = f"Naming `{enabled}` · Mode `{mode}`"
            button = discord.ui.Button(label="Open", style=discord.ButtonStyle.primary)
            if name == "Naming" and cog is not None and guild_id is not None:
                button.callback = self.open_naming_settings
            elif name == "Roles & Channels" and cog is not None and guild_id is not None:
                button.callback = self.open_roles_channels_settings
            elif name == "Starboard" and cog is not None and guild_id is not None:
                button.callback = self.open_starboard_settings
            else:
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

    async def open_naming_settings(self, interaction: discord.Interaction):
        """Open the naming settings view."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran v!settings can open these settings.",
                ephemeral=True,
            )
            return
        if self.cog is None or self.guild_id is None:
            await interaction.response.send_message(
                "These settings can only be opened in a server.",
                ephemeral=True,
            )
            return
        view = NamingSettingsView(self.cog, interaction.user.id, self.guild_id)
        await interaction.response.edit_message(view=view)

    async def open_starboard_settings(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran v!settings can open these settings.",
                ephemeral=True,
            )
            return
        if self.cog is None or self.guild_id is None:
            await interaction.response.send_message(
                "These settings can only be opened in a server.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            view=StarboardSettingsView(self.cog, self.user_id, self.guild_id)
        )

    async def open_roles_channels_settings(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran v!settings can open these settings.",
                ephemeral=True,
            )
            return
        if self.cog is None or self.guild_id is None:
            await interaction.response.send_message(
                "These settings can only be opened in a server.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            view=RolesChannelsSettingsView(self.cog, self.user_id, self.guild_id)
        )

    async def placeholder(self, interaction: discord.Interaction):
        await interaction.response.defer()


class GrabEmojiModal(discord.ui.Modal, title="Custom Emoji"):
    """Collect an emoji to prepend to the grabbed reserve list."""

    emoji = discord.ui.TextInput(
        label="Emoji",
        placeholder="Paste an emoji or <:name:123456789>",
        required=False,
        max_length=100,
    )

    def __init__(self, grab_view):
        super().__init__()
        self.grab_view = grab_view
        self.emoji.default = grab_view.custom_emoji

    async def on_submit(self, interaction: discord.Interaction):
        await self.grab_view.set_custom_emoji(
            interaction,
            self.emoji.value,
        )


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
        self.custom_emoji = ""
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
            display_name = (
                f"all {pokemon_name}"
                if self.all_forms and requested_all_forms
                else pokemon_name
            )
            entries.append((user_id, display_name, False, custom_emoji))
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
        del custom_emoji
        prefix = f"{self.custom_emoji} " if self.custom_emoji else ""
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
        self.emoji_button.label = "Edit emoji" if self.custom_emoji else "Custom emoji"

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
        await self.open_custom_emoji_modal(interaction)

    async def open_custom_emoji_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(GrabEmojiModal(self))

    async def set_custom_emoji(
        self,
        interaction: discord.Interaction,
        emoji: str,
    ):
        self.custom_emoji = emoji.strip()
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

    @discord.ui.button(label="Readyup", style=discord.ButtonStyle.success)
    async def readyup_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "The ready-up queue can only be used inside a server.",
                ephemeral=True,
            )
            return
        user_ids = list(dict.fromkeys(user_id for user_id, *_ in self.entries))
        active_views = getattr(self.cog, "readyup_views", {})
        active_view = active_views.get(str(guild.id))
        if active_view is None or active_view.is_finished():
            added = self.cog.add_readyup_users(guild.id, user_ids)
        else:
            added = await active_view.add_users(user_ids)
        if added:
            message = f"Added **{len(added)}** user(s) to the ready-up queue."
        else:
            message = "Everyone in this list is already in the ready-up queue."
        await interaction.response.send_message(message, ephemeral=True)

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


class ReadyupView(discord.ui.View):
    """Track readiness for the users in one server's ready-up queue."""

    def __init__(
        self,
        cog,
        guild_id: int,
        author_id: int,
        user_ids: list[str],
    ):
        super().__init__(timeout=1800)
        self.cog = cog
        self.guild_id = str(guild_id)
        self.author_id = author_id
        self.user_ids = list(dict.fromkeys(str(user_id) for user_id in user_ids))
        self.ready_user_ids: set[str] = set()
        self.completed = False
        self.completion_notified = False
        self.ended = False
        self.message: discord.Message | None = None
        self.lock = asyncio.Lock()

    def build_embed(self) -> discord.Embed:
        all_ready = len(self.ready_user_ids) == len(self.user_ids)
        embed = discord.Embed(
            title="All Ready" if all_ready else "Ready Up",
            description=(
                "All users are ready!"
                if all_ready
                else "Click **Ready** when you are ready to start."
            ),
            color=discord.Color.green() if all_ready else discord.Color.orange(),
        )
        not_ready = [
            f"☐ <@{user_id}>"
            for user_id in self.user_ids
            if user_id not in self.ready_user_ids
        ]
        ready = [
            f"✅ <@{user_id}>"
            for user_id in self.user_ids
            if user_id in self.ready_user_ids
        ]
        embed.add_field(
            name="Not Ready",
            value="\n".join(not_ready) or "—",
            inline=False,
        )
        embed.add_field(
            name="Ready",
            value="\n".join(ready) or "—",
            inline=False,
        )
        return embed

    async def add_users(self, user_ids: list[str]) -> list[str]:
        async with self.lock:
            added = self.cog.add_readyup_users(self.guild_id, user_ids)
            if not added:
                return []
            self.user_ids.extend(added)
            self.completed = False
            self.completion_notified = False
            self.ready_button.disabled = False
            if self.message is not None:
                await self.message.edit(embed=self.build_embed(), view=self)
            return added

    @discord.ui.button(label="Ready", style=discord.ButtonStyle.success)
    async def ready_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        del button
        async with self.lock:
            active_views = getattr(self.cog, "readyup_views", {})
            if (
                self.ended
                or active_views.get(self.guild_id) is not self
            ):
                await interaction.response.send_message(
                    "This ready-up has ended or was cleared.",
                    ephemeral=True,
                )
                return
            if self.completed:
                await interaction.response.send_message(
                    "Everyone in this ready-up is already ready.",
                    ephemeral=True,
                )
                return
            user_id = str(interaction.user.id)
            if user_id not in self.user_ids:
                await interaction.response.send_message(
                    "You are not in this ready-up queue.",
                    ephemeral=True,
                )
                return
            if user_id in self.ready_user_ids:
                await interaction.response.send_message(
                    "You are already marked ready.",
                    ephemeral=True,
                )
                return

            self.ready_user_ids.add(user_id)
            all_ready = len(self.ready_user_ids) == len(self.user_ids)
            if all_ready:
                self.completed = True
                self.ready_button.disabled = True
            await interaction.response.edit_message(
                embed=self.build_embed(),
                view=self,
            )
            if all_ready and not self.completion_notified:
                self.completion_notified = True
                await interaction.followup.send(
                    f"<@{self.author_id}> everyone is ready its time to start the org.",
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
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
                else self.cog.resolve_pokemon_list(pokemon_name)[0]
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


class SlashDaycareContext:
    def __init__(self, interaction: discord.Interaction):
        self.guild = interaction.guild
        self.author = interaction.user
        self.interaction = interaction

    async def send(self, *args, **kwargs):
        return await self.interaction.followup.send(*args, **kwargs)


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
        self.image_download_times = deque(maxlen=100)
        self.message_send_times = deque(maxlen=100)
        self.spawn_metrics = deque(maxlen=100)
        self.spawn_preview_tasks: set[asyncio.Task[None]] = set()
        self.spawn_prediction_cache: OrderedDict[bytes, tuple[str, float]] = OrderedDict()
        self.store_times = deque(maxlen=100)
        self.last_spawn_metrics = None
        self.recognized_spawn_count = 0
        self.recent_spawn_times = {}
        self.class_names = {name.casefold(): name for name in self.recognizer.classes}
        self.pokemon_types = self.load_pokemon_types()
        self.pokemon_sprite_ids = self.load_pokemon_sprite_ids()
        self.pokemon_spawn_chances = self.load_pokemon_spawn_chances()
        self.pokemon_best_names = self.load_pokemon_best_names()
        self.pokemon_aliases = self.load_pokemon_aliases()
        self.pokemon_species = self.load_pokemon_species()
        self.reviewed_spawn_count = self.load_collected_training_count()
        self.bot_state = self.load_bot_state()
        self.ffa_requests_in_flight: set[tuple[int, str]] = set()
        self.starboard_service = StarboardService(self)
        self.readyup_views = {}
        self.breeding_box_service = BreedingBoxService(self, POKETWO_BOT_ID)
        self.dex_tracking_service = DexTrackingService(self, POKETWO_BOT_ID)
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

    def load_pokemon_spawn_chances(self):
        """Load the Pokétwo spawn odds keyed by case-insensitive Pokémon name."""
        with open("poketwo_spawn_chances.csv", newline="", encoding="utf-8-sig") as f:
            return {
                row["Pokemon"].strip().casefold(): row
                for row in csv.DictReader(f)
                if row["Pokemon"].strip()
            }

    def resolve_pokemon_name(self, name: str) -> str | None:
        """Resolve English, localized, or romanized Pokémon input."""
        stripped = name.strip()
        canonical = self.class_names.get(stripped.casefold())
        if canonical is not None:
            return canonical
        normalized = normalize_pokemon_alias(stripped)
        nidoran_genders = {
            "nidoranmale": "nidoran♂",
            "nidoranfemale": "nidoran",
        }
        if normalized in nidoran_genders:
            return self.class_names.get(nidoran_genders[normalized])
        return self.pokemon_aliases.get(normalized)

    def custom_sprite_url(self, pokemon_name: str) -> str | None:
        """Return the custom sprite URL for a Pokémon if available."""
        if os.path.basename(pokemon_name) != pokemon_name:
            return None
        filename = f"{pokemon_name}.png"
        if not os.path.isfile(os.path.join("pokemon_sprites", filename)):
            return None
        return f"{CUSTOM_SPRITE_BASE_URL}/{quote(filename)}"

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
        pokemon_species = getattr(self, "pokemon_species", {})
        species_id = pokemon_species.get(canonical)
        for class_name in self.class_names.values():
            class_normalized = normalize_pokemon_alias(class_name)
            matches_family = (
                pokemon_species.get(class_name) == species_id
                if species_id is not None
                else (
                    canonical_normalized in class_normalized
                    or class_name == canonical
                )
            )
            if canonical_normalized.startswith("nidoran"):
                matches_family = class_normalized.startswith("nidoran")
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
                dex_owners = dex_ping_owners(self, guild_id, pokemon_name)
                if dex_owners:
                    mentions = ", ".join(f"<@{user_id}>" for user_id in dex_owners)
                    content.append(f"Dex pings: {mentions}")
                type_pingers = self.type_ping_owners(pokemon_name, guild_id)
                if type_pingers:
                    mentions = ", ".join(
                        f"<@{user_id}>" for user_id in type_pingers
                    )
                    content.append(f"Type pings: {mentions}")
                quest_pingers = self.quest_ping_owners(pokemon_name, guild_id)
                if quest_pingers:
                    mentions = ", ".join(
                        f"<@{user_id}>" for user_id in quest_pingers
                    )
                    content.append(f"Quest pings: {mentions}")
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
        hunters = [
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
        return self.current_guild_member_ids(guild_id, hunters)

    def collection_owners_for_spawn(
        self,
        guild_id: int,
        pokemon_name: str,
    ) -> list[str]:
        """Return members collecting a spawned Pokémon who receive pings."""
        owners = [
            user_id
            for user_id, pokemon_names in self.bot_state.get(
                "collections",
                {},
            ).get(str(guild_id), {}).items()
            if pokemon_name in pokemon_names
            and self.pings_enabled(user_id, "collection")
        ]
        return self.current_guild_member_ids(guild_id, owners)

    def current_guild_member_ids(
        self,
        guild_id: int,
        user_ids: list[str],
    ) -> list[str]:
        """Drop stored user IDs that are no longer members of this server."""
        bot = getattr(self, "bot", None)
        if bot is None:
            return user_ids
        guild = bot.get_guild(int(guild_id))
        if guild is None:
            return user_ids
        get_member = getattr(guild, "get_member", None)
        if not callable(get_member):
            return user_ids
        return [
            user_id
            for user_id in user_ids
            if get_member(int(user_id)) is not None
        ]

    def pings_enabled(self, user_id, kind: str) -> bool:
        """Return whether a user receives pings of this kind (default: yes)."""
        muted = self.bot_state.get("afk", {}).get(str(user_id), {})
        return not muted.get(kind, False)

    def type_ping_types(
        self,
        user_id: int,
        guild_id: int | None = None,
    ) -> list[str]:
        """Return the valid Pokémon types selected by one user."""
        settings = self.bot_state.get("type_pings", {})
        if guild_id is None:
            selected = settings.get(str(user_id), [])
        else:
            selected = settings.get(str(guild_id), {}).get(
                str(user_id),
                settings.get(str(user_id), []),
            )
        if not isinstance(selected, list):
            return []
        return [pokemon_type for pokemon_type in TYPE_NAMES if pokemon_type in selected]

    def type_ping_owners(
        self,
        pokemon_name: str,
        guild_id: int | None = None,
    ) -> list[str]:
        """Return users who selected at least one type of this Pokémon."""
        pokemon_types = set(self.pokemon_types[pokemon_name])
        settings = self.bot_state.get("type_pings", {})
        if guild_id is None:
            selections = settings
        else:
            selections = settings.get(str(guild_id), {})
            legacy = {
                user_id: selected
                for user_id, selected in settings.items()
                if str(user_id).isdigit() and isinstance(selected, list)
            }
            selections = {**legacy, **selections}
        owners = [
            user_id
            for user_id, selected in selections.items()
            if isinstance(selected, list)
            and any(pokemon_type in selected for pokemon_type in pokemon_types)
            and self.pings_enabled(user_id, "typeping")
        ]
        if guild_id is None:
            return owners
        return self.current_guild_member_ids(guild_id, owners)

    def quest_ping_regions(
        self,
        user_id: int,
        guild_id: int | None = None,
    ) -> list[str]:
        """Return the regions selected by one user for quest pings."""
        settings = self.bot_state.get("quest_pings", {})
        if guild_id is None:
            selected = settings.get(str(user_id), [])
        else:
            selected = settings.get(str(guild_id), {}).get(
                str(user_id),
                settings.get(str(user_id), []),
            )
        if not isinstance(selected, list):
            return []
        return [region for region in REGIONS if region in selected]

    def quest_ping_owners(
        self,
        pokemon_name: str,
        guild_id: int | None = None,
    ) -> list[str]:
        """Return users who selected regions for quest pings of this Pokémon."""
        pokemon_regions = self._get_pokemon_regions(pokemon_name)
        settings = self.bot_state.get("quest_pings", {})
        if guild_id is None:
            selections = settings
        else:
            selections = settings.get(str(guild_id), {})
            legacy = {
                user_id: selected
                for user_id, selected in settings.items()
                if str(user_id).isdigit() and isinstance(selected, list)
            }
            selections = {**legacy, **selections}
        owners = [
            user_id
            for user_id, selected in selections.items()
            if isinstance(selected, list)
            and any(region in selected for region in pokemon_regions)
            and self.pings_enabled(user_id, "questping")
        ]
        if guild_id is None:
            return owners
        return self.current_guild_member_ids(guild_id, owners)

    def _get_pokemon_regions(self, pokemon_name: str) -> list[str]:
        """Return the species' origin and applicable form or quest categories."""
        species_id = self.pokemon_species[pokemon_name]
        if species_id == "MissingNo":
            return []
        if not isinstance(species_id, int):
            raise ValueError(f"Invalid species ID for {pokemon_name}: {species_id!r}")

        regions = [
            region
            for first, last, region in QUEST_ORIGIN_RANGES
            if first <= species_id <= last
        ]
        if not regions:
            logging.getLogger(__name__).warning(
                "No quest-ping origin region for %s (species ID %s)",
                pokemon_name,
                species_id,
            )
        for region, prefix in REGIONS.items():
            if prefix and pokemon_name.startswith(prefix) and region not in regions:
                regions.append(region)
        if pokemon_name in PALDEAN_TAUROS_FORMS and "Paldea" not in regions:
            regions.append("Paldea")
        if (
            1011 <= species_id <= 1017
            or pokemon_name == "Bloodmoon Ursaluna"
            or species_id == 1025
        ):
            regions.append("Kitakami")
        if species_id in PARADOX_SPECIES_IDS:
            regions.append("Paradox")
        return regions

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

    def readyup_user_ids(self, guild_id) -> list[str]:
        """Return the unique users queued for a server's ready-up."""
        queues = self.bot_state.setdefault("readyup_queues", {})
        user_ids = queues.get(str(guild_id), [])
        if not isinstance(user_ids, list):
            raise ValueError(f"Ready-up queue for server {guild_id} is invalid")
        return list(dict.fromkeys(str(user_id) for user_id in user_ids))

    def add_readyup_users(self, guild_id, user_ids: list[str]) -> list[str]:
        """Append new users to a server's ready-up queue without duplicates."""
        queues = self.bot_state.setdefault("readyup_queues", {})
        guild_key = str(guild_id)
        current = self.readyup_user_ids(guild_key)
        added = [
            user_id
            for user_id in dict.fromkeys(str(value) for value in user_ids)
            if user_id not in current
        ]
        if not added:
            return []
        had_queue = guild_key in queues
        previous_queue = queues.get(guild_key)
        queues[guild_key] = current + added
        try:
            self.save_bot_state()
        except OSError:
            if had_queue:
                queues[guild_key] = previous_queue
            else:
                queues.pop(guild_key, None)
            raise
        return added

    def clear_readyup_users(self, guild_id) -> int:
        """Remove every queued user for one server."""
        queues = self.bot_state.setdefault("readyup_queues", {})
        guild_key = str(guild_id)
        current = self.readyup_user_ids(guild_key)
        if not current:
            queues.pop(guild_key, None)
            return 0
        previous_queue = queues.pop(guild_key)
        try:
            self.save_bot_state()
        except OSError:
            queues[guild_key] = previous_queue
            raise
        return len(current)

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
        for message_id, request in self.bot_state.get("ffa_requests", {}).items():
            if request["status"] in ("pending", "sending"):
                self.bot.add_view(FFAReviewView(self), message_id=int(message_id))
        for message_id, release in self.bot_state.get("ffa_releases", {}).items():
            self.bot.add_view(
                FFAReserveView(
                    self, release["guild_id"], release["guild_name"],
                    release["user_id"], release["pokemon"],
                ),
                message_id=int(message_id),
            )
        connector = aiohttp.TCPConnector(
            limit=20,
            ttl_dns_cache=300,
            keepalive_timeout=60,
        )
        self.http_session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(
                total=8,
                connect=2,
                sock_read=4,
            ),
        )

    async def cog_unload(self):
        """Close shared resources."""
        for task in self.spawn_preview_tasks:
            task.cancel()
        if self.spawn_preview_tasks:
            await asyncio.gather(*self.spawn_preview_tasks, return_exceptions=True)
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
            "incense_auto_pause": {},
            "incense_purchases": {},
            "reserves": {},
            "ffa_requests": {},
            "ffa_releases": {},
            "active_incenses": {},
            "shiny_hunts": {},
            "collections": {},
            "type_pings": {},
            "quest_pings": {},
            "categories": {},
            "afk": {},
            "breeding_boxes": {},
            "daycare_settings": {},
            "readyup_queues": {},
            "last_update_announcement": "",
            "automatic_update_announcement": "",
            "automatic_update_pending_message": None,
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
        state.setdefault("incense_auto_pause", {})
        state.setdefault("incense_purchases", {})
        state.setdefault("reserves", {})
        state.setdefault("ffa_requests", {})
        state.setdefault("ffa_releases", {})
        state.setdefault("active_incenses", {})
        state.setdefault("shiny_hunts", {})
        state.setdefault("collections", {})
        state.setdefault("type_pings", {})
        state.setdefault("quest_pings", {})
        state.setdefault("categories", {})
        state.setdefault("afk", {})
        state.setdefault("breeding_boxes", {})
        state.setdefault("daycare_settings", {})
        state.setdefault("readyup_queues", {})
        state.setdefault("last_update_announcement", "")
        state.setdefault("automatic_update_announcement", "")
        state.setdefault("automatic_update_pending_message", None)
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

    def breeding_user_boxes(self, guild_id: int, user_id: int) -> dict:
        """Return one user's globally available breeding boxes."""
        return self.breeding_box_service.user_boxes(guild_id, user_id)

    def resolve_breeding_box(
        self,
        guild_id: int,
        user_id: int,
        selector: str,
    ) -> tuple[str | None, dict | None]:
        """Resolve a box name or 1-based box number."""
        boxes = self.breeding_user_boxes(guild_id, user_id)
        if not boxes:
            return None, None
        if selector.isdigit():
            names = sorted(boxes, key=str.casefold)
            index = int(selector) - 1
            if 0 <= index < len(names):
                name = names[index]
                return name, boxes[name]
        name = next(
            (key for key in boxes if key.casefold() == selector.casefold()),
            None,
        )
        return (name, boxes[name]) if name is not None else (None, None)

    def breeding_box_item_count(self, box: dict) -> int:
        """Count individual stored Pokémon entries in a box."""
        items = box.get("items", [])
        return len(items) if isinstance(items, list) else 0

    async def breeding_box_message_items(self, ctx) -> list[str]:
        """Read Pokémon names from the replied-to Pokétwo list."""
        if ctx.message.reference is None:
            return []
        source = ctx.message.reference.resolved
        if source is None:
            try:
                source = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return []
        text = "\n".join(
            [
                source.content or "",
                *(embed.title or "" for embed in source.embeds),
                *(embed.description or "" for embed in source.embeds),
            ]
        )
        names = []
        for line in text.splitlines():
            for reported_name in sorted(
                self.report_pokemon_names(),
                key=len,
                reverse=True,
            ):
                pattern = rf"(?<![\w]){re.escape(reported_name)}(?![\w])"
                if re.search(pattern, line, re.IGNORECASE):
                    resolved = self.resolve_pokemon_name(reported_name)
                    if resolved:
                        names.append(resolved)
                    break
        return list(dict.fromkeys(names))

    async def manage_breeding_box(self, ctx, action: str, argument: str):
        """Perform destructive and tag operations on personal breeding boxes."""
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        boxes = self.breeding_user_boxes(guild_id, user_id)
        parts = argument.split()
        if not parts:
            await ctx.send(
                f"Usage: `v!box {action} <box>`"
                + (" <pokemon>" if action in {"remove", "tag", "untag"} else "")
            )
            return

        box_name, box = self.resolve_breeding_box(guild_id, user_id, parts[0])
        if box is None:
            await ctx.send(f"❌ Breeding box `{parts[0]}` was not found.")
            return
        if box_name is None:
            await ctx.send("❌ Breeding box lookup failed.")
            return

        if action == "rename":
            if len(parts) < 2:
                await ctx.send("Usage: `v!box rename <box> <new name>`")
                return
            new_name = " ".join(parts[1:]).strip()[:100]
            if not new_name:
                await ctx.send("Usage: `v!box rename <box> <new name>`")
                return
            if new_name.casefold() != box_name.casefold() and any(
                name.casefold() == new_name.casefold() for name in boxes
            ):
                await ctx.send(f"❌ A box named **{new_name}** already exists.")
                return
            boxes[new_name] = boxes.pop(box_name)
            self.save_bot_state()
            await ctx.send(f"✅ Renamed **{box_name}** to **{new_name}**.")
            return

        if action == "delete":
            boxes.pop(box_name, None)
            self.save_bot_state()
            await ctx.send(f"✅ Deleted breeding box **{box_name}**.")
            return

        if action == "clear":
            box["items"] = []
            self.save_bot_state()
            await ctx.send(f"✅ Cleared breeding box **{box_name}**.")
            return

        if action == "remove":
            if len(parts) < 2:
                await ctx.send("Usage: `v!box remove <box> <pokemon>`")
                return
            pokemon_input = " ".join(parts[1:])
            pokemon_name = self.resolve_pokemon_name(pokemon_input)
            if pokemon_name is None:
                await ctx.send(f"❌ Unknown Pokémon: `{pokemon_input}`")
                return
            original_count = len(box["items"])
            box["items"] = [
                item for item in box["items"]
                if not (isinstance(item, dict) and item.get("name") == pokemon_name)
            ]
            removed = original_count - len(box["items"])
            self.save_bot_state()
            await ctx.send(
                f"✅ Removed **{removed}** {pokemon_name} entry/entries."
                if removed
                else f"{pokemon_name} is not in **{box_name}**."
            )
            return

        if action == "transfer":
            if len(parts) < 3:
                await ctx.send(
                    "Usage: `v!box transfer <from> <to> <pokemon>`"
                )
                return
            destination_name, destination = self.resolve_breeding_box(
                guild_id,
                user_id,
                parts[1],
            )
            if destination is None:
                await ctx.send(f"❌ Breeding box `{parts[1]}` was not found.")
                return
            pokemon_name = self.resolve_pokemon_name(" ".join(parts[2:]))
            if pokemon_name is None:
                await ctx.send(f"❌ Unknown Pokémon: `{' '.join(parts[2:])}`")
                return
            index = next(
                (
                    index for index, item in enumerate(box["items"])
                    if isinstance(item, dict) and item.get("name") == pokemon_name
                ),
                None,
            )
            if index is None:
                await ctx.send(f"{pokemon_name} is not in **{box_name}**.")
                return
            if self.breeding_box_item_count(destination) >= BREEDING_BOX_LIMIT:
                await ctx.send(f"❌ Breeding box **{destination_name}** is full.")
                return
            destination.setdefault("items", []).append(box["items"].pop(index))
            self.save_bot_state()
            await ctx.send(
                f"✅ Transferred **{pokemon_name}** from **{box_name}** "
                f"to **{destination_name}**."
            )
            return

        if action in {"tag", "untag"}:
            if len(parts) < 2:
                await ctx.send(f"Usage: `v!box {action} <box> <pokemon> [tag]`")
                return
            pokemon_input = " ".join(parts[1:-1]) if action == "tag" and len(parts) > 2 else " ".join(parts[1:])
            tag = parts[-1] if action == "tag" and len(parts) > 2 else ""
            pokemon_name = self.resolve_pokemon_name(pokemon_input)
            if pokemon_name is None:
                await ctx.send(f"❌ Unknown Pokémon: `{pokemon_input}`")
                return
            item = next(
                (
                    item for item in box["items"]
                    if isinstance(item, dict) and item.get("name") == pokemon_name
                ),
                None,
            )
            if item is None:
                await ctx.send(f"{pokemon_name} is not in **{box_name}**.")
                return
            tags = set(item.setdefault("tags", []))
            if action == "tag":
                if not tag:
                    await ctx.send("Usage: `v!box tag <box> <pokemon> <tag>`")
                    return
                tags.add(tag)
                item["tags"] = sorted(tags, key=str.casefold)
                self.save_bot_state()
                await ctx.send(f"✅ Tagged **{pokemon_name}** as `{tag}`.")
            else:
                if not tags:
                    await ctx.send(f"{pokemon_name} has no tags.")
                    return
                item["tags"] = []
                self.save_bot_state()
                await ctx.send(f"✅ Removed tags from **{pokemon_name}**.")

    async def legacy_breeding_box_command(self, ctx, entry: str = ""):
        """Retained for migration compatibility with pre-v!box box state."""
        if ctx.guild is None:
            await ctx.send("Breeding boxes can only be used inside a server.")
            return

        text = entry.strip()
        parts = text.split(maxsplit=1)
        subcommand = parts[0].casefold() if parts else ""
        argument = parts[1].strip() if len(parts) > 1 else ""
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        boxes = self.breeding_user_boxes(guild_id, user_id)

        if subcommand in {"", "list"}:
            if subcommand == "list" and not argument:
                pass
            if not boxes:
                await ctx.send(
                    "You have no breeding boxes yet. Create one with "
                    "`v!box <box name>`."
                )
                return
            lines = []
            for index, (name, box) in enumerate(
                sorted(boxes.items(), key=lambda item: item[0].casefold()),
                start=1,
            ):
                count = self.breeding_box_item_count(box)
                lines.append(
                    f"{index}. **{name}** — {count}/{BREEDING_BOX_LIMIT}"
                )
            await ctx.send(
                embed=discord.Embed(
                    title=f"{ctx.author.display_name}'s Breeding Boxes",
                    description="\n".join(lines),
                    color=discord.Color.green(),
                )
            )
            return

        if subcommand == "help":
            await ctx.send(
                "**Breeding box commands**\n"
                "`v!box` — list boxes\n"
                "`v!box create <name>` — create a box\n"
                "Reply to a Pokétwo list with `v!box append [box] [--c]`\n"
                "`v!box remove <box> <name>` — remove Pokémon\n"
                "`v!box transfer <from> <to> <name>` — move Pokémon\n"
                "`v!box copy <source> <new name>` — copy a box\n"
                "`v!box tag <box> <name> <tag>` / `v!box untag <box> <name>`\n"
                "`v!box tags` / `v!box tagged <tag>`\n"
                "`v!box rename <box> <new name>` / `v!box delete <box>`\n"
                "`v!box clear <box>` / `v!box reset`\n"
                "`v!dc [box]` / `v!dc menu` / `v!boxhelp`"
            )
            return

        if subcommand in {"rename", "delete", "clear", "remove", "transfer", "tag", "untag"}:
            await self.manage_breeding_box(ctx, subcommand, argument)
            return

        if subcommand == "tags":
            tags = sorted(
                {
                    str(tag)
                    for box in boxes.values()
                    for item in box.get("items", [])
                    if isinstance(item, dict)
                    for tag in item.get("tags", [])
                },
                key=str.casefold,
            )
            await ctx.send(
                "No tags yet." if not tags else
                "Tags: " + ", ".join(f"`{tag}`" for tag in tags)
            )
            return

        if subcommand == "tagged":
            tag = argument.casefold()
            matches = []
            for box_name, box in boxes.items():
                for item in box.get("items", []):
                    if isinstance(item, dict) and tag in {
                        str(value).casefold() for value in item.get("tags", [])
                    }:
                        matches.append(f"**{item['name']}** ({box_name})")
            await ctx.send(
                "\n".join(dict.fromkeys(matches))
                if matches
                else f"No Pokémon are tagged `{argument}`."
            )
            return

        if subcommand == "daycare":
            if text == "daycare":
                await ctx.send(
                    "Daycare preferences are available as part of pair selection "
                    "from `v!dc [box]`."
                )
                return

        if ctx.message.reference is not None:
            copy_only = "--c" in text.casefold().split()
            selector = text.replace("--c", "", 1).strip() if copy_only else text
            box_name, box = (
                self.resolve_breeding_box(guild_id, user_id, selector)
                if selector
                else (None, None)
            )
            if selector and box is None:
                await ctx.send(f"❌ Breeding box `{selector}` was not found.")
                return
            if box is None:
                box_name = "Box 1"
                box = boxes.setdefault(
                    box_name,
                    {"items": []},
                )
            items = await self.breeding_box_message_items(ctx)
            if not items:
                await ctx.send(
                    "No recognized Pokémon were found in the replied-to list."
                )
                return
            available = BREEDING_BOX_LIMIT - self.breeding_box_item_count(box)
            if available <= 0:
                await ctx.send(f"❌ Breeding box **{box_name}** is full.")
                return
            added = []
            stored_items = box.setdefault("items", [])
            for pokemon_name in items[:available]:
                stored_items.append({"name": pokemon_name, "tags": []})
                added.append(pokemon_name)
            self.save_bot_state()
            names = ", ".join(dict.fromkeys(added))
            await ctx.send(
                f"✅ Stored {len(added)} Pokémon in **{box_name}**: {names}"
                + ("." if copy_only is False else ".")
            )
            return

        if subcommand == "create":
            argument = argument or ""
        if not subcommand and argument:
            subcommand = ""

        box_name, box = self.resolve_breeding_box(guild_id, user_id, text)
        if box is not None:
            items = sorted(
                (
                    item["name"]
                    for item in box.get("items", [])
                    if isinstance(item, dict) and item.get("name")
                ),
                key=str.casefold,
            )
            if not items:
                await ctx.send(f"Box **{box_name}** is empty.")
                return
            species = {}
            for item in items:
                canonical = self.resolve_pokemon_name(item)
                key = (
                    self.pokemon_species.get(canonical)
                    if canonical
                    else None
                )
                if key is not None:
                    species.setdefault(str(key), []).append(canonical)
            pairs = []
            for names in species.values():
                names = sorted(set(names), key=str.casefold)
                if len(names) >= 2:
                    pairs.append(f"`@Pokétwo#8236 daycare {names[0].lower()} {names[1].lower()}`")
            await ctx.send(
                embed=discord.Embed(
                    title=f"{box_name} — Breedable Pairs",
                    description=(
                        "\n".join(pairs[:20])
                        if pairs
                        else "No two matching stored species were found."
                    ),
                    color=discord.Color.green(),
                )
            )
            return

        box_name = text[:100].strip()
        if not box_name:
            await ctx.send("Usage: `v!box <box name>`")
            return
        if box_name.casefold() in {name.casefold() for name in boxes}:
            await ctx.send(f"❌ A breeding box named **{box_name}** already exists.")
            return
        boxes[box_name] = {"items": []}
        self.save_bot_state()
        await ctx.send(f"✅ Created breeding box **{box_name}**.")

    async def breeding_box_command(
        self,
        ctx,
        command: str,
        entry: str = "",
    ):
        """Route the v!box, v!dc, and v!boxhelp command families."""
        await self.breeding_box_service.dispatch(ctx, command, entry)

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
        if ctx.guild is None:
            return False
        if self.is_administrator(ctx):
            return True
        role_ids = self.restricted_role_ids(ctx.guild.id)
        return any(role.id in role_ids for role in ctx.author.roles)

    def incense_auto_pause_enabled(self, guild_id: int) -> bool:
        """Return whether confirmed incense purchases auto-pause in a server."""
        return self.bot_state["incense_auto_pause"].get(str(guild_id), True)

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
        chunks = re.split(r"\s*(?:\||—|–|\n|;|/|,|\s-\s*)\s*", text)
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
            all_forms_match = re.search(
                r"^(?:all\s+|all\s+forms?\s+)|"
                r"\s+(?:all|all\s+forms?)$",
                value,
                flags=re.IGNORECASE,
            )
            requested_all_forms = all_forms_match is not None
            if all_forms_match is not None:
                value = (
                    value[: all_forms_match.start()]
                    + value[all_forms_match.end() :]
                ).strip()
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
        entries: list[tuple[str, str, bool, bool, str]] = []
        for line in text.splitlines():
            mentions = list(re.finditer(r"<@!?(\d+)>", line))
            previous_segment_assigned = False
            for index, mention in enumerate(mentions):
                category_key = None
                category_emoji = ""
                prefix_start = (
                    mentions[index - 1].end() if index > 0 else 0
                )
                prefix = (
                    "" if previous_segment_assigned
                    else line[prefix_start : mention.start()]
                )
                end = (
                    mentions[index + 1].start()
                    if index + 1 < len(mentions)
                    else len(line)
                )
                following_pokemon = self.pokemon_names_from_grab_segment(
                    line[mention.end() : end]
                )
                if guild_id is not None:
                    prefix_segments = re.split(
                        r"\s*(?:\||—|–|;|/|,|\s-\s)\s*",
                        prefix,
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
                elif not (
                    following_pokemon
                    and re.fullmatch(
                        r"\s*\*{0,2}booster(?:\s+\d+)?\*{0,2}"
                        r"\s*[-–—:]\s*",
                        prefix,
                        flags=re.IGNORECASE,
                    )
                ):
                    pokemon_names = self.pokemon_names_from_grab_segment(
                        prefix
                    )
                    for pokemon_name, requested_all_forms, custom_emoji in (
                        pokemon_names
                    ):
                        entry = (
                            mention.group(1),
                            str(pokemon_name),
                            requested_all_forms,
                            False,
                            custom_emoji,
                        )
                        if entry not in entries:
                            entries.append(entry)
                previous_segment_assigned = bool(following_pokemon)
                for pokemon_name, requested_all_forms, custom_emoji in following_pokemon:
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
    async def on_guild_join(self, guild):
        """Introduce naming and support in an accessible server channel."""
        welcome = discord.Embed(
            title="Welcome to Vivillon",
            description=(
                "Thank you for inviting Vivillon to your server! I'm grateful "
                "to be here.\n\n"
                "Vivillon identifies Pokétwo spawns and shows their names to help "
                "you catch them.\n\n"
                "Use `v!help` to see what all of my commands do.\n\n"
                "To enable naming in your server, join the "
                "[Butterfly Garden main server](https://discord.gg/butterflygarden) "
                "and open a ticket. If you have any issues or questions, you can "
                "also open a ticket there for help."
            ),
        )
        support_embed, support_view = self.build_support_message()
        channels = list(guild.text_channels)
        if guild.system_channel is not None:
            channels = [guild.system_channel] + [
                channel for channel in channels if channel != guild.system_channel
            ]
        if guild.me is None:
            print(
                f"Could not send welcome message in guild {guild.id}: "
                "bot member unavailable."
            )
            return
        for channel in channels:
            permissions = channel.permissions_for(guild.me)
            if not (
                permissions.view_channel
                and permissions.send_messages
                and permissions.embed_links
            ):
                continue
            try:
                await channel.send(embeds=[welcome, support_embed], view=support_view)
                return
            except discord.HTTPException as error:
                print(
                    f"Could not send welcome message in channel {channel.id}: {error}"
                )
        print(
            f"Could not send welcome message in guild {guild.id}: "
            "no usable text channel."
        )

    def clear_member_server_data(self, guild_id: int, user_id: int) -> bool:
        """Clear one member's server-specific hunt, collection, and ping data."""
        guild_key = str(guild_id)
        user_key = str(user_id)
        changed = False
        for state_key in (
            "shiny_hunts", "collections", "type_pings", "quest_pings", "dex_tracking"
        ):
            settings = self.bot_state.setdefault(state_key, {})
            guild_settings = settings.get(guild_key)
            if isinstance(guild_settings, dict) and user_key in guild_settings:
                if state_key == "dex_tracking":
                    self.dex_tracking_service.cancel_sessions(guild_id, user_id)
                guild_settings.pop(user_key)
                changed = True

            legacy = settings.get(user_key)
            if state_key in {"type_pings", "quest_pings"} and isinstance(legacy, list):
                for guild in self.bot.guilds:
                    if guild.id == guild_id:
                        continue
                    get_member = getattr(guild, "get_member", None)
                    if not callable(get_member) or get_member(user_id) is None:
                        continue
                    settings.setdefault(str(guild.id), {}).setdefault(
                        user_key,
                        list(legacy),
                    )
                settings.pop(user_key)
                changed = True
        if changed:
            self.save_bot_state()
        return changed

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Clear server-specific member data after a leave or ban."""
        self.clear_member_server_data(member.guild.id, member.id)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Clear server-specific member data when a ban is reported."""
        self.clear_member_server_data(guild.id, user.id)

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
            remove_caught_dex_entry(self, message)
            self.track_incense(message)
            await self.maybe_pause_after_incense_purchase(message)
            if message.guild and self.bot_state.get("guild_settings", {}).get(
                str(message.guild.id), {}
            ).get("starboard"):
                await self.starboard_service.handle(message)
            if message.guild and self.premium_tier(message.guild.id) is None:
                return
            if self.naming_channel_disabled(message):
                return
            if self.is_spawn_message(message) and self.channel_within_incense_capacity(
                message
            ):
                await self.handle_poketwo_spawn(message)

    def naming_channel_disabled(self, message) -> bool:
        """Return whether Vivillon naming is disabled in this message's channel."""
        if message.guild is None:
            return False
        roles_channels = (
            self.bot_state.get("guild_settings", {})
            .get(str(message.guild.id), {})
            .get("roles_channels", {})
        )
        disabled_channels = roles_channels.get("disabled_naming_channels", [])
        if not isinstance(disabled_channels, list):
            return False
        return str(message.channel.id) in {
            str(channel_id) for channel_id in disabled_channels
        }

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        """Follow edited Pokétwo list pages, even if the message is uncached."""
        if {"content", "embeds", "components"}.intersection(payload.data):
            await self.breeding_box_service.handle_list_edit(payload.message)
            await self.dex_tracking_service.handle_list_edit(payload.message)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Update incense state when Pokétwo edits a status/countdown embed."""
        del before
        if after.author.id == self.bot.user.id:
            return
        if after.author.id == POKETWO_BOT_ID:
            self.track_incense(after)
            await self.maybe_pause_after_incense_purchase(after)
            if after.guild and self.bot_state.get("guild_settings", {}).get(
                str(after.guild.id), {}
            ).get("starboard"):
                await self.starboard_service.handle(after)

    @staticmethod
    def is_incense_purchase_confirmation(message) -> bool:
        """Return whether a Pokétwo message confirms that incense was bought."""
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
        return any(
            re.search(pattern, text) is not None
            for pattern in (
                r"\bincense\s+has\s+been\s+bought\b",
                r"\byou\s+purchased\s+an?\s+incense\s+for\s+\d+\s+shards?\b",
            )
        )

    async def maybe_pause_after_incense_purchase(self, message):
        """Pause Pokétwo after a confirmed incense purchase unless disabled."""
        if message.guild is None or not self.is_incense_purchase_confirmation(message):
            return
        purchases = self.bot_state["incense_purchases"].setdefault(
            str(message.guild.id), {}
        )
        channel_key = str(message.channel.id)
        purchased_at = message.created_at.timestamp()
        if purchased_at > purchases.get(channel_key, 0):
            purchases[channel_key] = purchased_at
            self.save_bot_state()
        if not self.incense_auto_pause_enabled(message.guild.id):
            return
        try:
            paused = await self.pause_poketwo_channel(
                message.channel,
                reason="Pokétwo confirmed an incense purchase",
            )
        except discord.HTTPException as error:
            print(
                f"Could not automatically pause Pokétwo in channel "
                f"{message.channel.id}: {error}"
            )
            paused = False
        if not paused:
            await message.channel.send(
                "❌ I could not automatically pause Pokétwo. "
                "Please check that I have **Manage Channels** permission "
                "and that Pokétwo is still in this server."
            )
            return
        await message.channel.send(
            "✅ Pokétwo has been paused in this channel after the incense purchase. "
            "Use `v!resume` to resume it."
        )

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
            pokemon_name, confidence, inference_seconds = (
                await self.recognize_cached_spawn_image(image_data)
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
        thumbnail_url = None
        thumbnail_file = None
        defer_prediction_preview = False
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
            dex_owners = []
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
                dex_owners = dex_ping_owners(self, message.guild.id, pokemon_name)
            embed.set_image(url="attachment://spawn-review.webp")
            with Image.open(BytesIO(image_data)) as image:
                review_buffer = BytesIO()
                image.convert("RGB").save(
                    review_buffer,
                    format="WEBP",
                    quality=85,
                )
            review_buffer.seek(0)
            send_kwargs = {
                "embed": embed,
                "file": discord.File(review_buffer, filename="spawn-review.webp"),
                "view": SpawnReviewView(self, pokemon_name, image_data),
            }
            if dex_owners:
                send_kwargs["content"] = "Dex pings: " + ", ".join(
                    f"<@{user_id}>" for user_id in dex_owners
                )
        else:
            defer_prediction_preview = True
            content, embed = self.format_spawn_prediction(
                pokemon_name,
                confidence,
                message.guild.id if message.guild else None,
                shiny_hunters,
            )
            custom_sprite = self.custom_sprite_url(pokemon_name)
            if custom_sprite is not None:
                thumbnail_url = custom_sprite
            elif pokemon_name in CUSTOM_SPRITE_IDENTIFIERS:
                thumbnail_url = self.spawn_image_url(message)
                if thumbnail_url is None:
                    thumbnail_buffer = BytesIO()
                    with Image.open(BytesIO(image_data)) as image:
                        image.convert("RGB").save(
                            thumbnail_buffer,
                            format="WEBP",
                            quality=85,
                        )
                    thumbnail_buffer.seek(0)
                    thumbnail_file = discord.File(
                        thumbnail_buffer,
                        filename="pokemon.webp",
                    )
            else:
                sprite_id = self.pokemon_sprite_ids.get(pokemon_name)
                if sprite_id is not None:
                    thumbnail_url = (
                        "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                        "sprites/pokemon/other/official-artwork/"
                        f"{sprite_id}.png"
                    )
            send_kwargs = {"content": content}

        send_started = perf_counter()
        response_message = await message.channel.send(**send_kwargs)
        send_seconds = perf_counter() - send_started
        if defer_prediction_preview:
            preview_embed = embed.copy()
            if thumbnail_url is not None or thumbnail_file is not None:
                preview_embed.set_thumbnail(
                    url=thumbnail_url or "attachment://pokemon.webp"
                )
            task = asyncio.create_task(
                self.update_spawn_preview(
                    response_message,
                    preview_embed,
                    thumbnail_file,
                )
            )
            self.spawn_preview_tasks.add(task)
            task.add_done_callback(self.spawn_preview_tasks.discard)
            task.add_done_callback(self.report_spawn_preview_error)

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
        self.image_download_times.append(download_seconds)
        self.message_send_times.append(send_seconds)
        self.last_spawn_metrics = {
            "download": download_seconds,
            "inference": inference_seconds,
            "send": send_seconds,
            "total": total_seconds,
        }
        self.spawn_metrics.append(self.last_spawn_metrics)
        self.recognized_spawn_count += 1

    @staticmethod
    def report_spawn_preview_error(task: asyncio.Task[None]) -> None:
        """Report unexpected failures from deferred preview updates."""
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            print(f"Could not update spawn prediction preview: {error}")

    @staticmethod
    async def update_spawn_preview(
        message,
        embed: discord.Embed,
        thumbnail_file: discord.File | None,
    ) -> None:
        """Add the full preview after the naming response has been posted."""
        try:
            if thumbnail_file is None:
                await message.edit(embed=embed)
            else:
                await message.edit(embed=embed, attachments=[thumbnail_file])
        except discord.HTTPException as error:
            print(f"Could not update spawn prediction preview: {error}")

    async def recognize_cached_spawn_image(
        self, image_data: bytes
    ) -> tuple[str, float, float]:
        """Reuse predictions only for byte-identical spawn images."""
        started = perf_counter()
        image_hash = sha256(image_data).digest()
        cached = self.spawn_prediction_cache.get(image_hash)
        if cached is not None:
            self.spawn_prediction_cache.move_to_end(image_hash)
            return cached[0], cached[1], perf_counter() - started
        pokemon_name, confidence, inference_seconds = await asyncio.to_thread(
            self.recognize_spawn_image, image_data
        )
        self.spawn_prediction_cache[image_hash] = (pokemon_name, confidence)
        self.spawn_prediction_cache.move_to_end(image_hash)
        if len(self.spawn_prediction_cache) > 1024:
            self.spawn_prediction_cache.popitem(last=False)
        return pokemon_name, confidence, inference_seconds

    def recognize_spawn_image(self, image_data: bytes):
        """Recognize an image without blocking the Discord event loop."""
        with Image.open(BytesIO(image_data)) as image:
            return self.recognizer.recognize(image)

    @staticmethod
    def spawn_image_url(message):
        """Return the original Discord URL for a spawn image."""
        for attachment in getattr(message, "attachments", []):
            if (attachment.content_type or "").startswith("image/"):
                return attachment.url

        for embed in getattr(message, "embeds", []):
            if embed.image and embed.image.url:
                return embed.image.url
            if embed.thumbnail and embed.thumbnail.url:
                return embed.thumbnail.url
        return None

    async def _get_spawn_image(self, message):
        """Return the spawn image bytes and download duration."""
        started = perf_counter()
        for attachment in message.attachments:
            if (attachment.content_type or "").startswith("image/"):
                optimized_url = self.optimized_spawn_image_url(attachment)
                if optimized_url is not None and getattr(
                    self, "http_session", None
                ) is not None:
                    downloads = {
                        asyncio.create_task(
                            self._read_spawn_image_url(optimized_url)
                        ),
                        asyncio.create_task(attachment.read(use_cached=True)),
                    }
                    image_data = await self.first_spawn_download(downloads)
                    if image_data is not None:
                        return image_data, perf_counter() - started
                else:
                    try:
                        image_data = await attachment.read(use_cached=True)
                        return image_data, perf_counter() - started
                    except discord.HTTPException as error:
                        print(
                            "Could not download Pokétwo spawn image from Discord's "
                            f"cached media URL; retrying the original URL: {error}"
                        )
                try:
                    image_data = await attachment.read()
                except discord.HTTPException as error:
                    print(
                        "Could not download Pokétwo spawn image from Discord's "
                        f"original URL: {error}"
                    )
                    return None, perf_counter() - started
                return image_data, perf_counter() - started

        image_url = self.spawn_image_url(message)
        if image_url is None:
            return None, perf_counter() - started

        if self.http_session is None:
            raise RuntimeError("Pokétwo image HTTP session is not initialized")

        image_urls = {image_url}
        for embed in getattr(message, "embeds", []):
            for image in (embed.image, embed.thumbnail):
                if image and image.url == image_url:
                    proxy_url = getattr(image, "proxy_url", None)
                    if proxy_url:
                        image_urls.add(proxy_url)
                    break
            else:
                continue
            break
        downloads = {
            asyncio.create_task(self._read_spawn_image_with_retry(url))
            for url in image_urls
        }
        image_data = await self.first_spawn_download(downloads)
        return image_data, perf_counter() - started

    @staticmethod
    def optimized_spawn_image_url(attachment) -> str | None:
        """Request a proxy image no larger than the recognizer's input."""
        proxy_url = getattr(attachment, "proxy_url", None)
        if not proxy_url:
            return None
        parts = urlsplit(proxy_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(
            {
                "width": str(SPAWN_DOWNLOAD_SIZE),
                "height": str(SPAWN_DOWNLOAD_SIZE),
                "format": "webp",
            }
        )
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    async def _read_spawn_image_url(self, image_url: str) -> bytes:
        """Download one spawn image URL."""
        if self.http_session is None:
            raise RuntimeError("Pokétwo image HTTP session is not initialized")
        async with self.http_session.get(image_url) as response:
            response.raise_for_status()
            return await response.read()

    async def _read_spawn_image_with_retry(self, image_url: str) -> bytes:
        """Retry one transient failure when fetching an embedded image."""
        try:
            return await self._read_spawn_image_url(image_url)
        except aiohttp.ClientResponseError as error:
            if not 500 <= error.status < 600:
                raise
        except (aiohttp.ClientConnectionError, TimeoutError):
            pass
        await asyncio.sleep(0.25)
        return await self._read_spawn_image_url(image_url)

    @staticmethod
    async def first_spawn_download(
        downloads: set[asyncio.Task[bytes]],
    ) -> bytes | None:
        """Return the first successful image download and cancel slower requests."""
        errors = []
        try:
            pending = set(downloads)
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    try:
                        image_data = task.result()
                    except (
                        aiohttp.ClientError,
                        discord.HTTPException,
                        TimeoutError,
                    ) as error:
                        errors.append(error)
                    else:
                        return image_data
            if errors:
                print(
                    "Could not download Pokétwo spawn image from Discord's "
                    f"fast media URLs: {errors[-1]}"
                )
            return None
        finally:
            for download in downloads:
                download.cancel()
            await asyncio.gather(*downloads, return_exceptions=True)

    async def pause_missingno_channel(self, channel):
        """Deny only Pokétwo permission to send in a MissingNo channel."""
        return await self.pause_poketwo_channel(
            channel,
            reason="MissingNo spawned; waiting for staff to resume",
        )

    async def pause_poketwo_channel(self, channel, reason: str) -> bool:
        """Deny Pokétwo permission to send in a channel and save its prior overwrite."""
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
            reason=reason,
        )
        return True

    @commands.command(name="settings")
    async def settings(self, ctx):
        """Show the server settings menu."""
        guild_id = ctx.guild.id if ctx.guild else None
        await ctx.send(view=ServerSettingsView(ctx.author.id, cog=self, guild_id=guild_id))

    @commands.command(name="announce", hidden=True)
    async def announce_update(self, ctx):
        """Post the update announcement immediately (staff only)."""
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You don't have permission.")
            return
        
        from announcements import post_update_announcement
        try:
            result = await post_update_announcement(self.bot, self)
            if result:
                await ctx.send("✅ Announcement posted successfully")
            else:
                await ctx.send("ℹ️ Announcement unchanged from last post")
        except Exception as e:
            await ctx.send(f"❌ Error posting announcement: {e}")

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
        """Create an empty Pokémon category. Restricted."""
        if ctx.guild is None:
            await ctx.send("Categories can only be managed inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You don't have permission to create categories.")
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
        """Add Pokémon to an existing category. Restricted."""
        if ctx.guild is None:
            await ctx.send("Categories can only be managed inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You don't have permission to modify categories.")
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

    @commands.command(name="category")
    async def category_command(self, ctx, action: str = "", *, name: str = ""):
        """Manage categories: v!category remove <name>. Restricted."""
        if ctx.guild is None:
            await ctx.send("Categories can only be managed inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You don't have permission to manage categories.")
            return
        if action.lower() != "remove" or not name.strip():
            await ctx.send("Usage: `v!category remove <name>`")
            return
        key = self.find_category(ctx.guild.id, name.strip())
        if key is None:
            await ctx.send(f"❌ Category **{name}** doesn't exist.")
            return
        self.guild_categories(ctx.guild.id).pop(key)
        self.save_bot_state()
        await ctx.send(f"✅ Deleted category **{key}**.")

    def report_pokemon_names(self) -> list[str]:
        """Return Pokémon names usable when reading catch and naming-bot messages."""
        names = set(self.class_names.values())
        names.update(
            row["Pokemon"]
            for row in self.pokemon_spawn_chances.values()
            if row.get("Pokemon")
        )
        names.update(EVENT_FORM_PRICES)
        for guild_categories in self.bot_state.get("categories", {}).values():
            for members in guild_categories.values():
                names.update(str(name) for name in members)
        return sorted(names, key=len, reverse=True)

    def report_pokemon_from_first_line(self, line: str) -> str | None:
        """Resolve a naming-bot message's leading Pokémon name."""
        first_line = re.sub(r"^[\s>*`_~]+", "", line).strip()
        for name in self.report_pokemon_names():
            if not first_line.casefold().startswith(name.casefold()):
                continue
            if len(first_line) == len(name) or not first_line[len(name)].isalnum():
                return name
        return None

    def report_message_lines(self, message) -> list[str]:
        """Flatten message and embed text while preserving its first-line order."""
        lines: list[str] = []
        lines.extend((message.content or "").splitlines())
        for embed in message.embeds:
            lines.extend((embed.title or "").splitlines())
            lines.extend((embed.description or "").splitlines())
            for field in embed.fields:
                lines.extend(
                    f"{field.name}: {field.value}".splitlines()
                )
        return lines

    def report_naming_bot_evidence(self, message) -> tuple[str, set[str]] | None:
        """Read a Pokémon and reserve mentions from a naming-bot reply."""
        lines = self.report_message_lines(message)
        first_line = next((line.strip() for line in lines if line.strip()), "")
        pokemon_name = self.report_pokemon_from_first_line(first_line)
        if pokemon_name is None:
            return None

        reserved_user_ids = set()
        for line in lines:
            reserve_line = re.match(
                r"^\s*(?:reserve\s+pings|reserved)\s*:\s*(.*)$",
                line,
                flags=re.IGNORECASE,
            )
            if reserve_line is not None:
                reserved_user_ids.update(
                    re.findall(r"<@!?(\d+)>", reserve_line.group(1))
                )
        if not reserved_user_ids:
            return None
        return pokemon_name, reserved_user_ids

    def report_species_id(self, pokemon_name: str) -> int | str | None:
        """Return a Pokémon's species identifier, including event forms."""
        species_id = getattr(self, "pokemon_species", {}).get(pokemon_name)
        if species_id is not None:
            return species_id
        spawn_data = self.pokemon_spawn_chances.get(pokemon_name.casefold())
        if spawn_data is not None:
            return int(spawn_data["Dex"])
        base_name = next(
            (
                base
                for form, base in EVENT_FORM_BASES.items()
                if form.casefold() == pokemon_name.casefold()
            ),
            None,
        )
        if base_name is not None:
            base_data = self.pokemon_spawn_chances.get(base_name.casefold())
            if base_data is not None:
                return int(base_data["Dex"])
        return None

    def report_species_has_custom_forms(self, pokemon_name: str) -> bool:
        """Return whether the named species has known custom or regional forms."""
        species_id = self.report_species_id(pokemon_name)
        if species_id is None:
            return False
        if any(
            form.casefold() != pokemon_name.casefold()
            and self.report_species_id(form) == species_id
            for form in self.class_names.values()
        ):
            return True
        return pokemon_name.casefold() in {
            "applin",
            "meowscarada",
            "simipour",
            "reuniclus",
        }

    def report_name_is_species_base(self, pokemon_name: str) -> bool:
        """Return whether a caught name identifies only the base species."""
        if any(
            form.casefold() == pokemon_name.casefold()
            for form in EVENT_FORM_BASES
        ):
            return False
        spawn_data = self.pokemon_spawn_chances.get(pokemon_name.casefold())
        if spawn_data is not None:
            return spawn_data["Pokemon"].casefold() == pokemon_name.casefold()
        species_id = self.report_species_id(pokemon_name)
        if species_id is None:
            return False
        return any(
            int(row["Dex"]) == species_id
            and row["Pokemon"].casefold() == pokemon_name.casefold()
            for row in self.pokemon_spawn_chances.values()
        )

    def same_report_species(self, first: str, second: str) -> bool:
        """Compare two reported Pokémon names by their Pokédex species."""
        if first.casefold() == second.casefold():
            return True
        first_id = self.report_species_id(first)
        return first_id is not None and first_id == self.report_species_id(second)

    def report_pokemon_from_catch(self, catch_message) -> tuple[str, str] | None:
        """Extract a catcher ID and Pokémon name from a Pokétwo catch message."""
        text = "\n".join(self.report_message_lines(catch_message))
        caught_match = re.search(r"\bcaught\b", text, flags=re.IGNORECASE)
        if caught_match is None:
            return None
        catcher_mentions = re.findall(
            r"<@!?(\d+)>",
            text[: caught_match.start()],
        )
        if not catcher_mentions:
            return None

        caught_text = text[caught_match.end() :]
        for name in self.report_pokemon_names():
            if re.search(
                rf"(?<![\w]){re.escape(name)}(?![\w])",
                caught_text,
                flags=re.IGNORECASE,
            ):
                return catcher_mentions[-1], name
        return None

    async def referenced_message(self, ctx, reference):
        """Resolve a Discord message reference from cache or channel history."""
        if reference is None:
            return None
        resolved = getattr(reference, "resolved", None)
        if resolved is not None and hasattr(resolved, "id"):
            return resolved
        message_id = getattr(reference, "message_id", None)
        if message_id is None:
            return None
        return await ctx.channel.fetch_message(message_id)

    async def referenced_spawn_message(self, ctx, catch_message):
        """Follow a catch's reference chain until its Pokétwo spawn is found.

        Pokétwo can edit a spawn after it has been caught, removing the text
        that identifies it as a spawn. The message's position in the reply
        chain is therefore the reliable signal here.
        """
        reference = getattr(catch_message, "reference", None)
        seen_message_ids = set()
        for _ in range(5):
            message = await self.referenced_message(ctx, reference)
            if message is None or message.id in seen_message_ids:
                return None
            seen_message_ids.add(message.id)
            if message.author.id == POKETWO_BOT_ID:
                return message
            reference = getattr(message, "reference", None)
        return None

    async def report_spawn_evidence(self, channel, spawn, catch_message) -> list:
        """Collect other bots' reserve evidence replying to one Pokétwo spawn."""
        evidence = []
        async for message in channel.history(
            limit=500,
            after=spawn,
            before=catch_message,
            oldest_first=True,
        ):
            reference = getattr(message, "reference", None)
            if getattr(reference, "message_id", None) != spawn.id:
                continue
            author = getattr(message, "author", None)
            if (
                author is None
                or not getattr(author, "bot", False)
                or author.id == self.bot.user.id
            ):
                continue
            parsed = self.report_naming_bot_evidence(message)
            if parsed is not None:
                evidence.append(parsed)
        return evidence

    def spawn_rate_report_price(self, pokemon_name: str) -> int | None:
        """Interpolate the reported spawn-rate tiers in 2,500-PC increments."""
        spawn_data = self.pokemon_spawn_chances.get(pokemon_name.casefold())
        if spawn_data is None:
            species_id = self.report_species_id(pokemon_name)
            if species_id is not None:
                spawn_data = next(
                    (
                        row
                        for row in self.pokemon_spawn_chances.values()
                        if int(row["Dex"]) == species_id
                    ),
                    None,
                )
        if spawn_data is None:
            return None
        denominator_match = re.fullmatch(r"\s*1\s*/\s*(\d+)\s*", spawn_data["Chance"])
        if denominator_match is None:
            return None
        denominator = int(denominator_match.group(1))
        if denominator <= SPAWN_RATE_PRICES[0][0]:
            return SPAWN_RATE_PRICES[0][1]
        for (lower_rate, lower_price), (upper_rate, upper_price) in zip(
            SPAWN_RATE_PRICES,
            SPAWN_RATE_PRICES[1:],
        ):
            if denominator <= upper_rate:
                interpolated_price = lower_price + (
                    (denominator - lower_rate)
                    * (upper_price - lower_price)
                    / (upper_rate - lower_rate)
                )
                return int((interpolated_price + 1_250) // 2_500) * 2_500
        return SPAWN_RATE_PRICES[-1][1]

    def reserve_report_price(
        self,
        guild_id: int,
        pokemon_name: str,
        catch_text: str,
    ) -> int | None:
        """Use fixed category/form prices before the calculated spawn-rate price."""
        spawn_rate_price = self.spawn_rate_report_price(pokemon_name)
        if spawn_rate_price is None:
            return None
        fixed_prices = [
            price
            for category, members in self.guild_categories(guild_id).items()
            if category.casefold() in RESERVE_CATEGORY_PRICES
            and any(
                str(member).casefold() == pokemon_name.casefold()
                for member in members
            )
            for price in (RESERVE_CATEGORY_PRICES[category.casefold()],)
        ]
        event_form_price = next(
            (
                price
                for form, price in EVENT_FORM_PRICES.items()
                if form.casefold() == pokemon_name.casefold()
            ),
            None,
        )
        if event_form_price is not None:
            fixed_prices.append(event_form_price)
        if re.search(r"\bgigantamax\b", f"{pokemon_name} {catch_text}", re.IGNORECASE):
            fixed_prices.append(35_000)
        return max(fixed_prices) if fixed_prices else spawn_rate_price

    @commands.command(name="report")
    async def report_stolen_reserve(self, ctx):
        """Report a stolen reserve by replying to a Pokétwo catch announcement."""
        if ctx.guild is None:
            await ctx.send("❌ Reports can only be submitted inside a server.")
            return
        try:
            catch_message = await self.referenced_message(
                ctx,
                getattr(ctx.message, "reference", None),
            )
        except discord.NotFound:
            catch_message = None
        except discord.Forbidden:
            await ctx.send(
                "❌ I need permission to read the catch channel's message history."
            )
            return
        except discord.HTTPException as error:
            print(f"Could not fetch the replied-to catch for a report: {error}")
            await ctx.send("❌ I could not read that catch announcement.")
            return
        if (
            catch_message is None
            or catch_message.author.id != POKETWO_BOT_ID
            or not re.search(
                r"\bcaught\b",
                "\n".join(self.report_message_lines(catch_message)),
                flags=re.IGNORECASE,
            )
        ):
            await ctx.send(
                "Reply to a Pokétwo catch announcement with `v!report`."
            )
            return

        caught = self.report_pokemon_from_catch(catch_message)
        if caught is None:
            await ctx.send("❌ I could not identify the catcher and Pokémon.")
            return
        catcher_id, pokemon_name = caught
        if catcher_id == str(ctx.author.id):
            await ctx.send("❌ You cannot report your own catch.")
            return

        try:
            spawn_message = await self.referenced_spawn_message(ctx, catch_message)
        except discord.NotFound:
            spawn_message = None
        except discord.Forbidden:
            await ctx.send(
                "❌ I need permission to read the catch channel's message history."
            )
            return
        except discord.HTTPException as error:
            print(f"Could not fetch the related Pokétwo spawn: {error}")
            await ctx.send("❌ I could not read the spawn for that catch.")
            return
        evidence = []
        try:
            if spawn_message is not None:
                evidence = await self.report_spawn_evidence(
                    ctx.channel,
                    spawn_message,
                    catch_message,
                )
        except discord.Forbidden:
            await ctx.send(
                "❌ I need permission to read the catch channel's message history."
            )
            return
        except discord.HTTPException as error:
            print(f"Could not read naming-bot reserve evidence: {error}")
            await ctx.send("❌ I could not read reserve evidence for that spawn.")
            return

        catch_text = "\n".join(self.report_message_lines(catch_message))
        form_unverified = False
        if (
            self.report_species_has_custom_forms(pokemon_name)
            and self.report_name_is_species_base(pokemon_name)
            and not re.search(r"\bgigantamax\b", catch_text, re.IGNORECASE)
        ):
            identified_forms = {
                name.casefold(): name
                for name, _user_ids in evidence
                if self.same_report_species(name, pokemon_name)
            }
            if len(identified_forms) > 1:
                await ctx.send(
                    "❌ I could not identify one matching form from naming-bot "
                    "replies; no report was sent."
                )
                return
            if identified_forms:
                pokemon_name = next(iter(identified_forms.values()))
            else:
                form_unverified = True

        reporter_id = str(ctx.author.id)
        reserved_user_ids = set(
            self.reserve_user_ids(ctx.guild.id, pokemon_name)
        )
        for name, user_ids in evidence:
            if name.casefold() == pokemon_name.casefold():
                reserved_user_ids.update(user_ids)
        if reporter_id not in reserved_user_ids:
            await ctx.send(
                "❌ You need a current Vivillon reserve or a reserve ping on "
                "the linked spawn from another naming bot to report this catch."
            )
            return
        if catcher_id in reserved_user_ids:
            await ctx.send(
                "❌ The catcher also has this Pokémon reserved; no report was sent."
            )
            return

        price = self.reserve_report_price(
            ctx.guild.id,
            pokemon_name,
            catch_text,
        )
        if price is None:
            await ctx.send(
                "❌ I could not find a spawn rate for this Pokémon; no report was sent."
            )
            return

        report_channel = self.bot.get_channel(RESERVE_REPORT_CHANNEL_ID)
        try:
            if report_channel is None:
                report_channel = await self.bot.fetch_channel(
                    RESERVE_REPORT_CHANNEL_ID
                )
            catch_link = (
                f"https://discord.com/channels/{ctx.guild.id}/"
                f"{catch_message.channel.id}/{catch_message.id}"
            )
            note_text = (
                "\nThe catch's form could not be verified."
                if form_unverified
                else ""
            )
            await report_channel.send(
                f"<@{catcher_id}> hey you stole a reserved Pokémon\n"
                f"Pokémon: {pokemon_name}\n"
                f"PC: {price:,} PC\n"
                f"<@{catcher_id}> trade <@{reporter_id}> "
                f"in <#{RESERVE_TRADE_THREAD_ID}>\n"
                f"Go to catch: {catch_link}{note_text}",
                allowed_mentions=discord.AllowedMentions(
                    users=[
                        discord.Object(id=int(catcher_id)),
                        discord.Object(id=int(reporter_id)),
                    ],
                    roles=False,
                    everyone=False,
                ),
            )
        except discord.Forbidden:
            await ctx.send(
                "❌ I need permission to send messages in the reserve report channel."
            )
            return
        except discord.NotFound:
            await ctx.send("❌ The reserve report channel could not be found.")
            return
        except discord.HTTPException as error:
            print(f"Could not send stolen-reserve report: {error}")
            await ctx.send("❌ I could not send the report; check the bot logs.")
            return
        await ctx.send("✅ Your stolen-reserve report was submitted.")

    @report_stolen_reserve.error
    async def report_stolen_reserve_error(self, ctx, error):
        """Make unexpected report failures visible to the user and in logs."""
        logging.getLogger(__name__).error(
            "Stolen-reserve report failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        await ctx.send("❌ The report could not be completed. Check the bot logs.")

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check if the bot is responsive"""
        await ctx.send(f"Pong! {self.bot.latency * 1000:.2f}ms")

    def update_ping_selections(
        self,
        user_id,
        guild_id,
        add_names,
        remove_names,
        valid_names,
        current,
        state_key,
        label,
    ) -> str | None:
        if not add_names and not remove_names:
            return None
        lookup = {name.casefold(): name for name in valid_names}
        invalid = [
            name for name in (*add_names, *remove_names)
            if name.casefold() not in lookup
        ]
        if invalid:
            return (
                f"❌ Unknown {label}: {discord.utils.escape_mentions(', '.join(invalid))}. "
                f"Valid options: {', '.join(valid_names)}."
            )
        added = {lookup[name.casefold()] for name in add_names}
        removed = {lookup[name.casefold()] for name in remove_names}
        if added & removed:
            return "❌ You cannot add and remove the same option at once."
        selected = [name for name in current if name not in removed] + list(added)
        try:
            save_ping_selection(self, state_key, user_id, selected, guild_id)
        except OSError:
            logging.getLogger(__name__).exception("Could not save %s settings", label)
            return f"❌ I couldn't save your {label} settings. Check the bot logs."
        return None

    async def prefix_ping_command(
        self, ctx, names, valid_names, current, state_key, label, view_type
    ):
        guild = getattr(ctx, "guild", None)
        if hasattr(ctx, "guild") and guild is None:
            await ctx.send(f"❌ {label.title()} settings can only be managed in a server.")
            return
        remove = bool(names) and names[0].casefold() == "remove"
        if remove and len(names) == 1:
            await ctx.send(f"❌ Specify at least one {label} option to remove.")
            return
        error = self.update_ping_selections(
            ctx.author.id, guild.id if guild is not None else None,
            () if remove else names, names[1:] if remove else (),
            valid_names, current, state_key, label,
        )
        if error:
            await ctx.send(error)
            return
        view = view_type(
            self,
            ctx.author.id,
            guild.id if guild is not None else None,
        )
        await ctx.send(embed=view.build_embed(), view=view)

    @commands.command(name="typeping", aliases=["tp"])
    async def type_ping_command(self, ctx, *types: str):
        """Choose Pokémon types to receive pings for."""
        await self.prefix_ping_command(
            ctx,
            types,
            TYPE_NAMES,
            self.type_ping_types(
                ctx.author.id,
                getattr(getattr(ctx, "guild", None), "id", None),
            ),
            "type_pings", "type-ping", TypePingView,
        )

    @commands.command(name="questping", aliases=["qp"])
    async def quest_ping_command(self, ctx, *regions: str):
        """Choose regions to receive quest pings for."""
        await self.prefix_ping_command(
            ctx,
            regions,
            REGIONS,
            self.quest_ping_regions(
                ctx.author.id,
                getattr(getattr(ctx, "guild", None), "id", None),
            ),
            "quest_pings", "quest-ping", QuestPingView,
        )

    async def slash_ping_command(
        self, interaction, add, remove, valid_names, current, state_key, label, view_type
    ):
        guild_id = getattr(interaction, "guild_id", None)
        if hasattr(interaction, "guild_id") and guild_id is None:
            await interaction.response.send_message(
                f"❌ {label.title()} settings can only be managed in a server.",
                ephemeral=True,
            )
            return
        for action, value in (("add", add), ("remove", remove)):
            if value is not None and not value.strip():
                await interaction.response.send_message(
                    f"❌ Specify at least one {label} option to {action}.",
                    ephemeral=True,
                )
                return
        error = self.update_ping_selections(
            interaction.user.id, guild_id,
            add.split() if add is not None else (),
            remove.split() if remove is not None else (),
            valid_names, current, state_key, label,
        )
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        view = view_type(self, interaction.user.id, guild_id)
        await interaction.response.send_message(
            embed=view.build_embed(), view=view, ephemeral=True,
        )

    @app_commands.command(name="tp", description="Manage Pokémon type pings")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        add="Types to add, separated by spaces",
        remove="Types to remove, separated by spaces",
    )
    async def slash_type_ping(
        self,
        interaction: discord.Interaction,
        add: str | None = None,
        remove: str | None = None,
    ):
        await self.slash_ping_command(
            interaction, add, remove, TYPE_NAMES,
            self.type_ping_types(
                interaction.user.id,
                getattr(interaction, "guild_id", None),
            ),
            "type_pings", "type-ping", TypePingView,
        )

    @app_commands.command(name="qp", description="Manage quest-ping regions")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        add="Regions to add, separated by spaces",
        remove="Regions to remove, separated by spaces",
    )
    async def slash_quest_ping(
        self,
        interaction: discord.Interaction,
        add: str | None = None,
        remove: str | None = None,
    ):
        await self.slash_ping_command(
            interaction, add, remove, REGIONS,
            self.quest_ping_regions(
                interaction.user.id,
                getattr(interaction, "guild_id", None),
            ),
            "quest_pings", "quest-ping", QuestPingView,
        )

    @commands.command(name="sr")
    async def spawn_rate_command(self, ctx, *, pokemon_name: str = ""):
        """Show a Pokémon's Pokétwo spawn rate and artwork."""
        pokemon_input = pokemon_name.strip()
        if not pokemon_input:
            await ctx.send("Usage: `v!sr <pokemon>`")
            return

        spawn_data = self.pokemon_spawn_chances.get(pokemon_input.casefold())
        if spawn_data is None:
            resolved_name = self.resolve_pokemon_name(pokemon_input)
            if resolved_name is not None:
                spawn_data = self.pokemon_spawn_chances.get(
                    resolved_name.casefold()
                )
        if spawn_data is None:
            await ctx.send(f"❌ Unknown Pokémon: `{pokemon_input}`")
            return

        pokemon_name = spawn_data["Pokemon"]
        embed = discord.Embed(
            title=pokemon_name,
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Spawn rate",
            value=(
                f"{spawn_data['Chance']} "
                f"({spawn_data['Chance percentage']})"
            ),
            inline=False,
        )
        sprite_id = self.pokemon_sprite_ids.get(pokemon_name, spawn_data["Dex"])
        embed.set_thumbnail(
            url=(
                "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                "sprites/pokemon/other/official-artwork/"
                f"{sprite_id}.png"
            )
        )
        await ctx.send(embed=embed)

    @staticmethod
    def build_support_message():
        """Build the support embed and its donation button."""
        embed = discord.Embed(
            title="Support Vivillon",
            description=(
                "🦋 Running and developing Vivillon costs money. Donations are "
                "completely optional, but every bit of support helps keep the bot "
                "running. Thank you!"
            ),
        )
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="Donate on GoFundMe",
                url="https://gofund.me/40e29e0bf",
                style=discord.ButtonStyle.link,
            )
        )
        return embed, view

    @commands.command(name="support")
    async def support(self, ctx):
        """Show the optional GoFundMe support link."""
        embed, view = self.build_support_message()
        await ctx.reply(embed=embed, view=view)

    @commands.command(name="tz")
    async def timezone_command(self, ctx, *, phase: str = ""):
        """Find one place currently experiencing the requested local-time phase."""
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to use this command.")
            return
        phase = phase.strip().casefold()
        if phase not in TIMEZONE_PHASE_EMOJIS:
            await ctx.send("Use `v!tz day`, `v!tz night`, `v!tz dawn`, or `v!tz dusk`.")
            return

        place = find_place_for_phase(phase)
        if place is None:
            await ctx.send(f"I couldn't find a place currently experiencing {phase}.")
            return

        await ctx.send(
            f"It is {phase} in **{place}**.\n"
            f"Copy: `<@{POKETWO_BOT_ID}> tz {place}` "
            f"{TIMEZONE_PHASE_EMOJIS[phase]}"
        )

        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return

        role = ctx.guild.get_role(TIMEZONE_ROLE_ID)
        if role is None:
            print(f"[TZ] Role {TIMEZONE_ROLE_ID} not found in guild {ctx.guild.id}")
            return

        try:
            print(f"[TZ] Adding role to {ctx.author} ({ctx.author.id})")
            await ctx.author.add_roles(role)
            print(f"[TZ] Role added, waiting 5 seconds...")
            await asyncio.sleep(5)
            print(f"[TZ] Removing role from {ctx.author}")
            await ctx.author.remove_roles(role)
            print(f"[TZ] Role removed")
        except discord.Forbidden as e:
            print(f"[TZ] Permission denied: {e}")
            await ctx.send(f"❌ Bot doesn't have permission to manage roles: {e}")
        except Exception as e:
            print(f"[TZ] Error: {type(e).__name__}: {e}")
            await ctx.send(f"❌ Error managing role: {e}")

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
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to view premium servers.")
            return
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

    async def restore_poketwo_channel(self, channel) -> str:
        """Restore Pokétwo's saved channel permissions."""
        saved = self.bot_state["paused_channels"].get(str(channel.id))
        if saved is None:
            return "not_paused"
        if not channel.permissions_for(channel.guild.me).manage_channels:
            return "missing_permissions"
        poketwo = channel.guild.get_member(POKETWO_BOT_ID)
        if poketwo is None:
            try:
                poketwo = await channel.guild.fetch_member(POKETWO_BOT_ID)
            except discord.NotFound:
                return "poketwo_missing"

        if saved["existed"]:
            previous = discord.PermissionOverwrite.from_pair(
                discord.Permissions(int(saved["allow"])),
                discord.Permissions(int(saved["deny"])),
            )
            await channel.set_permissions(
                poketwo,
                overwrite=previous,
                reason="Staff resumed Pokétwo",
            )
        else:
            await channel.set_permissions(
                poketwo,
                overwrite=None,
                reason="Staff resumed Pokétwo",
            )
        del self.bot_state["paused_channels"][str(channel.id)]
        self.save_bot_state()
        return "resumed"

    @commands.command(name="resume")
    async def resume_poketwo_channel(self, ctx):
        """Restore Pokétwo's previous permissions in the current channel."""
        if ctx.guild is None:
            await ctx.send("This command can only be used inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to resume this channel.")
            return
        result = await self.restore_poketwo_channel(ctx.channel)
        if result == "not_paused":
            await ctx.send("This channel is not paused by me.")
            return
        if result == "missing_permissions":
            await ctx.send("❌ I need **Manage Channels** permission to resume it.")
            return
        if result == "poketwo_missing":
            await ctx.send("❌ Pokétwo is no longer in this server.")
            return
        await ctx.send("✅ Channel resumed. Pokétwo can send messages again.")

    @commands.command(name="pause", aliases=["p"])
    async def pause_poketwo_channel_command(self, ctx, *, target: str = ""):
        """Pause the current channel or recently purchased incense channels."""
        if ctx.guild is None:
            await ctx.send("This command can only be used inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to pause this channel.")
            return
        if target.strip().casefold() == "all":
            await self.pause_recent_incense_channels(ctx)
            return
        if target.strip():
            await ctx.send("Usage: `v!p` or `v!p all`")
            return
        if not await self.pause_poketwo_channel(
            ctx.channel,
            reason="Staff paused Pokétwo",
        ):
            await ctx.send(
                "❌ I could not pause Pokétwo. Check that I have **Manage Channels** "
                "permission and that Pokétwo is still in this server."
            )
            return
        await ctx.send("✅ Channel paused. Pokétwo can no longer send messages here.")

    async def pause_recent_incense_channels(self, ctx):
        """Pause channels with confirmed purchases in the last 10 hours."""
        now = time()
        purchases = self.bot_state["incense_purchases"].get(str(ctx.guild.id), {})
        recent_channel_ids = [
            channel_id
            for channel_id, purchased_at in purchases.items()
            if 0 <= now - purchased_at <= INCENSE_PURCHASE_PAUSE_WINDOW_SECONDS
        ]
        if not recent_channel_ids:
            await ctx.send("There are no tracked incense purchases in the last 10 hours.")
            return

        paused = 0
        failed = 0
        for channel_id in recent_channel_ids:
            channel = ctx.guild.get_channel(int(channel_id))
            if channel is None:
                failed += 1
                continue
            try:
                success = await self.pause_poketwo_channel(
                    channel, reason="Staff paused recently purchased incense channels"
                )
            except discord.HTTPException as error:
                print(f"Could not pause Pokétwo in channel {channel_id}: {error}")
                success = False
            if success:
                paused += 1
            else:
                failed += 1
        if failed:
            await ctx.send(
                f"✅ Paused Pokétwo in {paused} channel(s). ❌ Could not pause "
                f"{failed}; check that the channels still exist, I have "
                "**Manage Channels** permission, and Pokétwo is still in the server."
            )
        else:
            await ctx.send(f"✅ Paused Pokétwo in {paused} channel(s).")

    @commands.command(name="poff")
    async def disable_incense_auto_pause(self, ctx):
        """Disable automatic channel pausing after confirmed incense purchases."""
        await self.set_incense_auto_pause(ctx, enabled=False)

    @commands.command(name="pon")
    async def enable_incense_auto_pause(self, ctx):
        """Enable automatic channel pausing after confirmed incense purchases."""
        await self.set_incense_auto_pause(ctx, enabled=True)

    async def set_incense_auto_pause(self, ctx, *, enabled: bool):
        """Set the current server's restricted incense auto-pause preference."""
        if ctx.guild is None:
            await ctx.send("This command can only be used inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send(
                "❌ You do not have permission to change incense auto-pause."
            )
            return
        self.bot_state["incense_auto_pause"][str(ctx.guild.id)] = enabled
        self.save_bot_state()
        state = "enabled" if enabled else "disabled"
        await ctx.send(
            f"✅ Automatic pausing after confirmed incense purchases is {state} "
            "for this server."
        )

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
        elif action == "all":
            if remainder:
                await ctx.send("Usage: `v!r all`")
                return
            await self.resume_all_poketwo_channels(ctx)
        elif not action_entry:
            await ctx.send(
                "Use `v!r list [@user]` / `v!reserve list [@user]`, "
                "`v!r add <pokemon,...> <@user> [<@user2> ...]`, "
                "`v!r remove <pokemon,...|category> [@user]`, "
                "`v!r search <pokemon|category>`, `v!r clear`, or `v!r all`."
            )
        else:
            await ctx.send(
                "Unknown reservation action. Use `add`, `remove`, `search`, "
                "`list`, `clear`, or `all`."
            )

    async def resume_all_poketwo_channels(self, ctx):
        """Resume all channels tracked as paused in the current server."""
        if ctx.guild is None:
            await ctx.send("This command can only be used inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to resume all channels.")
            return
        guild_channels = {str(channel.id): channel for channel in ctx.guild.channels}
        paused_channels = [
            guild_channels[channel_id]
            for channel_id in self.bot_state["paused_channels"]
            if channel_id in guild_channels
        ]
        if not paused_channels:
            await ctx.send("There are no tracked paused channels in this server.")
            return

        resumed = 0
        failed = 0
        for channel in paused_channels:
            result = await self.restore_poketwo_channel(channel)
            if result == "resumed":
                resumed += 1
            else:
                failed += 1
        if failed:
            await ctx.send(
                f"✅ Resumed {resumed} channel(s). ❌ Could not resume {failed}; "
                "check my **Manage Channels** permission and that Pokétwo is "
                "still in the server."
            )
        else:
            await ctx.send(f"✅ Resumed Pokétwo in {resumed} channel(s).")

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
                    for family_member in self.resolve_pokemon_family(pokemon_name)
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
        """Reserve a Pokémon for one or more members. Restricted command."""
        if ctx.guild is None:
            await ctx.send("Reservations can only be managed inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to add reserves.")
            return

        # Extract all user mentions from the end of the entry
        user_matches = list(re.finditer(r"<@!?(\d+)>", entry))
        if not user_matches:
            await ctx.send("Usage: `v!r add <pokémon name> <@user> [<@user2> ...]`")
            return
        
        # Get all user IDs from matches
        user_ids = [int(match.group(1)) for match in user_matches]
        
        # Remove all user mentions from input to get pokemon part
        pokemon_input = entry
        for match in reversed(user_matches):
            pokemon_input = pokemon_input[:match.start()] + pokemon_input[match.end():]
        pokemon_input = pokemon_input.strip()
        
        if not pokemon_input:
            await ctx.send("Usage: `v!r add <pokémon name> <@user> [<@user2> ...]`")
            return
        
        # Fetch all members and validate they exist in the server
        members = []
        for user_id in user_ids:
            member = ctx.guild.get_member(user_id)
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden):
                    member = None
            if member is None:
                await ctx.send(f"❌ User <@{user_id}> is not in this server.")
                return
            members.append(member)
        
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

        # Add reserves for all members and all pokemon
        for pokemon_name in pokemon_names:
            for member in members:
                self.add_reserve_owner(ctx.guild.id, str(pokemon_name), member.id)
        self.save_bot_state()
        
        # Build response message
        member_mentions = ", ".join(m.mention for m in members)
        if len(pokemon_names) == 1:
            await ctx.send(
                f"✅ **{pokemon_names[0]}** added to {member_mentions}'s reserves."
            )
        else:
            suffix = f" added to {member_mentions}'s reserves."
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
        """Show reservations for a Pokémon or category."""
        if ctx.guild is None:
            await ctx.send("Reservations can only be viewed inside a server.")
            return
        if not pokemon_input.strip():
            await ctx.send("Usage: `v!r search <pokemon|category>`")
            return
        search_input = pokemon_input.strip()
        category_key = self.find_category(ctx.guild.id, search_input)
        if category_key is not None:
            pokemon_names = self.guild_categories(ctx.guild.id)[category_key]
            if not pokemon_names:
                await ctx.send(f"❌ Category **{category_key}** is empty.")
                return
            reserved = []
            unreserved = []
            for pokemon_name in pokemon_names:
                user_ids = self.reserve_user_ids(ctx.guild.id, pokemon_name)
                if user_ids:
                    reserved.extend(
                        f"• **{pokemon_name}** — <@{user_id}>"
                        for user_id in user_ids
                    )
                else:
                    unreserved.append(f"• **{pokemon_name}**")
            lines = (
                ["**Reserved**"]
                + (reserved or ["No Pokémon are reserved."])
                + ["", "**Not reserved**"]
                + (unreserved or ["All Pokémon in this category are reserved."])
            )
            chunks = []
            chunk = []
            for line in lines:
                if chunk and (
                    len(chunk) >= 20
                    or len("\n".join(chunk)) + len(line) + 1 > 3900
                ):
                    chunks.append(chunk)
                    chunk = []
                chunk.append(line)
            if chunk:
                chunks.append(chunk)
            embeds = [
                discord.Embed(
                    title=f"{category_key[:230]} Category Reservations",
                    description="\n".join(page),
                    color=discord.Color.purple(),
                ).set_footer(text=f"Page {index} of {len(chunks)}")
                for index, page in enumerate(chunks, 1)
            ]
            if len(embeds) == 1:
                await ctx.send(embed=embeds[0])
            else:
                await ctx.send(
                    embed=embeds[0], view=ReserveListView(ctx.author.id, embeds)
                )
            return
        all_forms = search_input.casefold().startswith("all ")
        family_input = search_input[4:].strip() if all_forms else search_input
        pokemon_names = (
            self.resolve_pokemon_family(family_input)
            if all_forms
            else [self.resolve_pokemon_name(family_input)]
        )
        pokemon_names = [name for name in pokemon_names if name is not None]
        if not pokemon_names:
            await ctx.send(f"❌ Unknown Pokémon: `{pokemon_input.strip()}`")
            return
        if len(pokemon_names) > 1:
            lines = []
            for pokemon_name in pokemon_names:
                user_ids = self.reserve_user_ids(ctx.guild.id, pokemon_name)
                reservers = (
                    ", ".join(f"<@{user_id}>" for user_id in user_ids)
                    if user_ids
                    else "No members have reserved this Pokémon."
                )
                lines.append(f"**{pokemon_name}** — {reservers}")
            label = family_input[0].upper() + family_input[1:]
            embed = discord.Embed(
                title=f"All {label} Reservations",
                description="\n".join(lines),
                color=discord.Color.purple(),
            )
            await ctx.send(embed=embed)
            return

        pokemon_name = pokemon_names[0]
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

    @commands.command(name="rafk")
    async def reserve_afk_command(self, ctx):
        """Release your reserves and request an FFA announcement."""
        if ctx.guild is None:
            await ctx.send("Reservations can only be managed inside a server.")
            return
        view = FFAReserveView(self, ctx.guild.id, ctx.guild.name, ctx.author.id)
        await ctx.send(embed=view.build_embed(), view=view)

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
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to grab reserves.")
            return
        await self.grab_reserves(ctx, h_mode=False)

    @commands.group(name="readyup", invoke_without_command=True)
    async def readyup(self, ctx):
        """Start a ready check for the users added from a grabbed list."""
        if ctx.guild is None:
            await ctx.send("Ready-up can only be used inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to use ready-up.")
            return
        user_ids = self.readyup_user_ids(ctx.guild.id)
        if not user_ids:
            await ctx.send(
                "The ready-up queue is empty. Use `v!grab` and click **Readyup** "
                "to add users first."
            )
            return
        view = ReadyupView(self, ctx.guild.id, ctx.author.id, user_ids)
        mention_chunks = []
        current_mentions = []
        current_length = 0
        for user_id in user_ids:
            mention = f"<@{user_id}>"
            mention_length = len(mention) + (1 if current_mentions else 0)
            if current_mentions and current_length + mention_length > 1900:
                mention_chunks.append(" ".join(current_mentions))
                current_mentions = []
                current_length = 0
                mention_length = len(mention)
            current_mentions.append(mention)
            current_length += mention_length
        if current_mentions:
            mention_chunks.append(" ".join(current_mentions))
        allowed_mentions = discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        )
        if len(mention_chunks) == 1:
            message = await ctx.send(
                content=mention_chunks[0],
                embed=view.build_embed(),
                view=view,
                allowed_mentions=allowed_mentions,
            )
        else:
            for mentions in mention_chunks:
                await ctx.send(
                    content=mentions,
                    allowed_mentions=allowed_mentions,
                )
            message = await ctx.send(embed=view.build_embed(), view=view)
        view.message = message
        self.readyup_views[str(ctx.guild.id)] = view

    @readyup.command(name="clear")
    async def clear_readyup(self, ctx):
        """Clear the server's ready-up queue and end its active check."""
        if ctx.guild is None:
            await ctx.send("Ready-up can only be used inside a server.")
            return
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to clear ready-up.")
            return
        count = self.clear_readyup_users(ctx.guild.id)
        view = self.readyup_views.pop(str(ctx.guild.id), None)
        if view is not None:
            view.ended = True
            view.ready_button.disabled = True
            if view.message is not None:
                try:
                    await view.message.edit(
                        content="Ready-up queue cleared.",
                        embed=None,
                        view=None,
                    )
                    view.stop()
                except discord.NotFound:
                    view.stop()
                except discord.DiscordException as error:
                    logging.warning(
                        "Could not update cleared ready-up message: %s",
                        error,
                    )
        if count:
            await ctx.send(f"✅ Cleared **{count}** user(s) from the ready-up queue.")
        else:
            await ctx.send("The ready-up queue is already empty.")

    @commands.group(name="dex", invoke_without_command=True)
    async def dex(self, ctx):
        """Show dex import usage."""
        await ctx.send(
            "Reply to your Pokétwo Pokédex with `v!dex append`. "
            "Use `v!dexhelp` for settings."
        )

    @dex.command(name="append")
    async def append_dex(self, ctx):
        """Track missing Pokémon from a Pokétwo Pokédex."""
        await self.dex_tracking_service.append(ctx)

    @commands.command(name="dexhelp")
    async def dex_help(self, ctx):
        """Open the dex tracking settings."""
        if ctx.guild is None:
            await ctx.send("❌ Dex tracking can only be used inside a server.")
            return
        view = DexSettingsView(self.dex_tracking_service, ctx.guild.id, ctx.author.id)
        await ctx.send(embed=view.embed(), view=view)

    @commands.group(name="cl", invoke_without_command=True)
    async def collection(self, ctx):
        """Show the caller's collection help."""
        if ctx.invoked_subcommand is not None:
            return
        await ctx.send(
            "Usage: `v!cl add <pokemon|category>`, "
            "`v!cl remove <pokemon|category>`, "
            "`v!cl search <pokemon>`, `v!cl list`, or `v!cl clear`."
        )

    @collection.command(name="add")
    async def add_collection(self, ctx, *, pokemon_input: str):
        """Add Pokémon, a family, or a server category to the caller's collection."""
        if ctx.guild is None:
            await ctx.send("Collections can only be managed inside a server.")
            return
        category_key = self.find_category(ctx.guild.id, pokemon_input.strip())
        if category_key is not None:
            pokemon_names = self.guild_categories(ctx.guild.id)[category_key]
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
        """Remove Pokémon or a server category from the caller's collection."""
        if ctx.guild is None:
            await ctx.send("Collections can only be managed inside a server.")
            return
        category_key = self.find_category(ctx.guild.id, pokemon_input.strip())
        if category_key is not None:
            pokemon_names = self.guild_categories(ctx.guild.id)[category_key]
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

    @collection.command(name="search")
    async def search_collection(self, ctx, *, pokemon_input: str):
        """Check whether a Pokémon is in the caller's collection."""
        if ctx.guild is None:
            await ctx.send("Collections can only be viewed inside a server.")
            return
        search_input = pokemon_input.strip()
        if not search_input:
            await ctx.send("Usage: `v!cl search <pokemon>`")
            return
        pokemon_name = self.resolve_pokemon_name(search_input)
        if pokemon_name is None:
            await ctx.send(f"❌ Unknown Pokémon: `{search_input}`")
            return

        collection = self.bot_state["collections"].get(
            str(ctx.guild.id),
            {},
        ).get(str(ctx.author.id), [])
        found = pokemon_name in collection
        description = (
            f"✅ **{pokemon_name}** is in your collection."
            if found
            else f"❌ **{pokemon_name}** is not in your collection."
        )
        embed = discord.Embed(
            title=f"{pokemon_name} Collection Search",
            description=description,
            color=discord.Color.blue(),
        )
        await ctx.send(embed=embed)

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

    @commands.command(name="apislow")
    async def api_slowest(self, ctx):
        """Break down the slowest of the latest 100 spawn responses."""
        if not self.spawn_metrics:
            await ctx.send("No spawn response timings have been recorded yet.")
            return

        slowest = max(self.spawn_metrics, key=lambda metrics: metrics["total"])
        other = slowest["total"] - (
            slowest["download"] + slowest["inference"] + slowest["send"]
        )
        embed = discord.Embed(title="Slowest Response Breakdown", color=0x000000)
        for name, seconds in (
            ("Download", slowest["download"]),
            ("Inference", slowest["inference"]),
            ("Discord send", slowest["send"]),
            ("Other", other),
            ("Total", slowest["total"]),
        ):
            embed.add_field(name=name, value=f"{seconds * 1000:.0f} ms", inline=True)
        embed.set_footer(text="Window: latest 100 recognitions")
        await ctx.send(embed=embed)

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
                "Download Avg",
                f"{timing(self.image_download_times) * 1000:.0f} ms",
            ),
            (
                "Download Latest",
                f"{timing(self.image_download_times, 'latest') * 1000:.0f} ms",
            ),
            (
                "Send Avg",
                f"{timing(self.message_send_times) * 1000:.0f} ms",
            ),
            (
                "Send Latest",
                f"{timing(self.message_send_times, 'latest') * 1000:.0f} ms",
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
        embed.set_footer(
            text=(
                f"Model: {MODEL_READ_VERSION} | ONNX fp32 "
                f"| Window: latest 100 recognitions"
            )
        )
        await ctx.send(embed=embed)

    @commands.command(name="servers")
    async def servers(self, ctx):
        """List every Discord server this bot is connected to."""
        if not self.has_restricted_permission(ctx):
            await ctx.send("❌ You do not have permission to view servers.")
            return
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

    async def daycare_box_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            guild_id = interaction.guild.id if interaction.guild is not None else 0
            boxes = self.breeding_box_service.user_boxes(
                guild_id, interaction.user.id
            )
            choices = []
            query = str(current).casefold()
            for index, box_name in enumerate(boxes, start=1):
                name = str(box_name)
                if query not in name.casefold():
                    continue
                choices.append(
                    app_commands.Choice(
                        name=name[:100],
                        value=str(index) if name.isdigit() else name[:100],
                    )
                )
                if len(choices) == 25:
                    break
            return choices
        except Exception as error:
            print(
                "Could not load global daycare box autocomplete "
                f"for user {getattr(interaction.user, 'id', 'unknown')}: {error}"
            )
            return []

    @app_commands.command(name="dc", description="Find compatible daycare pairs")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        box="Choose a breeding box",
        count="Number of different pairs to find (default: 1)",
    )
    @app_commands.autocomplete(box=daycare_box_autocomplete)
    async def slash_daycare(
        self,
        interaction: discord.Interaction,
        box: str | None = None,
        count: app_commands.Range[int, 1] = 1,
    ):
        await interaction.response.defer()
        ctx = SlashDaycareContext(interaction)
        await self.breeding_box_service.show_daycare_pairs(
            ctx, box or "", limit=count
        )


async def setup(bot):
    """Load the bot cog"""
    await bot.add_cog(PokéTwoNamingBot(bot))
