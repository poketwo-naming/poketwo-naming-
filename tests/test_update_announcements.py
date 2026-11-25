import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from announcements import (
    ACCUMULATED_UPDATES_KEY,
    ANNOUNCEMENT_CHANNEL_ID,
    ANNOUNCEMENT_ROLE_ID,
    ANNOUNCEMENT_STATE_KEY,
    PENDING_MESSAGE_STATE_KEY,
    UPDATE_ANNOUNCEMENT,
    add_update_to_announcement,
    post_update_announcement,
)


class FakeAnnouncementChannel(discord.TextChannel):
    pass


class UpdateAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    def make_channel(self):
        channel = Mock(spec=discord.TextChannel)
        channel.send = AsyncMock(
            return_value=SimpleNamespace(
                id=123,
                flags=SimpleNamespace(crossposted=False),
                publish=AsyncMock(),
            )
        )
        channel.fetch_message = AsyncMock()
        return channel

    async def test_sends_and_auto_publishes_once(self):
        channel = self.make_channel()
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())
        add_update_to_announcement(cog.bot_state, UPDATE_ANNOUNCEMENT)

        self.assertTrue(await post_update_announcement(bot, cog))
        bot.get_channel.assert_called_once_with(ANNOUNCEMENT_CHANNEL_ID)
        channel.send.assert_awaited_once()
        sent = channel.send.await_args
        self.assertEqual(
            sent.args[0],
            f"<@&{ANNOUNCEMENT_ROLE_ID}> {UPDATE_ANNOUNCEMENT}",
        )
        message = channel.send.return_value
        message.publish.assert_awaited_once()
        self.assertEqual(
            cog.bot_state[ANNOUNCEMENT_STATE_KEY],
            UPDATE_ANNOUNCEMENT,
        )
        self.assertNotIn(PENDING_MESSAGE_STATE_KEY, cog.bot_state)

        cog.save_bot_state.reset_mock()
        self.assertFalse(await post_update_announcement(bot, cog))
        channel.send.assert_awaited_once()
        cog.save_bot_state.assert_not_called()

    async def test_accumulates_multiple_updates(self):
        channel = self.make_channel()
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())
        
        update1 = "**🔔 Update 1**\nFirst change"
        update2 = "**🔔 Update 2**\nSecond change"
        add_update_to_announcement(cog.bot_state, update1)
        add_update_to_announcement(cog.bot_state, update2)

        self.assertTrue(await post_update_announcement(bot, cog))
        sent = channel.send.await_args
        expected_text = f"{update1}\n\n{update2}"
        self.assertEqual(
            sent.args[0],
            f"<@&{ANNOUNCEMENT_ROLE_ID}> {expected_text}",
        )

    async def test_fetches_channel_if_not_cached(self):
        channel = self.make_channel()
        bot = SimpleNamespace(
            get_channel=Mock(return_value=None),
            fetch_channel=AsyncMock(return_value=channel),
        )
        cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())
        add_update_to_announcement(cog.bot_state, UPDATE_ANNOUNCEMENT)

        self.assertTrue(await post_update_announcement(bot, cog))
        bot.fetch_channel.assert_awaited_once_with(ANNOUNCEMENT_CHANNEL_ID)

    async def test_retries_pending_message_without_sending_again(self):
        pending_message = SimpleNamespace(
            content=f"<@&{ANNOUNCEMENT_ROLE_ID}> {UPDATE_ANNOUNCEMENT}",
            flags=SimpleNamespace(crossposted=False),
            publish=AsyncMock(),
        )
        channel = self.make_channel()
        channel.fetch_message = AsyncMock(return_value=pending_message)
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(
            bot_state={PENDING_MESSAGE_STATE_KEY: 123, ACCUMULATED_UPDATES_KEY: [UPDATE_ANNOUNCEMENT]},
            save_bot_state=Mock(),
        )

        self.assertTrue(await post_update_announcement(bot, cog))
        channel.send.assert_not_awaited()
        channel.fetch_message.assert_awaited_once_with(123)
        pending_message.publish.assert_awaited_once()
        self.assertEqual(
            cog.bot_state[ANNOUNCEMENT_STATE_KEY],
            UPDATE_ANNOUNCEMENT,
        )

    async def test_old_pending_update_does_not_replace_new_announcement(self):
        channel = self.make_channel()
        old_message = SimpleNamespace(
            content="An older update",
            flags=SimpleNamespace(crossposted=False),
            publish=AsyncMock(),
        )
        channel.fetch_message.return_value = old_message
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(
            bot_state={PENDING_MESSAGE_STATE_KEY: 100, ACCUMULATED_UPDATES_KEY: [UPDATE_ANNOUNCEMENT]},
            save_bot_state=Mock(),
        )

        self.assertTrue(await post_update_announcement(bot, cog))
        old_message.publish.assert_awaited_once()
        channel.send.assert_awaited_once()
        channel.send.return_value.publish.assert_awaited_once()
        self.assertEqual(cog.bot_state[ANNOUNCEMENT_STATE_KEY], UPDATE_ANNOUNCEMENT)

    async def test_send_failure_is_not_marked_as_sent(self):
        channel = self.make_channel()
        channel.send.side_effect = discord.Forbidden(
            response=Mock(),
            message="missing permission",
        )
        bot = SimpleNamespace(
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        cog = SimpleNamespace(bot_state={ACCUMULATED_UPDATES_KEY: [UPDATE_ANNOUNCEMENT]}, save_bot_state=Mock())

        with self.assertRaises(discord.Forbidden):
            await post_update_announcement(bot, cog)
        self.assertNotIn(ANNOUNCEMENT_STATE_KEY, cog.bot_state)
        self.assertNotIn(PENDING_MESSAGE_STATE_KEY, cog.bot_state)
