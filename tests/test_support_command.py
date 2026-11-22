import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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

    async def test_guild_join_sends_welcome_then_support_in_system_channel(self):
        cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        permissions = SimpleNamespace(
            view_channel=True, send_messages=True, embed_links=True
        )
        channel = SimpleNamespace(
            permissions_for=Mock(return_value=permissions), send=AsyncMock()
        )
        guild = SimpleNamespace(
            id=123, me=object(), system_channel=channel, text_channels=[channel]
        )

        await cog.on_guild_join(guild)

        sent = channel.send.await_args.kwargs
        self.assertEqual(len(sent["embeds"]), 2)
        welcome, support = sent["embeds"]
        self.assertIn("Thank you for inviting Vivillon", welcome.description)
        self.assertIn("Pokétwo spawns", welcome.description)
        self.assertIn("https://discord.gg/butterflygarden", welcome.description)
        self.assertIn("open a ticket", welcome.description)
        self.assertIn("issues or questions", welcome.description)
        self.assertIn("open a ticket there for help", welcome.description)
        self.assertEqual(support.title, "Support Vivillon")
        self.assertEqual(sent["view"].children[0].url, "https://gofund.me/40e29e0bf")
        channel.send.assert_awaited_once()

    async def test_guild_join_falls_back_when_system_channel_fails(self):
        cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        permissions = SimpleNamespace(
            view_channel=True, send_messages=True, embed_links=True
        )
        error = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "Missing permissions"
        )
        system = SimpleNamespace(
            id=1, permissions_for=Mock(return_value=permissions),
            send=AsyncMock(side_effect=error),
        )
        fallback = SimpleNamespace(
            id=2, permissions_for=Mock(return_value=permissions), send=AsyncMock()
        )
        guild = SimpleNamespace(
            id=123, me=object(), system_channel=system,
            text_channels=[system, fallback],
        )

        with patch("builtins.print"):
            await cog.on_guild_join(guild)

        system.send.assert_awaited_once()
        fallback.send.assert_awaited_once()

    async def test_guild_join_logs_when_no_channel_has_permissions(self):
        cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        channel = SimpleNamespace(
            permissions_for=Mock(return_value=SimpleNamespace(
                view_channel=True, send_messages=True, embed_links=False
            )),
            send=AsyncMock(),
        )
        guild = SimpleNamespace(
            id=123, me=object(), system_channel=None, text_channels=[channel]
        )

        with patch("builtins.print") as log:
            await cog.on_guild_join(guild)

        channel.send.assert_not_awaited()
        log.assert_called_once()
        self.assertIn("guild 123", log.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
