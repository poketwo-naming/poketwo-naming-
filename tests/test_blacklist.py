import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import discord
from discord.ext import commands

from bot import PokéTwoNamingBot


class BlacklistCommandCallback:
    async def __call__(self, cog: PokéTwoNamingBot, ctx: commands.Context, *, user_input: str) -> None: ...


class BlacklistCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {
            "blacklist": [],
        }
        self.cog.has_restricted_permission = lambda ctx: True
        self.cog.save_bot_state = lambda: None
        self.ctx = SimpleNamespace(
            send=AsyncMock(),
            author=SimpleNamespace(id=123, mention="<@123>"),
        )

    async def blacklist_user(self, user_input: str):
        callback = cast(BlacklistCommandCallback, PokéTwoNamingBot.blacklist_command.callback)
        await callback(self.cog, cast(commands.Context, self.ctx), user_input=user_input)

    async def show_blacklist(self):
        callback = cast(BlacklistCommandCallback, PokéTwoNamingBot.show_blacklist.callback)
        await callback(self.cog, cast(commands.Context, self.ctx))

    async def test_blacklist_user_by_mention(self):
        await self.blacklist_user("<@456>")

        self.assertIn(456, self.cog.bot_state["blacklist"])
        self.ctx.send.assert_awaited_once()
        message = self.ctx.send.await_args.args[0]
        self.assertIn("✅", message)
        self.assertIn("456", message)

    async def test_blacklist_user_by_id(self):
        await self.blacklist_user("789")

        self.assertIn(789, self.cog.bot_state["blacklist"])
        self.ctx.send.assert_awaited_once()

    async def test_blacklist_already_blacklisted_user(self):
        self.cog.bot_state["blacklist"] = [456]

        await self.blacklist_user("<@456>")

        message = self.ctx.send.await_args.args[0]
        self.assertIn("❌", message)
        self.assertIn("already blacklisted", message)

    async def test_blacklist_no_input(self):
        await self.blacklist_user("")

        self.ctx.send.assert_awaited_once()
        message = self.ctx.send.await_args.args[0]
        self.assertIn("Usage", message)

    async def test_blist_shows_empty_blacklist(self):
        await self.show_blacklist()

        self.ctx.send.assert_awaited_once()
        message = self.ctx.send.await_args.args[0]
        self.assertIn("No users", message)

    async def test_blist_shows_blacklisted_users(self):
        self.cog.bot_state["blacklist"] = [111, 222, 333]

        await self.show_blacklist()

        self.ctx.send.assert_awaited_once()
        embed = self.ctx.send.await_args.kwargs["embed"]
        self.assertIsInstance(embed, discord.Embed)
        self.assertEqual(embed.title, "Blacklisted Users")
        self.assertIn("3 user(s) blacklisted", embed.footer.text)

    async def test_is_blacklisted_returns_true_for_blacklisted_user(self):
        self.cog.bot_state["blacklist"] = [456]

        is_blacklisted = self.cog.is_blacklisted(456)

        self.assertTrue(is_blacklisted)

    async def test_is_blacklisted_returns_false_for_non_blacklisted_user(self):
        self.cog.bot_state["blacklist"] = [456]

        is_blacklisted = self.cog.is_blacklisted(789)

        self.assertFalse(is_blacklisted)


if __name__ == "__main__":
    unittest.main()

