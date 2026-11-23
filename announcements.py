"""Post update announcements to the configured Discord channel."""
import hashlib
from typing import Protocol

import discord


ANNOUNCEMENT_CHANNEL_ID = 1574489953444827146
ANNOUNCEMENT_STATE_KEY = "last_update_announcement"
UPDATE_ANNOUNCEMENT = (
    "**What's new**\n"
    "- Daycare results are plain messages with the selected box name and "
    "pair count, plus an inline phone copy and a fenced PC copy."
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

    await channel.send(UPDATE_ANNOUNCEMENT)
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
