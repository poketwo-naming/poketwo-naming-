"""Automatic update announcements for the Poketwo Naming server."""
import asyncio
import traceback

import discord


ANNOUNCEMENT_CHANNEL_ID = 1574489953444827146
ANNOUNCEMENT_ROLE_ID = 1574502724370825286
ANNOUNCEMENT_STATE_KEY = "automatic_update_announcement"
PENDING_MESSAGE_STATE_KEY = "automatic_update_pending_message"
UPDATE_ANNOUNCEMENT = (
    "**What's new**\n"
    "🔧 **Breeding Box Slash Commands** - Manage boxes and daycare pairs with `/` commands\n"
    "  - Use `/box` for create, list, append, remove, transfer, copy, tags, rename, and reset\n"
    "  - Use `/dc` to find pairs or open daycare settings\n"
    "  - Use `/boxhelp` for the breeding box command guide"
)


async def post_update_announcement(bot, cog) -> bool:
    """Send and automatically publish the latest update once."""
    bot_state = cog.bot_state

    bot_state.pop("last_update_announcement", None)
    bot_state.pop("pending_update_publication", None)

    if bot_state.get(ANNOUNCEMENT_STATE_KEY) == UPDATE_ANNOUNCEMENT:
        bot_state.pop(PENDING_MESSAGE_STATE_KEY, None)
        return False

    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        raise TypeError(
            f"Announcement channel {ANNOUNCEMENT_CHANNEL_ID} is not a text channel"
        )

    pending_id = bot_state.get(PENDING_MESSAGE_STATE_KEY)
    if pending_id is not None:
        if not isinstance(pending_id, int):
            bot_state.pop(PENDING_MESSAGE_STATE_KEY, None)
            cog.save_bot_state()
        else:
            message = await channel.fetch_message(pending_id)
            if not getattr(message.flags, "crossposted", False):
                await message.publish()
            bot_state.pop(PENDING_MESSAGE_STATE_KEY)
            bot_state[ANNOUNCEMENT_STATE_KEY] = UPDATE_ANNOUNCEMENT
            cog.save_bot_state()
            return True

    message = await channel.send(
        f"<@&{ANNOUNCEMENT_ROLE_ID}> {UPDATE_ANNOUNCEMENT}",
        allowed_mentions=discord.AllowedMentions(
            roles=[discord.Object(id=ANNOUNCEMENT_ROLE_ID)],
            users=False,
            everyone=False,
        ),
    )

    bot_state[PENDING_MESSAGE_STATE_KEY] = message.id
    cog.save_bot_state()

    if not getattr(message.flags, "crossposted", False):
        await message.publish()

    bot_state.pop(PENDING_MESSAGE_STATE_KEY)
    bot_state[ANNOUNCEMENT_STATE_KEY] = UPDATE_ANNOUNCEMENT
    cog.save_bot_state()
    return True


async def run_update_announcement(bot, retries: int = 12, delay_seconds: float = 5) -> None:
    """Retry startup announcement failures until a send/publish succeeds."""
    for attempt in range(retries):
        cog = bot.get_cog("PokéTwoNamingBot")
        if cog is None:
            if attempt + 1 < retries:
                await asyncio.sleep(delay_seconds)
            continue
        try:
            if await post_update_announcement(bot, cog):
                print("✅ Update announcement sent and published")
            else:
                print("ℹ️ Update announcement is already current")
            return
        except Exception as error:
            print(
                f"⚠️ Could not send/publish update announcement "
                f"(attempt {attempt + 1}/{retries}): {error}"
            )
            traceback.print_exc()
            if attempt + 1 < retries:
                await asyncio.sleep(delay_seconds)
