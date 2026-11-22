import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import PokéTwoNamingBot


class SpawnRateCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.pokemon_spawn_chances = {
            "pikachu": {
                "Pokemon": "Pikachu",
                "Chance": "1/899",
                "Chance percentage": "0.1112%",
                "Dex": "25",
            }
        }
        self.cog.pokemon_sprite_ids = {"Pikachu": 25}
        self.cog.class_names = {"pikachu": "Pikachu"}
        self.cog.pokemon_aliases = {}
        self.ctx = SimpleNamespace(send=AsyncMock())

    async def command(self, name):
        await PokéTwoNamingBot.spawn_rate_command.callback(
            self.cog,
            self.ctx,
            pokemon_name=name,
        )

    async def test_shows_name_spawn_rate_percentage_and_artwork(self):
        await self.command("pikachu")

        embed = self.ctx.send.await_args.kwargs["embed"]
        self.assertEqual(embed.title, "Pikachu")
        self.assertEqual(embed.fields[0].name, "Spawn rate")
        self.assertEqual(embed.fields[0].value, "1/899 (0.1112%)")
        self.assertEqual(
            embed.thumbnail.url,
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            "sprites/pokemon/other/official-artwork/25.png",
        )

    async def test_reports_unknown_pokemon(self):
        await self.command("Not a Pokémon")

        self.ctx.send.assert_awaited_once_with(
            "❌ Unknown Pokémon: `Not a Pokémon`"
        )

    async def test_requires_a_pokemon_name(self):
        await self.command("  ")

        self.ctx.send.assert_awaited_once_with("Usage: `v!sr <pokemon>`")


class SpawnChanceDataTests(unittest.TestCase):
    def test_loads_spawn_chance_csv_by_case_insensitive_name(self):
        cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)

        chances = cog.load_pokemon_spawn_chances()

        self.assertEqual(chances["pikachu"]["Chance"], "1/899")
        self.assertEqual(chances["pikachu"]["Chance percentage"], "0.1112%")


if __name__ == "__main__":
    unittest.main()
