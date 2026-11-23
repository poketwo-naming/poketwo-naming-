"""Post update announcements to the configured Discord channel."""
import hashlib
from typing import Protocol

import discord


ANNOUNCEMENT_CHANNEL_ID = 1574489953444827146
ANNOUNCEMENT_ROLE_ID = 1574502724370825286
ANNOUNCEMENT_STATE_KEY = "last_update_announcement"
PENDING_PUBLICATION_KEY = "pending_update_publication"
UPDATE_ANNOUNCEMENT = (
    "**What's new**\n"
    "🔧 **Announcement Posting Fix** - Update notices now post and publish reliably\n"
    "  - Send and publication failures are no longer silently swallowed\n"
    "  - Pending announcements retry instead of being lost\n"
    "  - Failed state saves roll back safely for the next retry"
)


class AnnouncementCog(Protocol):
    bot_state: dict[str, object]

    def save_bot_state(self) -> None: ...


class AnnouncementBot(Protocol):
    def get_channel(self, channel_id: int) -> object | None: ...

    async def fetch_channel(self, channel_id: int) -> object: ...


async def post_update_announcement(bot: AnnouncementBot, cog: AnnouncementCog) -> bool:
    """Post and publish the update once, retrying any pending publication."""
    digest = hashlib.sha256(UPDATE_ANNOUNCEMENT.encode("utf-8")).hexdigest()
    pending = cog.bot_state.get(PENDING_PUBLICATION_KEY)
    if cog.bot_state.get(ANNOUNCEMENT_STATE_KEY) == digest and pending is None:
        return False

    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not isinstance(channel, discord.abc.Messageable):
        raise TypeError(
            f"Announcement channel {ANNOUNCEMENT_CHANNEL_ID} cannot receive messages"
        )

    async def publish_pending(message: discord.Message) -> None:
        if not message.flags.crossposted:
            await message.publish()
        pending_id = cog.bot_state.pop(PENDING_PUBLICATION_KEY)
        try:
            cog.save_bot_state()
        except OSError:
            cog.bot_state[PENDING_PUBLICATION_KEY] = pending_id
            raise

    if pending is not None:
        if not isinstance(pending, int):
            raise ValueError("Invalid pending update announcement message ID")
        await publish_pending(await channel.fetch_message(pending))
        if cog.bot_state.get(ANNOUNCEMENT_STATE_KEY) == digest:
            return False

    message = await channel.send(
        f"<@&{ANNOUNCEMENT_ROLE_ID}> {UPDATE_ANNOUNCEMENT}",
        allowed_mentions=discord.AllowedMentions(
            roles=[discord.Object(id=ANNOUNCEMENT_ROLE_ID)],
            users=False,
            everyone=False,
        ),
    )
    had_previous_digest = ANNOUNCEMENT_STATE_KEY in cog.bot_state
    previous_digest = cog.bot_state.get(ANNOUNCEMENT_STATE_KEY)
    cog.bot_state[ANNOUNCEMENT_STATE_KEY] = digest
    cog.bot_state[PENDING_PUBLICATION_KEY] = message.id
    try:
        cog.save_bot_state()
    except OSError:
        cog.bot_state.pop(PENDING_PUBLICATION_KEY)
        if had_previous_digest:
            cog.bot_state[ANNOUNCEMENT_STATE_KEY] = previous_digest
        else:
            cog.bot_state.pop(ANNOUNCEMENT_STATE_KEY)
        raise
    await publish_pending(message)
    return True
