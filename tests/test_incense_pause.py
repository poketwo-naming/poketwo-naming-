import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from bot import PokéTwoNamingBot


class IncensePauseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {
            "incense_auto_pause": {},
            "paused_channels": {},
        }
        self.cog.save_bot_state = Mock()
        self.cog.pause_poketwo_channel = AsyncMock(return_value=True)
        self.channel = SimpleNamespace(send=AsyncMock())
        self.message = SimpleNamespace(
            content="Incense has been bought.",
            embeds=[],
            guild=SimpleNamespace(id=123),
            channel=self.channel,
        )

    async def test_confirmed_purchase_pauses_channel(self):
        await self.cog.maybe_pause_after_incense_purchase(self.message)

        self.cog.pause_poketwo_channel.assert_awaited_once_with(
            self.channel,
            reason="Pokétwo confirmed an incense purchase",
        )

    async def test_disabled_auto_pause_does_not_pause_channel(self):
        self.cog.bot_state["incense_auto_pause"]["123"] = False

        await self.cog.maybe_pause_after_incense_purchase(self.message)

        self.cog.pause_poketwo_channel.assert_not_awaited()

    async def test_unconfirmed_message_does_not_pause_channel(self):
        self.message.content = "Incense is active."

        await self.cog.maybe_pause_after_incense_purchase(self.message)

        self.cog.pause_poketwo_channel.assert_not_awaited()

    async def test_poff_and_pon_update_server_preference(self):
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            send=AsyncMock(),
        )
        self.cog.has_restricted_permission = Mock(return_value=True)

        await PokéTwoNamingBot.disable_incense_auto_pause.callback(self.cog, ctx)
        self.assertFalse(self.cog.incense_auto_pause_enabled(123))

        await PokéTwoNamingBot.enable_incense_auto_pause.callback(self.cog, ctx)
        self.assertTrue(self.cog.incense_auto_pause_enabled(123))
        self.assertEqual(ctx.send.await_count, 2)

    async def test_poff_requires_restricted_permission(self):
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            send=AsyncMock(),
        )
        self.cog.has_restricted_permission = Mock(return_value=False)

        await PokéTwoNamingBot.disable_incense_auto_pause.callback(self.cog, ctx)

        self.assertTrue(self.cog.incense_auto_pause_enabled(123))
        ctx.send.assert_awaited_once()

    async def test_r_all_resumes_tracked_channels_in_this_server(self):
        poketwo = object()

        def make_channel(channel_id):
            guild = SimpleNamespace(
                id=123,
                me=object(),
                get_member=lambda member_id: poketwo,
            )
            channel = SimpleNamespace(
                id=channel_id,
                guild=guild,
                permissions_for=Mock(
                    return_value=SimpleNamespace(manage_channels=True)
                ),
                set_permissions=AsyncMock(),
            )
            guild.channels = [channel]
            return channel

        first = make_channel(1)
        second = make_channel(2)
        guild = SimpleNamespace(
            id=123,
            channels=[first, second],
        )
        self.cog.bot_state["paused_channels"] = {
            "1": {"guild_id": "123", "existed": False, "allow": 0, "deny": 0},
            "2": {"guild_id": "123", "existed": False, "allow": 0, "deny": 0},
            "3": {"guild_id": "456", "existed": False, "allow": 0, "deny": 0},
        }
        self.cog.has_restricted_permission = Mock(return_value=True)
        ctx = SimpleNamespace(
            guild=guild,
            send=AsyncMock(),
            message=SimpleNamespace(content="v!r all"),
        )

        await self.cog.dispatch_reservations(ctx)

        self.assertEqual(first.set_permissions.await_count, 1)
        self.assertEqual(second.set_permissions.await_count, 1)
        self.assertEqual(
            list(self.cog.bot_state["paused_channels"]),
            ["3"],
        )
        ctx.send.assert_awaited_once_with("✅ Resumed Pokétwo in 2 channel(s).")


if __name__ == "__main__":
    unittest.main()
