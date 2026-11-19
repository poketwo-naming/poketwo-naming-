import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from bot import GrabReservesView, PokéTwoNamingBot


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

    def test_grab_parser_preserves_custom_emoji_and_all_forms(self):
        message = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            content=(
                "<@456> <:party_pikachu:123456789> all Pikachu"
            ),
            embeds=[],
            message_snapshots=[],
        )

        entries = self.cog.parse_grab_list(message, 123)

        self.assertEqual(
            entries,
            [
                (
                    "456",
                    "Pikachu",
                    True,
                    False,
                    "<:party_pikachu:123456789>",
                )
            ],
        )

    async def test_grab_preview_hides_users_and_uses_source_emoji(self):
        self.cog.resolve_pokemon_family = (
            lambda name, include_regionals=True: [
            "Pikachu",
            "Cosplay Pikachu",
            ]
        )
        view = GrabReservesView(
            self.cog,
            789,
            101112,
            [
                (
                    "456",
                    "Pikachu",
                    True,
                    False,
                    "<:party_pikachu:123456789>",
                )
            ],
        )

        initial_description = view.build_embed().description or ""
        self.assertNotIn("<@456>", initial_description)
        self.assertEqual(
            initial_description,
            "Pikachu\nCosplay Pikachu",
        )
        view.custom_emoji = True
        emoji_description = view.build_embed().description or ""
        self.assertEqual(
            emoji_description,
            "<:party_pikachu:123456789> Pikachu\n"
            "<:party_pikachu:123456789> Cosplay Pikachu",
        )
        self.assertIn(
            "<@456>",
            view.format_line(
                "456",
                "Pikachu",
                custom_emoji="<:party_pikachu:123456789>",
            ),
        )

    async def test_exchange_expands_all_forms_in_replied_list(self):
        self.cog.class_names = {
            "pikachu": "Pikachu",
            "cosplay pikachu": "Cosplay Pikachu",
        }
        source = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            content="Pikachu all - <@456>",
            embeds=[],
            message_snapshots=[],
        )
        self.cog.referenced_grab_message = AsyncMock(return_value=source)
        self.cog.bot_state["reserves"]["123"] = {
            "Pikachu": ["789"],
            "Cosplay Pikachu": ["789"],
        }
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=101),
            send=AsyncMock(),
        )

        await self.cog.exchange_reserves(ctx, "<@789>")

        view = ctx.send.await_args.kwargs["view"]
        self.assertEqual(
            view.entries,
            [("456", "Cosplay Pikachu"), ("456", "Pikachu")],
        )


if __name__ == "__main__":
    unittest.main()
