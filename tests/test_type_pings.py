import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from bot import PokéTwoNamingBot, TYPE_EMOJIS, TYPE_NAMES, TypePingView


class TypePingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {
            "type_pings": {},
            "afk": {},
            "reserves": {},
            "shiny_hunts": {},
            "collections": {},
        }
        self.cog.pokemon_types = {
            "Bulbasaur": ["grass", "poison"],
            "Charmander": ["fire"],
        }
        self.cog.pokemon_best_names = {
            "Bulbasaur": "Bulbasaur",
            "Charmander": "Charmander",
        }
        self.cog.save_bot_state = Mock()
        self.user_id = 456

    def interaction(self, user_id=None):
        return SimpleNamespace(
            user=SimpleNamespace(id=user_id or self.user_id),
            response=SimpleNamespace(
                edit_message=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )

    async def test_menu_displays_all_types_and_initial_off_state(self):
        view = TypePingView(self.cog, self.user_id)

        self.assertEqual(view.build_embed().title, "Type Pings")
        self.assertIn(f"{TYPE_EMOJIS['bug']} Bug ❌", view.build_embed().description)
        self.assertEqual(len(view.children[0].options), len(TYPE_NAMES))
        self.assertEqual(
            [button.label for button in view.children[1:]],
            ["All On", "All Off"],
        )
        self.assertFalse(any(option.default for option in view.children[0].options))

    async def test_select_and_all_buttons_update_saved_types(self):
        view = TypePingView(self.cog, self.user_id)
        select = view.children[0]
        select._values = ["grass", "poison"]
        interaction = self.interaction()

        await select.callback(interaction)

        self.assertEqual(
            self.cog.bot_state["type_pings"][str(self.user_id)],
            ["grass", "poison"],
        )
        self.assertEqual(self.cog.save_bot_state.call_count, 1)
        self.assertTrue(
            all(
                option.default == (option.value in {"grass", "poison"})
                for option in view.children[0].options
            )
        )

        await view.children[1].callback(interaction)
        self.assertEqual(
            self.cog.bot_state["type_pings"][str(self.user_id)],
            list(TYPE_NAMES),
        )
        await view.children[2].callback(interaction)
        self.assertEqual(self.cog.bot_state["type_pings"][str(self.user_id)], [])

    async def test_other_user_cannot_change_settings(self):
        view = TypePingView(self.cog, self.user_id)

        await view.children[1].callback(self.interaction(user_id=789))

        self.cog.save_bot_state.assert_not_called()
        self.assertEqual(self.cog.bot_state["type_pings"], {})

    async def test_dual_type_spawn_pings_each_matching_user_once(self):
        self.cog.bot_state["type_pings"] = {
            "456": ["grass", "poison"],
            "789": ["water"],
        }

        content, _ = self.cog.format_spawn_prediction("Bulbasaur", 99.0, 123)

        self.assertIn("Type pings: <@456>", content)
        self.assertNotIn("<@789>", content)
        self.assertEqual(self.cog.type_ping_owners("Bulbasaur"), ["456"])

    async def test_type_ping_respects_user_ping_preference(self):
        self.cog.bot_state["type_pings"] = {
            "456": ["grass"],
            "789": ["grass"],
        }
        self.cog.bot_state["afk"] = {
            "789": {"typeping": True},
        }

        content, _ = self.cog.format_spawn_prediction("Bulbasaur", 99.0, 123)

        self.assertIn("Type pings: <@456>", content)
        self.assertNotIn("<@789>", content)
        self.assertEqual(self.cog.type_ping_owners("Bulbasaur"), ["456"])

    async def test_reserve_override_hides_type_pings(self):
        self.cog.bot_state["type_pings"] = {
            "456": ["grass"],
        }
        self.cog.bot_state["reserves"] = {
            "123": {
                "Bulbasaur": "789",
            }
        }

        content, _ = self.cog.format_spawn_prediction("Bulbasaur", 99.0, 123)

        self.assertIn("Reserved: <@789>", content)
        self.assertNotIn("Type pings:", content)


if __name__ == "__main__":
    unittest.main()
