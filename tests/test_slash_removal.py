import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, {"DISCORD_TOKEN": "test-token"}):
    import main


class SlashSyncTests(unittest.IsolatedAsyncioTestCase):
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
