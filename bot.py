"""
Pokétwo Naming Bot - Core bot functionality for naming Pokémon
"""
from collections import deque
from hashlib import sha256
from io import BytesIO
import asyncio
import json
import os
import re
from time import monotonic, perf_counter
from zipfile import ZIP_DEFLATED, ZipFile

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, UnidentifiedImageError

from pokemon_recognition import PokemonImageRecognizer


POKETWO_BOT_ID = 716390085896962058
TRAINING_REVIEW_CHANNEL_ID = 1531476097970212915
TRAINING_ROOT = "pokemon_images/training_data"
TRAINING_COLLECTION_FILE = "pokemon_images/new_training_images.json"
MODEL_READ_VERSION = "V2.0.0"
TRAINING_REVIEWER_USER_IDS = {217819108329259008}
BOT_STATE_FILE = "bot_state.json"
PREMIUM_MAIN_GUILD_ID = 1530949341013868635
PREMIUM_CAPACITIES = {
    "bronze": 100,
    "silver": 200,
    "gold": 300,
}
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


class PokéTwoNamingBot(commands.Cog):
    """Pokétwo naming bot cog with commands for naming Pokémon"""

    def __init__(self, bot):
        self.bot = bot
        self.names_file = "pokemon_names.json"
        self.suggestions_file = "pokemon_suggestions.json"
        model_started = perf_counter()
        self.recognizer = PokemonImageRecognizer()
        self.model_load_seconds = perf_counter() - model_started
        self.http_session = None
        self.spawn_response_times = deque(maxlen=100)
        self.inference_times = deque(maxlen=100)
        self.store_times = deque(maxlen=100)
        self.last_spawn_metrics = None
        self.recognized_spawn_count = 0
        self.recent_spawn_times = {}
        self.active_incenses = {}
        self.class_names = {name.casefold(): name for name in self.recognizer.classes}
        self.pokemon_types = self.load_pokemon_types()
        self.pokemon_best_names = self.load_pokemon_best_names()
        self.reviewed_spawn_count = self.load_collected_training_count()
        self.bot_state = self.load_bot_state()
        self.premium_servers_file = os.getenv(
            "PREMIUM_SERVERS_FILE",
            "data/premium_servers.json",
        )
        self.premium_servers = self.load_premium_servers()
        self.load_names()
        self.load_suggestions()

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

    def format_spawn_prediction(self, pokemon_name: str, confidence: float) -> str:
        """Format the prediction with every correct primary/secondary type icon."""
        icons = " ".join(
            TYPE_EMOJIS[pokemon_type]
            for pokemon_type in self.pokemon_types[pokemon_name]
        )
        return (
            f"{icons} {pokemon_name} {confidence:.2f}%\n"
            f"best name: {self.pokemon_best_names[pokemon_name]}"
        )

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
        """Close shared HTTP resources."""
        if self.http_session is not None:
            await self.http_session.close()

    def load_names(self):
        """Load saved names from file"""
        if os.path.exists(self.names_file):
            with open(self.names_file, "r") as f:
                self.names = json.load(f)
        else:
            self.names = {}

    def save_names(self):
        """Save names to file"""
        with open(self.names_file, "w") as f:
            json.dump(self.names, f, indent=2)

    def load_suggestions(self):
        """Load Pokémon suggestions from file"""
        started = perf_counter()
        if os.path.exists(self.suggestions_file):
            with open(self.suggestions_file, "r") as f:
                self.suggestions = json.load(f)
        else:
            self.suggestions = {}
        self.json_load_seconds = perf_counter() - started

    def load_collected_training_count(self):
        """Return the number of feedback images collected for retraining."""
        if not os.path.exists(TRAINING_COLLECTION_FILE):
            return 0
        with open(TRAINING_COLLECTION_FILE, "r", encoding="utf-8") as f:
            collected = json.load(f)
        return len(collected)

    def load_bot_state(self):
        """Load persistent restricted roles and paused channel overwrites."""
        if not os.path.exists(BOT_STATE_FILE):
            return {"restricted_roles": {}, "paused_channels": {}}
        with open(BOT_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        state.setdefault("restricted_roles", {})
        state.setdefault("paused_channels", {})
        return state

    def save_bot_state(self):
        """Persist configuration needed to resume paused channels safely."""
        with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.bot_state, f, indent=2, ensure_ascii=False)

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

        now = monotonic()
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
        role_id = self.bot_state["restricted_roles"].get(str(ctx.guild.id))
        return bool(role_id and ctx.author.get_role(int(role_id)))

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
        """Track explicit incense notices and burst spawn activity by channel."""
        channel_id = int(message.channel.id)
        now = monotonic()
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
            if re.search(r"\b(end|ended|expired|stopped|inactive)\w*\b", text):
                self.active_incenses.pop(channel_id, None)
                return
            if re.search(r"\b(active|activated|started|remaining)\w*\b", text):
                self.active_incenses[channel_id] = now + 60 * 60

        if self.is_spawn_message(message):
            recent = self.recent_spawn_times.setdefault(
                channel_id,
                deque(maxlen=20),
            )
            recent.append(now)
            recent_count = sum(now - spawned < 90 for spawned in recent)
            if recent_count >= 3:
                self.active_incenses[channel_id] = now + 20 * 60

    def active_incense_count(self, guild_id: int | None = None) -> int:
        """Count unexpired incense channels, optionally within one guild."""
        now = monotonic()
        for channel_id, expires_at in list(self.active_incenses.items()):
            if expires_at <= now:
                self.active_incenses.pop(channel_id, None)
        if guild_id is None:
            return len(self.active_incenses)
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

        # Check if message is from Pokétwo bot
        if message.author.id == POKETWO_BOT_ID:
            if message.guild and self.premium_tier(message.guild.id) is None:
                return
            self.track_incense(message)
            if self.is_spawn_message(message) and self.channel_within_incense_capacity(
                message
            ):
                await self.handle_poketwo_spawn(message)

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

        if message.channel.id == TRAINING_REVIEW_CHANNEL_ID:
            embed = discord.Embed(
                title="Is this Pokémon correct?",
                color=discord.Color.blurple(),
            )
            type_icons = " ".join(
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
            await message.channel.send(
                self.format_spawn_prediction(pokemon_name, confidence)
            )

        if pokemon_name.casefold() == "missingno":
            guild_id = str(message.guild.id)
            role_id = self.bot_state["restricted_roles"].get(guild_id)
            staff_mention = f"<@&{role_id}>" if role_id else "@staff"
            pause_note = (
                " The channel is paused for Pokétwo."
                if missingno_pause
                else " I could not pause Pokétwo automatically."
            )
            await message.channel.send(
                f"⚠️ Don't catch this Pokémon! Ping a staff member: {staff_mention}."
                f"{pause_note} Use `v!r` to resume."
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

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check if the bot is responsive"""
        await ctx.send(f"Pong! {self.bot.latency * 1000:.2f}ms")

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
        self.bot_state["restricted_roles"][str(ctx.guild.id)] = str(role.id)
        self.save_bot_state()
        await ctx.send(f"✅ Restricted commands are now available to {role.mention}.")

    @commands.command(name="r")
    async def resume_poketwo(self, ctx):
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

    @commands.command(name="suggestname")
    async def suggest_name(self, ctx, pokemon_name: str):
        """Suggest a name for a Pokémon"""
        pokemon = pokemon_name.lower()
        
        if pokemon in self.suggestions:
            suggestions = self.suggestions[pokemon]
            embed = discord.Embed(
                title=f"Name Suggestions for {pokemon_name}",
                description="\n".join(f"• {name}" for name in suggestions),
                color=discord.Color.gold()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ No suggestions found for {pokemon_name}. Try another Pokémon!")

    @commands.command(name="savename")
    async def save_name(self, ctx, pokemon_id: str, *, nickname: str):
        """Save a nickname for your Pokémon"""
        user_id = str(ctx.author.id)
        
        if user_id not in self.names:
            self.names[user_id] = {}
        
        self.names[user_id][pokemon_id] = nickname
        self.save_names()
        
        embed = discord.Embed(
            title="✅ Name Saved!",
            description=f"Pokémon **{pokemon_id}** is now named **{nickname}**",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name="nameit")
    async def name_it(self, ctx, *, pokemon_name: str):
        """Quick name a Pokémon (use with Pokétwo catch)"""
        pokemon = pokemon_name.lower()
        
        if pokemon in self.suggestions:
            suggestions = self.suggestions[pokemon]
            embed = discord.Embed(
                title=f"🎀 Quick Name for {pokemon_name}",
                description=f"Top suggestion: **{suggestions[0]}**\n\nOther options:\n" + 
                           "\n".join(f"• {name}" for name in suggestions[1:5]),
                color=discord.Color.purple()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ No suggestions for {pokemon_name}!")

    @commands.command(name="mynames")
    async def my_names(self, ctx):
        """View all your saved Pokémon names"""
        user_id = str(ctx.author.id)
        
        if user_id not in self.names or not self.names[user_id]:
            await ctx.send("❌ You haven't saved any Pokémon names yet!")
            return
        
        embed = discord.Embed(
            title=f"{ctx.author.name}'s Pokémon Names",
            color=discord.Color.blue()
        )
        
        for pokemon_id, nickname in self.names[user_id].items():
            embed.add_field(name=f"ID: {pokemon_id}", value=f"**{nickname}**", inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name="deletename")
    async def delete_name(self, ctx, pokemon_id: str):
        """Delete a saved Pokémon name"""
        user_id = str(ctx.author.id)
        
        if user_id not in self.names or pokemon_id not in self.names[user_id]:
            await ctx.send("❌ That Pokémon name doesn't exist!")
            return
        
        deleted_name = self.names[user_id].pop(pokemon_id)
        self.save_names()
        
        await ctx.send(f"✅ Deleted nickname **{deleted_name}** for Pokémon **{pokemon_id}**")

    @commands.command(name="help_naming")
    async def help_naming(self, ctx):
        """Display help for Pokétwo naming bot"""
        embed = discord.Embed(
            title="🎀 Pokétwo Naming Bot Help",
            description="Commands for managing Pokémon names",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="v!suggestname <pokemon>",
            value="Get name suggestions for a Pokémon",
            inline=False
        )
        embed.add_field(
            name="v!nameit <pokemon>",
            value="Quick names for catching a Pokémon",
            inline=False
        )
        embed.add_field(
            name="v!savename <id> <nickname>",
            value="Save a nickname for your Pokémon",
            inline=False
        )
        embed.add_field(
            name="v!mynames",
            value="View all your saved Pokémon names",
            inline=False
        )
        embed.add_field(
            name="v!deletename <id>",
            value="Delete a saved Pokémon name",
            inline=False
        )
        embed.add_field(
            name="v!ping",
            value="Check bot status",
            inline=False
        )
        embed.add_field(
            name="v!api",
            value="View Pokémon recognition and response timings",
            inline=False
        )
        embed.add_field(
            name="v!servers",
            value="List every server where the bot is active",
            inline=False
        )
        embed.add_field(
            name="v!premium",
            value="View Bronze, Silver, and Gold incense naming capacities",
            inline=False
        )
        embed.add_field(
            name="v!r",
            value="Resume a channel paused after MissingNo (restricted)",
            inline=False
        )
        embed.add_field(
            name="v!permission <role_id>",
            value="Grant a role access to restricted commands (administrator)",
            inline=False
        )
        embed.add_field(
            name="v!training",
            value="Show reviewed image count in the training channel",
            inline=False
        )
        embed.add_field(
            name="v!export_training",
            value="Download reviewed images for retraining",
            inline=False
        )
        embed.add_field(
            name="📡 Auto-Detection",
            value="Bot automatically detects Pokétwo spawns and shows naming suggestions!",
            inline=False
        )
        await ctx.send(embed=embed)


async def setup(bot):
    """Load the bot cog"""
    await bot.add_cog(PokéTwoNamingBot(bot))
