import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from bot import PokéTwoNamingBot

with patch.dict(os.environ, {"DISCORD_TOKEN": "test-token"}):
    from main import remove_old_slash_commands


class SlashRemovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_removes_old_slash_commands_only(self):
        old = SimpleNamespace(
            name="box", type=discord.AppCommandType.chat_input, delete=AsyncMock()
        )
        other = SimpleNamespace(
            name="unrelated", type=discord.AppCommandType.chat_input, delete=AsyncMock()
        )
        activity = SimpleNamespace(
            name="box", type=4,
            delete=AsyncMock(),
        )
        tree = SimpleNamespace(fetch_commands=AsyncMock(return_value=[old, other, activity]))

        self.assertEqual(await remove_old_slash_commands(tree), 1)
        old.delete.assert_awaited_once()
        other.delete.assert_not_awaited()
        activity.delete.assert_not_awaited()

    async def test_delete_failures_are_reported(self):
        command = SimpleNamespace(
            name="dc", type=discord.AppCommandType.chat_input,
            delete=AsyncMock(side_effect=RuntimeError("failed")),
        )
        tree = SimpleNamespace(fetch_commands=AsyncMock(return_value=[command]))
        with self.assertRaisesRegex(RuntimeError, "failed"):
            await remove_old_slash_commands(tree)

    def test_cog_registers_no_slash_commands(self):
        self.assertEqual(PokéTwoNamingBot.__cog_app_commands__, [])
