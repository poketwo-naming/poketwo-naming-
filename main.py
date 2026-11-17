"""
Pokétwo Naming Bot - Main entry point
"""
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()


def get_token() -> str:
    """Load the required Discord token from the hosting environment."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not found in environment variables!")
        print(
            "Please set DISCORD_TOKEN in your hosting platform's environment variables."
        )
        raise RuntimeError("DISCORD_TOKEN is required")
    return token


TOKEN = get_token()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=("v!", "V!"), intents=intents)


@bot.event
async def on_ready():
    """Called when the bot is ready"""
    print(f"{bot.user} has connected to Discord!")
    print(f"Bot is in {len(bot.guilds)} guild(s)")


@bot.event
async def on_message(message):
    """Handle incoming messages"""
    if message.author == bot.user:
        return
    await bot.process_commands(message)


async def load_cogs():
    """Load all bot cogs"""
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")
            print(f"Loaded cog: {filename}")


async def main():
    """Start the bot"""
    async with bot:
        await bot.load_extension("bot")
        await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
