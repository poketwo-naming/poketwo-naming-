import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from discord.ext import commands

from bot import PokéTwoNamingBot

with patch.dict(os.environ, {"DISCORD_TOKEN": "test-token"}):
    from main import register_daycare_command, remove_old_slash_commands


class SlashRemovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_removes_old_slash_commands_only(self):
        old = SimpleNamespace(
            name="box", type=discord.AppCommandType.chat_input, delete=AsyncMock()
        )
        other = SimpleNamespace(
            name="unrelated", type=discord.AppCommandType.chat_input, delete=AsyncMock()
        )
        daycare = SimpleNamespace(
            name="dc", type=discord.AppCommandType.chat_input, delete=AsyncMock()
        )
        activity = SimpleNamespace(
            name="box", type=4,
            delete=AsyncMock(),
        )
        tree = SimpleNamespace(
            fetch_commands=AsyncMock(return_value=[old, other, daycare, activity])
        )

        self.assertEqual(await remove_old_slash_commands(tree), 1)
        old.delete.assert_awaited_once()
        other.delete.assert_not_awaited()
        daycare.delete.assert_not_awaited()
        activity.delete.assert_not_awaited()

    async def test_delete_failures_are_reported(self):
        command = SimpleNamespace(
            name="box", type=discord.AppCommandType.chat_input,
            delete=AsyncMock(side_effect=RuntimeError("failed")),
        )
        tree = SimpleNamespace(fetch_commands=AsyncMock(return_value=[command]))
        with self.assertRaisesRegex(RuntimeError, "failed"):
            await remove_old_slash_commands(tree)

    async def test_only_daycare_is_registered_without_bulk_sync(self):
        client = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        client._connection.application_id = 123
        cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        for command in cog.__cog_app_commands__:
            client.tree.add_command(command)
        with patch.object(
            client.tree._http, "upsert_global_command", new_callable=AsyncMock
        ) as upsert:
            await register_daycare_command(client.tree)
        payload = upsert.await_args.kwargs["payload"]
        self.assertEqual([command.name for command in cog.__cog_app_commands__], ["dc"])
        self.assertEqual(payload["name"], "dc")
        self.assertEqual([option["name"] for option in payload["options"]], ["box", "count"])
        self.assertTrue(payload["options"][0]["autocomplete"])
        self.assertEqual(payload["options"][1]["min_value"], 1)
