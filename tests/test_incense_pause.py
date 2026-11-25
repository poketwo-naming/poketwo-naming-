import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bot import POKETWO_BOT_ID, PokéTwoNamingBot


class IncensePauseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {
            "incense_auto_pause": {},
            "incense_purchases": {},
            "paused_channels": {},
        }
        self.cog.save_bot_state = Mock()
        self.cog.pause_poketwo_channel = AsyncMock(return_value=True)
        self.channel = SimpleNamespace(id=1, send=AsyncMock())
        self.message = SimpleNamespace(
            content="Incense has been bought.",
            embeds=[],
            guild=SimpleNamespace(id=123),
            channel=self.channel,
            created_at=datetime.fromtimestamp(100_000, timezone.utc),
        )

    async def test_confirmed_purchase_pauses_channel(self):
        await self.cog.maybe_pause_after_incense_purchase(self.message)

        self.cog.pause_poketwo_channel.assert_awaited_once_with(
            self.channel,
            reason="Pokétwo confirmed an incense purchase",
        )
        self.channel.send.assert_awaited_once_with(
            "✅ Pokétwo has been paused in this channel after the incense purchase. "
            "Use `v!resume` to resume it."
        )

    async def test_screenshot_purchase_confirmation_from_poketwo_pauses(self):
        self.message.content = "You purchased an Incense for 50 shards!"
        self.message.author = SimpleNamespace(id=POKETWO_BOT_ID)
        self.cog.bot = SimpleNamespace(user=SimpleNamespace(id=999))
        self.cog.track_incense = Mock()
        self.cog.premium_tier = Mock(return_value=None)

        await self.cog.on_message(self.message)

        self.cog.pause_poketwo_channel.assert_awaited_once()
        self.channel.send.assert_awaited_once()

    async def test_purchase_confirmation_in_embed_pauses(self):
        self.message.content = ""
        self.message.embeds = [
            SimpleNamespace(
                title=None,
                description="You purchased an Incense for 50 shards!",
                footer=None,
            )
        ]

        await self.cog.maybe_pause_after_incense_purchase(self.message)

        self.cog.pause_poketwo_channel.assert_awaited_once()
        self.channel.send.assert_awaited_once()

    async def test_failed_pause_reports_failure_not_success(self):
        self.cog.pause_poketwo_channel.return_value = False

        await self.cog.maybe_pause_after_incense_purchase(self.message)

        self.channel.send.assert_awaited_once()
        self.assertIn(
            "could not automatically pause", self.channel.send.await_args.args[0]
        )

    async def test_discord_permission_error_reports_failure(self):
        response = SimpleNamespace(status=403, reason="Forbidden")
        self.cog.pause_poketwo_channel.side_effect = discord.Forbidden(
            response, "Missing Permissions"
        )

        await self.cog.maybe_pause_after_incense_purchase(self.message)

        self.channel.send.assert_awaited_once()
        self.assertIn(
            "could not automatically pause", self.channel.send.await_args.args[0]
        )

    async def test_disabled_auto_pause_does_not_pause_channel(self):
        self.cog.bot_state["incense_auto_pause"]["123"] = False

        await self.cog.maybe_pause_after_incense_purchase(self.message)

        self.cog.pause_poketwo_channel.assert_not_awaited()
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.cog.bot_state["incense_purchases"]["123"]["1"], 100_000)

    async def test_unconfirmed_message_does_not_pause_channel(self):
        self.message.content = "Incense is active."

        await self.cog.maybe_pause_after_incense_purchase(self.message)

        self.cog.pause_poketwo_channel.assert_not_awaited()
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.cog.bot_state["incense_purchases"], {})

    async def test_edited_or_older_confirmation_does_not_extend_purchase_window(self):
        self.cog.bot_state["incense_auto_pause"]["123"] = False
        await self.cog.maybe_pause_after_incense_purchase(self.message)
        self.message.created_at = datetime.fromtimestamp(99_000, timezone.utc)
        await self.cog.maybe_pause_after_incense_purchase(self.message)
        self.assertEqual(self.cog.bot_state["incense_purchases"]["123"]["1"], 100_000)
        self.cog.save_bot_state.assert_called_once()

    async def test_purchase_survives_reload_with_auto_pause_disabled(self):
        self.cog.bot_state["incense_auto_pause"]["123"] = False
        self.cog.save_bot_state = PokéTwoNamingBot.save_bot_state.__get__(self.cog)
        with TemporaryDirectory() as directory:
            with patch("bot.BOT_STATE_FILE", str(Path(directory) / "state.json")):
                await self.cog.maybe_pause_after_incense_purchase(self.message)
                state = self.cog.load_bot_state()
        self.assertEqual(state["incense_purchases"]["123"]["1"], 100_000)

    async def test_pause_all_skips_expired_and_other_servers_and_continues_on_failure(self):
        now = 100_000
        channels = {1: self.channel, 2: SimpleNamespace(id=2), 3: SimpleNamespace(id=3)}
        self.cog.bot_state["incense_purchases"] = {
            "123": {"1": now, "2": now - 36_000, "3": now - 36_001},
            "456": {"4": now},
        }
        self.cog.has_restricted_permission = Mock(return_value=True)
        response = SimpleNamespace(status=403, reason="Forbidden")
        self.cog.pause_poketwo_channel.side_effect = [
            discord.Forbidden(response, "Missing Permissions"),
            True,
        ]
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123, get_channel=channels.get),
            send=AsyncMock(),
        )

        with patch("bot.time", return_value=now):
            await PokéTwoNamingBot.pause_poketwo_channel_command.callback(
                self.cog, ctx, target="all"
            )

        self.assertEqual(
            [call.args[0].id for call in self.cog.pause_poketwo_channel.await_args_list],
            [1, 2],
        )
        self.assertIn("1 channel(s)", ctx.send.await_args.args[0])
        self.assertIn("Could not pause 1", ctx.send.await_args.args[0])

    async def test_pause_all_reports_no_recent_purchases(self):
        self.cog.bot_state["incense_purchases"] = {"123": {"1": 63_999}}
        self.cog.has_restricted_permission = Mock(return_value=True)
        ctx = SimpleNamespace(guild=SimpleNamespace(id=123), send=AsyncMock())
        with patch("bot.time", return_value=100_000):
            await PokéTwoNamingBot.pause_poketwo_channel_command.callback(
                self.cog, ctx, target="all"
            )
        self.cog.pause_poketwo_channel.assert_not_awaited()
        self.assertIn("no tracked incense purchases", ctx.send.await_args.args[0])

    async def test_pause_all_requires_restricted_permission(self):
        self.cog.has_restricted_permission = Mock(return_value=False)
        ctx = SimpleNamespace(guild=SimpleNamespace(id=123), send=AsyncMock())
        await PokéTwoNamingBot.pause_poketwo_channel_command.callback(
            self.cog, ctx, target="all"
        )
        self.cog.pause_poketwo_channel.assert_not_awaited()
        self.assertIn("do not have permission", ctx.send.await_args.args[0])

    async def test_pause_all_reports_missing_channel_and_pauses_other_channels(self):
        self.cog.bot_state["incense_purchases"] = {"123": {"1": 100_000, "2": 100_000}}
        self.cog.has_restricted_permission = Mock(return_value=True)
        ctx = SimpleNamespace(
            guild=SimpleNamespace(
                id=123, get_channel=lambda channel_id: self.channel if channel_id == 1 else None
            ),
            send=AsyncMock(),
        )
        with patch("bot.time", return_value=100_000):
            await PokéTwoNamingBot.pause_poketwo_channel_command.callback(
                self.cog, ctx, target="all"
            )
        self.cog.pause_poketwo_channel.assert_awaited_once()
        self.assertIn("Could not pause 1", ctx.send.await_args.args[0])

    async def test_single_pause_and_invalid_arguments(self):
        self.cog.has_restricted_permission = Mock(return_value=True)
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123), channel=self.channel, send=AsyncMock()
        )
        await PokéTwoNamingBot.pause_poketwo_channel_command.callback(self.cog, ctx)
        self.cog.pause_poketwo_channel.assert_awaited_once_with(
            self.channel, reason="Staff paused Pokétwo"
        )
        await PokéTwoNamingBot.pause_poketwo_channel_command.callback(
            self.cog, ctx, target="all extra"
        )
        self.cog.pause_poketwo_channel.assert_awaited_once()
        self.assertIn("Usage", ctx.send.await_args.args[0])

    async def test_another_bot_cannot_trigger_pause(self):
        self.message.content = "You purchased an Incense for 50 shards!"
        self.message.author = SimpleNamespace(id=456)
        self.cog.bot = SimpleNamespace(user=SimpleNamespace(id=999))

        await self.cog.on_message(self.message)

        self.cog.pause_poketwo_channel.assert_not_awaited()
        self.channel.send.assert_not_awaited()

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
