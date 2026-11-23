import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import discord

from announcements import (
    ANNOUNCEMENT_CHANNEL_ID,
    ANNOUNCEMENT_ROLE_ID,
    ANNOUNCEMENT_STATE_KEY,
    AnnouncementBot,
    AnnouncementCog,
    PENDING_PUBLICATION_KEY,
    UPDATE_ANNOUNCEMENT,
    post_update_announcement,
)


class FakeMessageableChannel(discord.abc.Messageable):
    def __init__(self):
        self.message = SimpleNamespace(
            id=123,
            flags=SimpleNamespace(crossposted=False),
            publish=AsyncMock(),
        )
        self.send_mock = AsyncMock(return_value=self.message)
        self.fetch_message_mock = AsyncMock(return_value=self.message)
        self.send = self.send_mock
        self.fetch_message = self.fetch_message_mock


async def post_update(bot: SimpleNamespace, cog: SimpleNamespace) -> bool:
    return await post_update_announcement(
        cast(AnnouncementBot, bot),
        cast(AnnouncementCog, cog),
    )


class UpdateAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_new_announcement_and_does_not_repeat_it(self):
        channel = FakeMessageableChannel()
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())

        self.assertTrue(await post_update(bot, cog))
        channel.send_mock.assert_awaited_once()
        sent_message = channel.send_mock.await_args
        assert sent_message is not None
        self.assertEqual(
            sent_message.args[0],
            f"<@&{ANNOUNCEMENT_ROLE_ID}> {UPDATE_ANNOUNCEMENT}",
        )
        self.assertEqual(
            sent_message.kwargs["allowed_mentions"].roles,
            [discord.Object(id=ANNOUNCEMENT_ROLE_ID)],
        )
        bot.get_channel.assert_called_once_with(ANNOUNCEMENT_CHANNEL_ID)
        bot.fetch_channel.assert_not_awaited()
        channel.message.publish.assert_awaited_once()
        self.assertNotIn(PENDING_PUBLICATION_KEY, cog.bot_state)
        self.assertEqual(cog.save_bot_state.call_count, 2)

        self.assertFalse(await post_update(bot, cog))
        channel.send_mock.assert_awaited_once()

    async def test_fetches_channel_when_not_cached(self):
        channel = FakeMessageableChannel()
        bot = SimpleNamespace(
            get_channel=Mock(return_value=None),
            fetch_channel=AsyncMock(return_value=channel),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())

        self.assertTrue(await post_update(bot, cog))
        bot.fetch_channel.assert_awaited_once_with(ANNOUNCEMENT_CHANNEL_ID)

    async def test_does_not_mark_announcement_sent_if_send_fails(self):
        channel = FakeMessageableChannel()
        channel.send_mock.side_effect = discord.Forbidden(
            response=Mock(), message="missing permission"
        )
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())

        with self.assertRaises(discord.Forbidden):
            await post_update(bot, cog)

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
            await post_update(bot, cog)

        self.assertNotIn(ANNOUNCEMENT_STATE_KEY, cog.bot_state)
        self.assertNotIn(PENDING_PUBLICATION_KEY, cog.bot_state)
        channel.message.publish.assert_not_awaited()

    async def test_retries_failed_publication_without_reposting(self):
        channel = FakeMessageableChannel()
        channel.message.publish.side_effect = [
            discord.Forbidden(response=Mock(), message="missing permission"),
            None,
        ]
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())

        with self.assertRaises(discord.Forbidden):
            await post_update(bot, cog)

        self.assertEqual(cog.bot_state[PENDING_PUBLICATION_KEY], 123)
        self.assertFalse(await post_update(bot, cog))
        channel.send_mock.assert_awaited_once()
        channel.fetch_message_mock.assert_awaited_once_with(123)
        self.assertEqual(channel.message.publish.await_count, 2)
        self.assertNotIn(PENDING_PUBLICATION_KEY, cog.bot_state)

    async def test_recovery_does_not_publish_an_already_crossposted_message(self):
        channel = FakeMessageableChannel()
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(
            bot_state={},
            save_bot_state=Mock(side_effect=[None, OSError("disk unavailable"), None]),
        )

        with self.assertRaises(OSError):
            await post_update(bot, cog)

        self.assertEqual(cog.bot_state[PENDING_PUBLICATION_KEY], 123)
        channel.message.flags.crossposted = True
        self.assertFalse(await post_update(bot, cog))
        channel.send_mock.assert_awaited_once()
        channel.message.publish.assert_awaited_once()
        self.assertNotIn(PENDING_PUBLICATION_KEY, cog.bot_state)

    async def test_old_pending_update_is_published_before_new_update(self):
        channel = FakeMessageableChannel()
        old_message = SimpleNamespace(
            id=100,
            flags=SimpleNamespace(crossposted=False),
            publish=AsyncMock(),
        )
        channel.fetch_message_mock.return_value = old_message
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(
            bot_state={
                ANNOUNCEMENT_STATE_KEY: "old digest",
                PENDING_PUBLICATION_KEY: old_message.id,
            },
            save_bot_state=Mock(),
        )

        self.assertTrue(await post_update(bot, cog))

        old_message.publish.assert_awaited_once()
        channel.send_mock.assert_awaited_once()
        channel.message.publish.assert_awaited_once()
        self.assertNotIn(PENDING_PUBLICATION_KEY, cog.bot_state)
