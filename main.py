"""
Pokétwo Naming Bot - Main entry point
"""
import os
import re
from typing import Protocol, cast

import discord
from discord.ext import commands
from dotenv import load_dotenv

from announcements import post_update_announcement

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


class BreedingBoxCog(Protocol):
    async def breeding_box_command(
        self,
        ctx: commands.Context,
        command: str,
        entry: str,
    ) -> None: ...


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=("v!", "V!"),
    intents=intents,
    help_command=None,
)


@bot.event
async def on_ready():
    """Called when the bot is ready"""
    print(f"{bot.user} has connected to Discord!")
    print(f"Bot is in {len(bot.guilds)} guild(s)")
    print(f"DEBUG: App commands in tree: {len(bot.tree._get_all_commands())}")
    
    # Sync app commands
    try:
        print("DEBUG: Starting app command sync...")
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} app command(s)")
        if synced:
            print(f"DEBUG: Synced commands: {[cmd.name for cmd in synced]}")
        else:
            print("DEBUG: No new commands to sync (already up to date)")
    except discord.app_commands.errors.AppCommandSyncError as e:
        # Handle Discord's Entry Point command restriction error
        if "50240" in str(e):
            print("⚠️  Warning: Entry Point command cannot be modified in bulk sync.")
            print("   This is expected behavior. App commands should still work.")
        else:
            print(f"❌ AppCommandSyncError: {e}")
    except Exception as e:
        print(f"❌ Sync failed with exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    # Try to post announcement (might fail if cog not loaded yet)
    cog = bot.get_cog("PokéTwoNamingBot")
    if cog is not None:
        try:
            result = await post_update_announcement(bot, cog)
            if result:
                print("✅ Update announcement posted successfully")
            else:
                print("ℹ️  Announcement unchanged from last post")
        except (discord.DiscordException, OSError, TypeError, ValueError) as error:
            print(f"⚠️  Could not post announcement: {error}")
    else:
        print("ℹ️  Cog not loaded yet, announcement deferred")


@bot.event
async def on_message(message):
    """Handle incoming messages"""
    if message.author == bot.user:
        return
    breeding_box_match = re.match(
        r"^\s*v!(?P<command>boxhelp|box|dc)(?:\s+(?P<entry>.*))?\s*$",
        message.content,
        re.IGNORECASE | re.DOTALL,
    )
    if breeding_box_match:
        ctx = await bot.get_context(message)
        cog = bot.get_cog("PokéTwoNamingBot")
        if cog is None:
            await message.channel.send(
                "❌ Breeding box handler is not loaded. Restart the bot."
            )
            return
        try:
            handler = cast(BreedingBoxCog, cog)
            await handler.breeding_box_command(
                ctx,
                breeding_box_match.group("command").casefold(),
                breeding_box_match.group("entry") or "",
            )
        except discord.DiscordException as error:
            print(f"Breeding box routing failed: {error}")
            await message.channel.send(
                "❌ Breeding boxes failed. Check the bot logs."
            )
        return
    reserve_list_match = re.fullmatch(
        r"\s*[vV]!(?:r|reserve)\s+list(?:\s+(.+?))?\s*",
        message.content,
    )
    if reserve_list_match:
        ctx = await bot.get_context(message)
        cog = bot.get_cog("PokéTwoNamingBot")
        if cog is None:
            cog = next(
                (
                    loaded_cog
                    for loaded_cog in bot.cogs.values()
                    if hasattr(loaded_cog, "show_reserve_list")
                ),
                None,
            )
        if cog is None:
            await message.channel.send(
                "❌ Reserve list handler is not loaded. Restart the bot."
            )
            return
        print(
            "Direct reserve-list route: "
            f"content={message.content!r} user={reserve_list_match.group(1)!r}"
        )
        try:
            await cog.show_reserve_list(
                ctx,
                reserve_list_match.group(1) or "",
            )
        except discord.DiscordException as error:
            print(f"Reserve list routing failed: {error}")
            await message.channel.send(
                "❌ Reserve list failed. Check the bot logs."
            )
        return
    await bot.process_commands(message)


async def load_cogs():
    """Load all bot cogs"""
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")
            print(f"Loaded cog: {filename}")


@bot.event
async def on_connect():
    """Sync app commands when bot connects"""
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} app command(s)")
    except discord.app_commands.errors.AppCommandSyncError as e:
        if "50240" in str(e):
            print("⚠️  Entry Point command cannot be modified (expected)")
        else:
            print(f"⚠️  Failed to sync app commands: {e}")
    except Exception as e:
        print(f"⚠️  Failed to sync app commands: {e}")


async def main():
    """Start the bot"""
    async with bot:
        await bot.load_extension("bot")
        await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
