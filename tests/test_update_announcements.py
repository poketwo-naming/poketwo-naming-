import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from announcements import (
    ANNOUNCEMENT_CHANNEL_ID,
    ANNOUNCEMENT_STATE_KEY,
    UPDATE_ANNOUNCEMENT,
    post_update_announcement,
)


class FakeMessageableChannel(discord.abc.Messageable):
    def __init__(self):
        self.send = AsyncMock()


class UpdateAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_new_announcement_and_does_not_repeat_it(self):
        channel = FakeMessageableChannel()
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())

        self.assertTrue(await post_update_announcement(bot, cog))
        channel.send.assert_awaited_once_with(UPDATE_ANNOUNCEMENT)
        bot.get_channel.assert_called_once_with(ANNOUNCEMENT_CHANNEL_ID)
        bot.fetch_channel.assert_not_awaited()
        cog.save_bot_state.assert_called_once()

        self.assertFalse(await post_update_announcement(bot, cog))
        channel.send.assert_awaited_once_with(UPDATE_ANNOUNCEMENT)

    async def test_fetches_channel_when_not_cached(self):
        channel = FakeMessageableChannel()
        bot = SimpleNamespace(
            get_channel=Mock(return_value=None),
            fetch_channel=AsyncMock(return_value=channel),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())

        self.assertTrue(await post_update_announcement(bot, cog))
        bot.fetch_channel.assert_awaited_once_with(ANNOUNCEMENT_CHANNEL_ID)

    async def test_does_not_mark_announcement_sent_if_send_fails(self):
        channel = FakeMessageableChannel()
        channel.send.side_effect = discord.Forbidden(
            response=Mock(), message="missing permission"
        )
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())

        with self.assertRaises(discord.Forbidden):
            await post_update_announcement(bot, cog)

        self.assertNotIn(ANNOUNCEMENT_STATE_KEY, cog.bot_state)
        cog.save_bot_state.assert_not_called()

    async def test_retries_after_announcement_state_cannot_be_saved(self):
        channel = FakeMessageableChannel()
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(
            bot_state={},
            save_bot_state=Mock(side_effect=OSError("disk unavailable")),
        )

        with self.assertRaises(OSError):
            await post_update_announcement(bot, cog)

        self.assertNotIn(ANNOUNCEMENT_STATE_KEY, cog.bot_state)
