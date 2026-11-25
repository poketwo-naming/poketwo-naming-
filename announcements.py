"""Automatic update announcements for the Poketwo Naming server."""
import asyncio
import discord


ANNOUNCEMENT_CHANNEL_ID = 1574489953444827146
ANNOUNCEMENT_ROLE_ID = 1574502724370825286
ANNOUNCEMENT_STATE_KEY = "automatic_update_announcement"
PENDING_MESSAGE_STATE_KEY = "automatic_update_pending_message"
ACCUMULATED_UPDATES_KEY = "accumulated_updates"
# Accumulate all updates made since last host restart instead of replacing with latest.
UPDATE_ANNOUNCEMENT = (
    "**🔔 FFA Approval Update**\n\n"
    "`v!rafk` announcement requests now ping <@&1574935908153557103> "
    "in the review channel so staff know an approval is needed."
)


def add_update_to_announcement(bot_state: dict, update_text: str) -> None:
    """Add an update to the accumulated list of changes since last restart."""
    updates = bot_state.setdefault(ACCUMULATED_UPDATES_KEY, [])
    if update_text not in updates:
        updates.append(update_text)


async def post_update_announcement(bot, cog) -> bool:
    """Send and automatically publish accumulated updates once."""
    bot_state = cog.bot_state

    bot_state.pop("last_update_announcement", None)
    bot_state.pop("pending_update_publication", None)

    updates = bot_state.get(ACCUMULATED_UPDATES_KEY, [])
    if not updates:
        return False

    announcement_text = "\n\n".join(updates)
    if (
        bot_state.get(ANNOUNCEMENT_STATE_KEY) == announcement_text
        and bot_state.get(PENDING_MESSAGE_STATE_KEY) is None
    ):
        return False

    content = f"<@&{ANNOUNCEMENT_ROLE_ID}> {announcement_text}"
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
            if message.content == content:
                bot_state[ANNOUNCEMENT_STATE_KEY] = announcement_text
            cog.save_bot_state()
            if bot_state.get(ANNOUNCEMENT_STATE_KEY) == announcement_text:
                return message.content == content

    message = await channel.send(
        content,
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
    bot_state[ANNOUNCEMENT_STATE_KEY] = announcement_text
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
            if attempt + 1 < retries:
                await asyncio.sleep(delay_seconds)
