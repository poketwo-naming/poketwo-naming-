import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from bot import PokéTwoNamingBot

with patch.dict(os.environ, {"DISCORD_TOKEN": "test-token"}):
    import main


class SlashSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_blacklisted_user_normal_message_is_processed_normally(self):
        message = SimpleNamespace(
            author=SimpleNamespace(id=123, mention="<@123>"),
            content="hello everyone",
            channel=SimpleNamespace(send=AsyncMock()),
        )
        cog = SimpleNamespace(is_blacklisted=Mock(return_value=True))

        with (
            patch.object(main.bot, "get_cog", return_value=cog),
            patch.object(main.bot, "process_commands", new_callable=AsyncMock) as process,
        ):
            await main.on_message(message)

        message.channel.send.assert_not_awaited()
        process.assert_awaited_once_with(message)

    async def test_blacklisted_user_command_receives_warning(self):
        message = SimpleNamespace(
            author=SimpleNamespace(id=123, mention="<@123>"),
            content="v!premium",
            channel=SimpleNamespace(send=AsyncMock()),
        )
        cog = SimpleNamespace(is_blacklisted=Mock(return_value=True))

        with (
            patch.object(main.bot, "get_cog", return_value=cog),
            patch.object(main.bot, "process_commands", new_callable=AsyncMock) as process,
        ):
            await main.on_message(message)

        message.channel.send.assert_awaited_once()
        self.assertIn("blacklisted", message.channel.send.await_args.args[0])
        process.assert_not_awaited()

    async def test_ready_syncs_global_slash_commands(self):
        commands = [SimpleNamespace(name="dc")]

        with (
            patch.object(main.bot.tree, "sync", AsyncMock(return_value=commands)) as sync,
            patch("main.run_update_announcement", new_callable=AsyncMock),
            patch(
                "main.asyncio.create_task",
                side_effect=lambda coroutine: coroutine.close(),
            ),
        ):
            await main.on_ready()

        sync.assert_awaited_once_with()

    async def test_ready_reports_sync_failures(self):
        with (
            patch.object(
                main.bot.tree,
                "sync",
                AsyncMock(side_effect=RuntimeError("sync failed")),
            ),
            patch("main.run_update_announcement", new_callable=AsyncMock),
            patch(
                "main.asyncio.create_task",
                side_effect=lambda coroutine: coroutine.close(),
            ),
            self.assertRaisesRegex(RuntimeError, "sync failed"),
        ):
            await main.on_ready()

    async def test_entry_point_error_upserts_commands_without_bulk_retry(self):
        response = SimpleNamespace(status=400, reason="Bad Request")
        error = discord.HTTPException(
            response, {"code": 50240, "message": "Entry Point must be included"}
        )
        command = PokéTwoNamingBot.slash_daycare
        with (
            patch.object(main.bot.tree, "sync", AsyncMock(side_effect=error)) as sync,
            patch.object(main.bot.tree, "get_commands", return_value=[command]),
            patch.object(main.bot._connection, "application_id", 123),
            patch.object(main.bot.http, "upsert_global_command", new_callable=AsyncMock) as upsert,
        ):
            count = await main.sync_global_commands()
        self.assertEqual(count, 1)
        sync.assert_awaited_once()
        payload = upsert.await_args.kwargs["payload"]
        self.assertEqual(upsert.await_args.args, (123,))
        self.assertEqual(payload["name"], "dc")
        self.assertEqual(payload["integration_types"], [0, 1])
        self.assertEqual(payload["contexts"], [0, 1, 2])
        self.assertEqual([option["name"] for option in payload["options"]], ["box", "count"])

    async def test_other_discord_errors_do_not_use_fallback(self):
        response = SimpleNamespace(status=403, reason="Forbidden")
        error = discord.HTTPException(response, {"code": 50001, "message": "No access"})
        with (
            patch.object(main.bot.tree, "sync", AsyncMock(side_effect=error)),
            patch.object(main.bot.http, "upsert_global_command", new_callable=AsyncMock) as upsert,
        ):
            with self.assertRaises(discord.HTTPException):
                await main.sync_global_commands()
        upsert.assert_not_awaited()

    async def test_fallback_upsert_failure_is_reported(self):
        response = SimpleNamespace(status=400, reason="Bad Request")
        entry_point_error = discord.HTTPException(response, {"code": 50240, "message": "Entry Point"})
        command = Mock()
        command.to_dict.return_value = {"name": "dc", "type": 1}
        with (
            patch.object(main.bot.tree, "sync", AsyncMock(side_effect=entry_point_error)),
            patch.object(main.bot.tree, "get_commands", return_value=[command]),
            patch.object(main.bot._connection, "application_id", 123),
            patch.object(main.bot.http, "upsert_global_command", AsyncMock(side_effect=entry_point_error)),
            self.assertRaises(discord.HTTPException),
        ):
            await main.sync_global_commands()
