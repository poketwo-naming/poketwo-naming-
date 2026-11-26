import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import BUIZIE_USER_ID, PokéTwoNamingBot


class BuizieNamingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot = SimpleNamespace(user=SimpleNamespace(id=999))
        self.channel = SimpleNamespace(send=AsyncMock())
        self.message = SimpleNamespace(
            author=SimpleNamespace(id=BUIZIE_USER_ID),
            content="hello",
            channel=self.channel,
            guild=None,
        )

    async def test_target_message_sends_naming_with_thumbnail(self):
        await self.cog.on_message(self.message)

        self.channel.send.assert_awaited_once()
        sent = self.channel.send.await_args.kwargs
        self.assertIn("Best name: buizie", sent["content"])
        self.assertIn("@Pokétwo#8236 c buizie", sent["content"])
        self.assertEqual(sent["embed"].title, "Catch buizie")
        self.assertEqual(sent["embed"].thumbnail.url, "attachment://buizie.png")
        self.assertEqual(sent["file"].filename, "buizie.png")
        sent["file"].close()

    async def test_other_people_do_not_trigger_response(self):
        self.message.author.id = 123
        await self.cog.on_message(self.message)
        self.channel.send.assert_not_awaited()

    async def test_target_grab_command_still_runs(self):
        self.message.content = "h!grab"
        self.cog.bot.get_context = AsyncMock(return_value="context")
        self.cog.grab_reserves = AsyncMock()
        await self.cog.on_message(self.message)
        self.cog.grab_reserves.assert_awaited_once_with("context", h_mode=True)
        self.channel.send.await_args.kwargs["file"].close()
