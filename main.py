"""
Pokétwo Naming Bot - Main entry point
"""
import asyncio
import os
import re
from typing import Protocol, cast

import discord
from discord.ext import commands
from dotenv import load_dotenv

from announcements import run_update_announcement

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


async def sync_global_commands() -> int:
    """Sync commands without removing an existing Activity entry point."""
    try:
        return len(await bot.tree.sync())
    except discord.HTTPException as error:
        if error.code != 50240:
            raise

    application_id = bot.application_id
    if application_id is None:
        raise discord.app_commands.MissingApplicationID
    registered = bot.tree.get_commands()
    translator = bot.tree.translator
    for command in registered:
        if translator is None:
            payload = command.to_dict(bot.tree)
        else:
            payload = await command.get_translated_payload(bot.tree, translator)
        await bot.http.upsert_global_command(application_id, payload=payload)
    print(
        "ℹ️ Synced commands individually to preserve the app's Entry Point; "
        "existing remote commands were not removed."
    )
    return len(registered)


@bot.event
async def on_ready():
    """Called when the bot is ready"""
    print(f"{bot.user} has connected to Discord!")
    print(f"Bot is in {len(bot.guilds)} guild(s)")
    asyncio.create_task(run_update_announcement(bot))

    try:
        count = await asyncio.wait_for(sync_global_commands(), timeout=120.0)
        print(f"✅ Synced {count} application command(s)")
    except asyncio.TimeoutError:
        print("⚠️  Slash command sync timed out (120s)")
    except (discord.DiscordException, discord.app_commands.AppCommandError) as error:
        print(f"❌ Failed to sync slash commands: {error}")


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


async def main():
    """Start the bot"""
    async with bot:
        await bot.load_extension("bot")
        await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
