"""
Pokétwo Naming Bot - Core bot functionality for naming Pokémon
"""
import discord
from discord.ext import commands
import json
import os


POKETWO_BOT_ID = 716390085896962058


class PokéTwoNamingBot(commands.Cog):
    """Pokétwo naming bot cog with commands for naming Pokémon"""

    def __init__(self, bot):
        self.bot = bot
        self.names_file = "pokemon_names.json"
        self.suggestions_file = "pokemon_suggestions.json"
        self.load_names()
        self.load_suggestions()

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
        """Handle Pokétwo spawn messages"""
        try:
            # Check if message has embeds (Pokétwo spawn format)
            if not message.embeds:
                return

            embed = message.embeds[0]
            
            # Extract Pokémon info from embed
            pokemon_name = None
            pokemon_id = None
            
            # Try to get Pokémon name from embed title or description
            if embed.title:
                pokemon_name = embed.title.strip()
            
            # Try to extract from embed description or fields
            if embed.description:
                lines = embed.description.split('\n')
                for line in lines:
                    if 'level' in line.lower() or 'id' in line.lower():
                        pokemon_id = line
                        break
            
            # If we found a Pokémon, announce it
            if pokemon_name:
                # Check if we have a saved name for this Pokémon type
                pokemon_lower = pokemon_name.lower()
                
                # Get suggested names
                suggested_names = self.suggestions.get(pokemon_lower, [])
                
                # Create response embed
                embed_response = discord.Embed(
                    title=f"🎯 {pokemon_name} Spawn Detected!",
                    description=f"A wild **{pokemon_name}** has appeared!",
                    color=discord.Color.orange()
                )
                
                if suggested_names:
                    embed_response.add_field(
                        name="📝 Suggested Names",
                        value="\n".join(f"• {name}" for name in suggested_names[:5]),
                        inline=False
                    )
                
                embed_response.add_field(
                    name="💡 Usage",
                    value=f"Use `!nameit {pokemon_name.lower()}` to name it",
                    inline=False
                )
                
                # Send response in the same channel
                await message.channel.send(embed=embed_response)
                
        except Exception as e:
            print(f"Error handling Pokétwo spawn: {e}")

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check if the bot is responsive"""
        await ctx.send(f"Pong! {self.bot.latency * 1000:.2f}ms")

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
            name="!suggestname <pokemon>",
            value="Get name suggestions for a Pokémon",
            inline=False
        )
        embed.add_field(
            name="!nameit <pokemon>",
            value="Quick names for catching a Pokémon",
            inline=False
        )
        embed.add_field(
            name="!savename <id> <nickname>",
            value="Save a nickname for your Pokémon",
            inline=False
        )
        embed.add_field(
            name="!mynames",
            value="View all your saved Pokémon names",
            inline=False
        )
        embed.add_field(
            name="!deletename <id>",
            value="Delete a saved Pokémon name",
            inline=False
        )
        embed.add_field(
            name="!ping",
            value="Check bot status",
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
