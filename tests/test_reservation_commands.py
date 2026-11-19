import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from bot import PokéTwoNamingBot


class ReservationCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {
            "categories": {"123": {"featured": ["Pikachu", "Eevee"]}},
            "reserves": {
                "123": {
                    "Pikachu": ["456", "789"],
                    "Eevee": "456",
                }
            },
        }
        self.cog.class_names = {"pikachu": "Pikachu"}
        self.cog.pokemon_aliases = {}
        self.cog.has_restricted_permission = lambda ctx: True
        self.cog.save_bot_state = lambda: None
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(
                id=123,
                get_member=lambda user_id: None,
            ),
            send=AsyncMock(),
        )

    async def test_remove_category_removes_all_category_reservations(self):
        await self.cog.remove_reserve(self.ctx, entry="featured")

        self.assertNotIn("Pikachu", self.cog.bot_state["reserves"]["123"])
        self.assertNotIn("Eevee", self.cog.bot_state["reserves"]["123"])
        self.ctx.send.assert_awaited_once()

    async def test_search_shows_every_reserving_member(self):
        await self.cog.search_reserve(self.ctx, "Pikachu")

        self.ctx.send.assert_awaited_once()
        embed = self.ctx.send.await_args.kwargs["embed"]
        self.assertIsInstance(embed, discord.Embed)
        self.assertEqual(embed.title, "Pikachu Reservations")
        self.assertEqual(embed.description, "• <@456>\n• <@789>")
        self.assertEqual(embed.footer.text, "2 reserving members")

    async def test_search_shows_unreserved_result_in_an_embed(self):
        self.cog.bot_state["reserves"]["123"].pop("Pikachu")

        await self.cog.search_reserve(self.ctx, "Pikachu")

        self.ctx.send.assert_awaited_once()
        embed = self.ctx.send.await_args.kwargs["embed"]
        self.assertIsInstance(embed, discord.Embed)
        self.assertEqual(embed.title, "Pikachu Reservations")
        self.assertEqual(
            embed.description,
            "No members have reserved this Pokémon.",
        )

    def test_missingno_prediction_includes_reserve_ping(self):
        self.cog.bot_state["reserves"]["123"]["MissingNo"] = ["456"]
        self.cog.pokemon_types = {"MissingNo": []}
        self.cog.pokemon_best_names = {"MissingNo": "MissingNo"}

        content, embed = self.cog.format_spawn_prediction(
            "MissingNo",
            99.0,
            guild_id=123,
        )

        self.assertIn("Reserved: <@456>", content)
        self.assertIn("Do not catch this Pokémon.", content)
        self.assertNotIn("Click to Copy", content)
        self.assertEqual(embed.title, "MissingNo detected")


if __name__ == "__main__":
    unittest.main()
