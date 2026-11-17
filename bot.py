"""
Pokétwo Naming Bot - Core bot functionality for naming Pokémon
"""
from collections import deque
from io import BytesIO
from time import perf_counter

import aiohttp
import discord
from discord.ext import commands
import json
import os
from PIL import Image, UnidentifiedImageError

from pokemon_recognition import PokemonImageRecognizer


POKETWO_BOT_ID = 716390085896962058


class PokéTwoNamingBot(commands.Cog):
    """Pokétwo naming bot cog with commands for naming Pokémon"""

    def __init__(self, bot):
        self.bot = bot
        self.names_file = "pokemon_names.json"
        self.suggestions_file = "pokemon_suggestions.json"
        self.recognizer = PokemonImageRecognizer()
        self.http_session = None
        self.spawn_response_times = deque(maxlen=100)
        self.last_spawn_metrics = None
        self.recognized_spawn_count = 0
        self.load_names()
        self.load_suggestions()

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
        if os.path.exists(self.suggestions_file):
            with open(self.suggestions_file, "r") as f:
                self.suggestions = json.load(f)
        else:
            self.suggestions = {}

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for Pokétwo spawn messages"""
        # Ignore bot's own messages
        if message.author.id == self.bot.user.id:
            return

        # Check if message is from Pokétwo bot
        if message.author.id == POKETWO_BOT_ID:
            await self.handle_poketwo_spawn(message)

    async def handle_poketwo_spawn(self, message):
        """Identify a Pokétwo spawn and report the predicted Pokémon."""
        started = perf_counter()
        image_data, download_seconds = await self._get_spawn_image(message)
        if image_data is None:
            print("Pokétwo spawn did not contain a readable image.")
            return

        try:
            with Image.open(BytesIO(image_data)) as image:
                pokemon_name, confidence, inference_seconds = (
                    self.recognizer.recognize(image)
                )
        except (UnidentifiedImageError, OSError) as error:
            print(f"Could not read Pokétwo spawn image: {error}")
            return

        await message.channel.send(f"{pokemon_name} {confidence:.2f}%")
        total_seconds = perf_counter() - started
        self.spawn_response_times.append(total_seconds)
        self.last_spawn_metrics = {
            "download": download_seconds,
            "inference": inference_seconds,
            "total": total_seconds,
        }
        self.recognized_spawn_count += 1

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

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check if the bot is responsive"""
        await ctx.send(f"Pong! {self.bot.latency * 1000:.2f}ms")

    @commands.command(name="api")
    async def api_status(self, ctx):
        """Display current bot and spawn-recognition performance."""
        average_seconds = (
            sum(self.spawn_response_times) / len(self.spawn_response_times)
            if self.spawn_response_times
            else 0
        )
        metrics = self.last_spawn_metrics or {
            "download": 0,
            "inference": 0,
            "total": 0,
        }
        embed = discord.Embed(
            title="API Status",
            description="Pokémon recognition performance",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Activity",
            value=f"🟢 Active\nClasses `{len(self.recognizer.classes)}`",
            inline=True,
        )
        embed.add_field(
            name="Recognition",
            value=(
                f"Validation `{self.recognizer.validation_accuracy:.2%}`\n"
                f"Spawns `{self.recognized_spawn_count}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Gateway",
            value=f"Latency `{self.bot.latency * 1000:.2f} ms`",
            inline=True,
        )
        embed.add_field(
            name="Latest Download",
            value=f"`{metrics['download'] * 1000:.2f} ms`",
            inline=True,
        )
        embed.add_field(
            name="Latest Inference",
            value=f"`{metrics['inference'] * 1000:.2f} ms`",
            inline=True,
        )
        embed.add_field(
            name="Average Naming",
            value=f"`{average_seconds * 1000:.2f} ms`",
            inline=True,
        )
        await ctx.send(embed=embed)

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
            name="📡 Auto-Detection",
            value="Bot automatically detects Pokétwo spawns and shows naming suggestions!",
            inline=False
        )
        await ctx.send(embed=embed)


async def setup(bot):
    """Load the bot cog"""
    await bot.add_cog(PokéTwoNamingBot(bot))
