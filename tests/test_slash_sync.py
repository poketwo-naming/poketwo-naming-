import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands

from bot import PokéTwoNamingBot

with patch.dict(os.environ, {"DISCORD_TOKEN": "test-token"}):
    from main import sync_application_commands


def http_error(code):
    return discord.HTTPException(
        SimpleNamespace(status=400, reason="Bad Request"),
        {"code": code, "message": "sync failed"},
    )


class SlashSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_sync_does_not_upsert_individually(self):
        tree = SimpleNamespace(
            sync=AsyncMock(return_value=[object()]),
            _http=SimpleNamespace(upsert_global_command=AsyncMock()),
        )
        self.assertEqual(await sync_application_commands(tree), 1)
        tree._http.upsert_global_command.assert_not_awaited()

    async def test_entry_point_error_upserts_all_global_commands(self):
        dc = Mock()
        dc.to_dict.return_value = {"name": "dc", "description": "daycare"}
        box = Mock()
        box.to_dict.return_value = {"name": "box", "description": "boxes"}
        tree = SimpleNamespace(
            sync=AsyncMock(side_effect=http_error(50240)),
            client=SimpleNamespace(application_id=123),
            get_commands=Mock(return_value=[dc, box]),
            translator=None,
            _http=SimpleNamespace(upsert_global_command=AsyncMock()),
        )
        self.assertEqual(await sync_application_commands(tree), 2)
        self.assertEqual(
            tree._http.upsert_global_command.await_args_list,
            [
                unittest.mock.call(123, payload={"name": "dc", "description": "daycare"}),
                unittest.mock.call(123, payload={"name": "box", "description": "boxes"}),
            ],
        )

    async def test_other_http_errors_are_not_hidden(self):
        tree = SimpleNamespace(sync=AsyncMock(side_effect=http_error(50001)))
        with self.assertRaises(discord.HTTPException):
            await sync_application_commands(tree)

    async def test_failed_individual_upsert_is_not_hidden(self):
        command = Mock()
        command.to_dict.return_value = {"name": "dc"}
        tree = SimpleNamespace(
            sync=AsyncMock(side_effect=http_error(50240)),
            client=SimpleNamespace(application_id=123),
            get_commands=Mock(return_value=[command]),
            translator=None,
            _http=SimpleNamespace(
                upsert_global_command=AsyncMock(side_effect=http_error(50001))
            ),
        )
        with self.assertRaises(discord.HTTPException):
            await sync_application_commands(tree)

    async def test_entry_point_fallback_registers_real_breeding_commands(self):
        client = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        client._connection.application_id = 123
        cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        for command in cog.__cog_app_commands__:
            client.tree.add_command(command)
        with (
            patch.object(client.tree, "sync", AsyncMock(side_effect=http_error(50240))),
            patch.object(
                client.tree._http, "upsert_global_command", new_callable=AsyncMock
            ) as upsert,
        ):
            await sync_application_commands(client.tree)

        payloads = {call.kwargs["payload"]["name"]: call.kwargs["payload"]
                    for call in upsert.await_args_list}
        self.assertTrue({"box", "dc", "boxhelp"}.issubset(payloads))
        self.assertEqual(
            {option["name"] for option in payloads["dc"]["options"]},
            {"box_name", "settings"},
        )
