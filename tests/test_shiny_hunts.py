import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np

from bot import PokéTwoNamingBot


class ShinyHuntSpeciesDataTests(unittest.TestCase):
    def test_species_mapping_covers_model_and_distinguishes_species(self):
        with open("pokemon_species.json", encoding="utf-8") as file:
            species = json.load(file)
        with np.load("pokemon_image_model.npz", allow_pickle=False) as model:
            self.assertFalse(set(model["classes"]) - set(species))

        for first, second in (
            ("Meowth", "Alolan Meowth"),
            ("Eevee", "Partner Eevee"),
            ("Pikachu", "Peakychu"),
            ("Rotom", "Rotom Phone"),
        ):
            with self.subTest(first=first, second=second):
                self.assertEqual(species[first], species[second])
        self.assertNotEqual(species["Mew"], species["Mewtwo"])
        self.assertNotEqual(species["Dunsparce"], species["Dudunsparce"])


class ShinyHuntTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {"shiny_hunts": {}, "afk": {}}
        self.cog.class_names = {
            name.casefold(): name
            for name in ("Meowth", "Alolan Meowth", "Galarian Meowth", "Mew", "Mewtwo")
        }
        self.cog.pokemon_aliases = {"mauzi": "Meowth"}
        self.cog.pokemon_species = {
            "Meowth": 52,
            "Alolan Meowth": 52,
            "Galarian Meowth": 52,
            "Mew": 151,
            "Mewtwo": 150,
        }
        self.cog.save_bot_state = Mock()
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=456),
            invoked_subcommand=None,
            send=AsyncMock(),
        )

    async def command(self, value):
        await PokéTwoNamingBot.shiny_hunt.callback(
            self.cog, self.ctx, pokemon_name=value
        )

    async def test_all_forms_ping_and_legacy_exact_hunts(self):
        await self.command("all Mauzi")
        self.assertEqual(
            self.cog.bot_state["shiny_hunts"]["123"]["456"],
            {"pokemon": "Meowth", "all_forms": True},
        )
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Alolan Meowth"), ["456"])
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Galarian Meowth"), ["456"])
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Mew"), [])
        self.assertEqual(self.cog.shiny_hunters_for_spawn(999, "Meowth"), [])

        self.cog.bot_state["shiny_hunts"]["123"]["789"] = {"pokemon": "Meowth"}
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Meowth"), ["456", "789"])
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Alolan Meowth"), ["456"])
        self.cog.bot_state["afk"]["456"] = {"shiny_hunt": True}
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Alolan Meowth"), [])

    async def test_all_from_form_excludes_unrelated_species(self):
        await self.command("all Alolan Meowth")
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Meowth"), ["456"])
        await self.command("all Mew")
        view = self.ctx.send.await_args.kwargs["view"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=456),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        await view.confirm_switch.callback(interaction)
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Mew"), ["456"])
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Mewtwo"), [])

    async def test_switching_scope_requires_confirmation_and_can_be_cleared(self):
        await self.command("Meowth")
        await self.command("all Meowth")
        view = self.ctx.send.await_args.kwargs["view"]
        self.assertIn("all Meowth", self.ctx.send.await_args.args[0])
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Alolan Meowth"), [])
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=456),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        await view.confirm_switch.callback(interaction)
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Alolan Meowth"), ["456"])
        await self.command("")
        self.assertIn("all Meowth", self.ctx.send.await_args.args[0])
        await PokéTwoNamingBot.clear_shiny_hunt.callback(self.cog, self.ctx)
        self.assertIn("all Meowth", self.ctx.send.await_args.args[0])
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Meowth"), [])

    async def test_cancel_switch_keeps_all_form_hunt(self):
        await self.command("all Meowth")
        await self.command("Meowth")
        view = self.ctx.send.await_args.kwargs["view"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=456),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        await view.cancel_switch.callback(interaction)
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Alolan Meowth"), ["456"])
        self.assertIn("all Meowth", interaction.response.edit_message.await_args.kwargs["content"])

    async def test_spawn_output_pings_all_form_hunter_unless_reserved(self):
        await self.command("all Meowth")
        self.cog.bot_state["reserves"] = {}
        self.cog.bot_state["collections"] = {}
        self.cog.pokemon_types = {"Alolan Meowth": []}
        self.cog.pokemon_best_names = {"Alolan Meowth": "Meowth"}

        content, _ = self.cog.format_spawn_prediction("Alolan Meowth", 90, 123)
        self.assertIn("Shiny hunt pings: <@456>", content)

        self.cog.bot_state["reserves"] = {"123": {"Alolan Meowth": ["789"]}}
        content, _ = self.cog.format_spawn_prediction("Alolan Meowth", 90, 123)
        self.assertIn("Reserved: <@789>", content)
        self.assertNotIn("<@456>", content)

    async def test_unknown_all_forms_does_not_change_existing_hunt(self):
        await self.command("Meowth")
        await self.command("all NotAPokemon")
        self.assertIn("Unknown Pokémon", self.ctx.send.await_args.args[0])
        self.assertEqual(self.cog.shiny_hunters_for_spawn(123, "Meowth"), ["456"])


if __name__ == "__main__":
    unittest.main()
