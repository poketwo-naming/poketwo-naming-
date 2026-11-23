"""Post update announcements to the configured Discord channel."""
import hashlib
from typing import Protocol

import discord


ANNOUNCEMENT_CHANNEL_ID = 1574489953444827146
ANNOUNCEMENT_ROLE_ID = 1574502724370825286
ANNOUNCEMENT_STATE_KEY = "last_update_announcement"
UPDATE_ANNOUNCEMENT = (
    "**What's new**\n"
    "- Added a ready-up queue: add users from `v!grab`, run `v!readyup` for "
    "a Ready button that pings queued users, and use `v!readyup clear` to reset "
    "the queue."
)


class AnnouncementCog(Protocol):
    bot_state: dict[str, object]

    def save_bot_state(self) -> None: ...


class AnnouncementBot(Protocol):
    def get_channel(self, channel_id: int) -> object | None: ...

    async def fetch_channel(self, channel_id: int) -> object: ...


async def post_update_announcement(bot: AnnouncementBot, cog: AnnouncementCog) -> bool:
    """Post the current update once, using bot state to avoid restart duplicates."""
    digest = hashlib.sha256(UPDATE_ANNOUNCEMENT.encode("utf-8")).hexdigest()
    if cog.bot_state.get(ANNOUNCEMENT_STATE_KEY) == digest:
        return False

    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not isinstance(channel, discord.abc.Messageable):
        raise TypeError(
            f"Announcement channel {ANNOUNCEMENT_CHANNEL_ID} cannot receive messages"
        )

    await channel.send(
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
    try:
        cog.save_bot_state()
    except OSError:
        if had_previous_digest:
            cog.bot_state[ANNOUNCEMENT_STATE_KEY] = previous_digest
        else:
            cog.bot_state.pop(ANNOUNCEMENT_STATE_KEY)
        raise
    return True
