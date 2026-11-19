import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

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

        self.ctx.send.assert_awaited_once_with(
            "**Pikachu** is reserved by <@456>, <@789>."
        )


if __name__ == "__main__":
    unittest.main()
