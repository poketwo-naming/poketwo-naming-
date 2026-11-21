import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from bot import PokéTwoNamingBot


class SupportCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_support_replies_with_donation_embed_and_link_button(self):
        cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        ctx = SimpleNamespace(reply=AsyncMock())

        await PokéTwoNamingBot.support.callback(cog, ctx)

        ctx.reply.assert_awaited_once()
        sent = ctx.reply.await_args.kwargs
        self.assertEqual(sent["embed"].title, "Support Vivillon")
        self.assertEqual(
            sent["embed"].description,
            "🦋 Running and developing Vivillon costs money. Donations are "
            "completely optional, but every bit of support helps keep the bot "
            "running. Thank you!",
        )
        self.assertEqual(len(sent["view"].children), 1)
        button = sent["view"].children[0]
        self.assertIsInstance(button, discord.ui.Button)
        self.assertEqual(button.label, "Donate on GoFundMe")
        self.assertEqual(button.url, "https://gofund.me/40e29e0bf")


if __name__ == "__main__":
    unittest.main()
