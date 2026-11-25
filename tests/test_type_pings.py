import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands
from discord.ext.commands.view import StringView

from bot import (
    PokéTwoNamingBot,
    QuestPingView,
    TYPE_EMOJIS,
    TYPE_NAMES,
    TypePingView,
)


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

    async def invoke_ping_command(self, command, arguments=""):
        ctx = SimpleNamespace(
            author=SimpleNamespace(id=self.user_id),
            message=SimpleNamespace(attachments=[]),
            view=StringView(arguments),
            send=AsyncMock(),
        )
        await command._parse_arguments(ctx)
        await command.callback(self.cog, *ctx.args, **ctx.kwargs)
        return ctx

    async def test_type_command_adds_names_and_menu_reflects_saved_selection(self):
        self.cog.bot_state["type_pings"]["456"] = ["grass"]
        ctx = await self.invoke_ping_command(
            PokéTwoNamingBot.type_ping_command, "Water FIRE fairy water"
        )

        self.assertEqual(
            self.cog.bot_state["type_pings"]["456"],
            ["fairy", "fire", "grass", "water"],
        )
        view = ctx.send.await_args.kwargs["view"]
        self.assertIsInstance(view, TypePingView)
        self.assertEqual(
            {option.value for option in view.children[0].options if option.default},
            {"fairy", "fire", "grass", "water"},
        )
        self.assertEqual(self.cog.type_ping_owners("Charmander"), ["456"])
        ctx = await self.invoke_ping_command(PokéTwoNamingBot.type_ping_command)
        self.assertIn("Water ✅", ctx.send.await_args.kwargs["embed"].description)
        self.cog.save_bot_state.assert_called_once()

    async def test_region_command_adds_names_and_menu_reflects_saved_selection(self):
        self.cog.bot_state["quest_pings"] = {"456": ["Alola"]}
        ctx = await self.invoke_ping_command(
            PokéTwoNamingBot.quest_ping_command, "kanto JOHTO kanto"
        )

        self.assertEqual(
            self.cog.bot_state["quest_pings"]["456"], ["Alola", "Johto", "Kanto"]
        )
        view = ctx.send.await_args.kwargs["view"]
        self.assertIsInstance(view, QuestPingView)
        self.assertEqual(
            {option.value for option in view.children[0].options if option.default},
            {"Alola", "Johto", "Kanto"},
        )
        self.assertEqual(self.cog.quest_ping_owners("Alolan Raichu"), ["456"])
        ctx = await self.invoke_ping_command(PokéTwoNamingBot.quest_ping_command)
        self.assertIn("Kanto ✅", ctx.send.await_args.kwargs["embed"].description)
        self.cog.save_bot_state.assert_called_once()

    async def test_invalid_names_do_not_change_either_selection(self):
        for command, state_key, existing, arguments in (
            (PokéTwoNamingBot.type_ping_command, "type_pings", ["grass"], "fire typo"),
            (PokéTwoNamingBot.quest_ping_command, "quest_pings", ["Alola"], "kanto typo"),
        ):
            with self.subTest(state_key=state_key):
                self.cog.bot_state[state_key] = {"456": existing}
                ctx = await self.invoke_ping_command(command, arguments)
                self.assertEqual(self.cog.bot_state[state_key]["456"], existing)
                self.assertIn("typo", ctx.send.await_args.args[0])
        self.cog.save_bot_state.assert_not_called()

    async def test_remove_names_updates_selection_and_menu(self):
        for command, state_key, existing, arguments, expected in (
            (PokéTwoNamingBot.type_ping_command, "type_pings",
             ["fire", "grass", "water"], "remove FIRE water fire", ["grass"]),
            (PokéTwoNamingBot.quest_ping_command, "quest_pings",
             ["Alola", "Johto", "Kanto"], "REMOVE kanto JOHTO kanto", ["Alola"]),
        ):
            with self.subTest(state_key=state_key):
                self.cog.bot_state[state_key] = {"456": existing}
                ctx = await self.invoke_ping_command(command, arguments)
                self.assertEqual(self.cog.bot_state[state_key]["456"], expected)
                view = ctx.send.await_args.kwargs["view"]
                self.assertEqual(
                    [option.value for option in view.children[0].options if option.default],
                    expected,
                )
        self.assertEqual(self.cog.save_bot_state.call_count, 2)

    async def test_removing_last_and_unselected_names_stops_pings(self):
        self.cog.bot_state["type_pings"]["456"] = ["fire"]
        self.cog.bot_state["quest_pings"] = {"456": ["Alola"]}

        await self.invoke_ping_command(
            PokéTwoNamingBot.type_ping_command, "remove fire water"
        )
        await self.invoke_ping_command(
            PokéTwoNamingBot.quest_ping_command, "remove alola kanto"
        )

        self.assertEqual(self.cog.bot_state["type_pings"]["456"], [])
        self.assertEqual(self.cog.bot_state["quest_pings"]["456"], [])
        self.assertEqual(self.cog.type_ping_owners("Charmander"), [])
        self.assertEqual(self.cog.quest_ping_owners("Alolan Raichu"), [])

    async def test_remove_invalid_or_missing_names_does_not_change_selection(self):
        for command, state_key, existing, arguments in (
            (PokéTwoNamingBot.type_ping_command, "type_pings", ["fire"], "remove fire typo"),
            (PokéTwoNamingBot.quest_ping_command, "quest_pings", ["Kanto"], "remove kanto typo"),
            (PokéTwoNamingBot.type_ping_command, "type_pings", ["fire"], "remove"),
            (PokéTwoNamingBot.quest_ping_command, "quest_pings", ["Kanto"], "remove"),
        ):
            with self.subTest(state_key=state_key, arguments=arguments):
                self.cog.bot_state[state_key] = {"456": existing}
                ctx = await self.invoke_ping_command(command, arguments)
                self.assertEqual(self.cog.bot_state[state_key]["456"], existing)
                self.assertTrue(ctx.send.await_args.args[0].startswith("❌"))
        self.cog.save_bot_state.assert_not_called()

    async def test_remove_save_failure_restores_previous_selection(self):
        for command, state_key, existing, arguments in (
            (PokéTwoNamingBot.type_ping_command, "type_pings", ["fire"], "remove fire"),
            (PokéTwoNamingBot.quest_ping_command, "quest_pings", ["Kanto"], "remove kanto"),
        ):
            with self.subTest(state_key=state_key):
                self.cog.bot_state[state_key] = {"456": existing}
                self.cog.save_bot_state.side_effect = OSError("disk full")
                with self.assertLogs("bot", level="ERROR"):
                    ctx = await self.invoke_ping_command(command, arguments)
                self.assertEqual(self.cog.bot_state[state_key]["456"], existing)
                self.assertIn("couldn't save", ctx.send.await_args.args[0])

    async def test_slash_ping_commands_have_add_and_remove_options(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        for command, name in (
            (PokéTwoNamingBot.slash_type_ping, "tp"),
            (PokéTwoNamingBot.slash_quest_ping, "qp"),
        ):
            with self.subTest(name=name):
                payload = command.to_dict(bot.tree)
                self.assertEqual(payload["name"], name)
                self.assertEqual(
                    [option["name"] for option in payload["options"]],
                    ["add", "remove"],
                )
                self.assertEqual(payload["integration_types"], [0, 1])
                self.assertEqual(payload["contexts"], [0, 1, 2])

    async def test_slash_ping_commands_register_with_cog(self):
        bot = commands.Bot(
            command_prefix="!", intents=discord.Intents.default(), help_command=None
        )
        with patch.object(PokéTwoNamingBot, "cog_load", new_callable=AsyncMock):
            await bot.add_cog(self.cog)
        self.assertIsNotNone(bot.tree.get_command("tp"))
        self.assertIsNotNone(bot.tree.get_command("qp"))

    async def test_slash_and_prefix_commands_update_same_selections(self):
        for prefix, slash, state_key, added, removed in (
            (PokéTwoNamingBot.type_ping_command, PokéTwoNamingBot.slash_type_ping,
             "type_pings", "fire", "water"),
            (PokéTwoNamingBot.quest_ping_command, PokéTwoNamingBot.slash_quest_ping,
             "quest_pings", "Kanto", "Johto"),
        ):
            with self.subTest(state_key=state_key):
                await self.invoke_ping_command(prefix, added)
                await slash.callback(self.cog, self.interaction(), remove=added)
                self.assertEqual(self.cog.bot_state[state_key]["456"], [])
                await slash.callback(self.cog, self.interaction(), add=removed)
                await self.invoke_ping_command(prefix, f"remove {removed}")
                self.assertEqual(self.cog.bot_state[state_key]["456"], [])

    async def test_slash_add_and_remove_share_prefix_selections(self):
        for command, state_key, existing, add, remove, expected in (
            (PokéTwoNamingBot.slash_type_ping, "type_pings", ["fire", "grass"],
             "water FAIRY", "FIRE", ["fairy", "grass", "water"]),
            (PokéTwoNamingBot.slash_quest_ping, "quest_pings", ["Alola", "Kanto"],
             "johto", "ALOLA", ["Johto", "Kanto"]),
        ):
            with self.subTest(state_key=state_key):
                self.cog.bot_state[state_key] = {"456": existing}
                interaction = self.interaction()
                await command.callback(self.cog, interaction, add=add, remove=remove)
                self.assertEqual(self.cog.bot_state[state_key]["456"], expected)
                response = interaction.response.send_message.await_args.kwargs
                self.assertTrue(response["ephemeral"])
                self.assertEqual(
                    {option.value for option in response["view"].children[0].options
                     if option.default},
                    set(expected),
                )
        self.assertEqual(self.cog.save_bot_state.call_count, 2)

    async def test_slash_invalid_empty_and_conflicting_options_do_not_save(self):
        for command, state_key, existing, add, remove in (
            (PokéTwoNamingBot.slash_type_ping, "type_pings", ["fire"], "water", "typo"),
            (PokéTwoNamingBot.slash_quest_ping, "quest_pings", ["Kanto"], " ", None),
            (PokéTwoNamingBot.slash_type_ping, "type_pings", ["fire"], "FIRE", "fire"),
        ):
            with self.subTest(state_key=state_key, add=add, remove=remove):
                self.cog.bot_state[state_key] = {"456": existing}
                interaction = self.interaction()
                await command.callback(self.cog, interaction, add=add, remove=remove)
                self.assertEqual(self.cog.bot_state[state_key]["456"], existing)
                self.assertTrue(
                    interaction.response.send_message.await_args.args[0].startswith("❌")
                )
        self.cog.save_bot_state.assert_not_called()

    async def test_slash_ping_menu_and_save_failure(self):
        self.cog.bot_state["type_pings"]["456"] = ["fire"]
        interaction = self.interaction()
        await PokéTwoNamingBot.slash_type_ping.callback(self.cog, interaction)
        self.assertIsInstance(
            interaction.response.send_message.await_args.kwargs["view"], TypePingView
        )
        self.cog.save_bot_state.assert_not_called()

        self.cog.save_bot_state.side_effect = OSError("disk full")
        interaction = self.interaction()
        with self.assertLogs("bot", level="ERROR"):
            await PokéTwoNamingBot.slash_type_ping.callback(
                self.cog, interaction, remove="fire"
            )
        self.assertEqual(self.cog.bot_state["type_pings"]["456"], ["fire"])
        self.assertIn(
            "couldn't save", interaction.response.send_message.await_args.args[0]
        )

    async def test_command_save_failure_restores_previous_selection(self):
        self.cog.bot_state["type_pings"]["456"] = ["grass"]
        self.cog.save_bot_state.side_effect = OSError("disk full")

        with self.assertLogs("bot", level="ERROR"):
            ctx = await self.invoke_ping_command(
                PokéTwoNamingBot.type_ping_command, "fire"
            )

        self.assertEqual(self.cog.bot_state["type_pings"]["456"], ["grass"])
        self.assertIn("couldn't save", ctx.send.await_args.args[0])

    async def test_region_menu_still_saves_and_rolls_back_on_error(self):
        view = QuestPingView(self.cog, self.user_id)
        interaction = self.interaction()
        await view.update_regions(interaction, ["Kanto", "Johto"])
        self.assertEqual(self.cog.bot_state["quest_pings"]["456"], ["Johto", "Kanto"])

        self.cog.save_bot_state.side_effect = OSError("disk full")
        with self.assertLogs("bot", level="ERROR"):
            await view.update_regions(interaction, ["Alola"])
        self.assertEqual(self.cog.bot_state["quest_pings"]["456"], ["Johto", "Kanto"])
        interaction.response.send_message.assert_awaited_once()

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

    async def test_leaving_or_ban_clears_only_that_servers_member_data(self):
        self.cog.bot = SimpleNamespace(
            guilds=[SimpleNamespace(id=123), SimpleNamespace(id=789)]
        )
        self.cog.bot_state.update(
            {
                "shiny_hunts": {
                    "123": {"456": {"pokemon": "Charmander"}},
                    "789": {"456": {"pokemon": "Bulbasaur"}},
                },
                "collections": {
                    "123": {"456": ["Charmander"]},
                    "789": {"456": ["Bulbasaur"]},
                },
                "type_pings": {
                    "123": {"456": ["fire"]},
                    "789": {"456": ["grass"]},
                },
                "quest_pings": {
                    "123": {"456": ["Kanto"]},
                    "789": {"456": ["Johto"]},
                },
            }
        )

        member = SimpleNamespace(
            id=456,
            guild=SimpleNamespace(id=123),
        )
        await PokéTwoNamingBot.on_member_remove(self.cog, member)

        for state_key in (
            "shiny_hunts",
            "collections",
            "type_pings",
            "quest_pings",
        ):
            self.assertNotIn("456", self.cog.bot_state[state_key]["123"])
            self.assertIn("456", self.cog.bot_state[state_key]["789"])
        self.cog.save_bot_state.assert_called_once_with()

        self.cog.save_bot_state.reset_mock()
        await PokéTwoNamingBot.on_member_ban(
            self.cog,
            SimpleNamespace(id=789),
            SimpleNamespace(id=456),
        )

        for state_key in (
            "shiny_hunts",
            "collections",
            "type_pings",
            "quest_pings",
        ):
            self.assertNotIn("456", self.cog.bot_state[state_key]["789"])
        self.cog.save_bot_state.assert_called_once_with()

    async def test_member_cleanup_migrates_legacy_pings_to_other_servers(self):
        guild_123 = SimpleNamespace(id=123, get_member=Mock(return_value=None))
        guild_789 = SimpleNamespace(
            id=789,
            get_member=Mock(return_value=SimpleNamespace(id=456)),
        )
        guild_999 = SimpleNamespace(id=999, get_member=Mock(return_value=None))
        self.cog.bot = SimpleNamespace(
            guilds=[guild_123, guild_789, guild_999]
        )
        self.cog.bot_state["type_pings"] = {"456": ["fire"]}
        self.cog.bot_state["quest_pings"] = {"456": ["Kanto"]}

        self.cog.clear_member_server_data(123, 456)

        self.assertNotIn("456", self.cog.bot_state["type_pings"])
        self.assertNotIn("456", self.cog.bot_state["quest_pings"])
        self.assertEqual(
            self.cog.bot_state["type_pings"]["789"]["456"],
            ["fire"],
        )
        self.assertEqual(
            self.cog.bot_state["quest_pings"]["789"]["456"],
            ["Kanto"],
        )
        self.assertNotIn("999", self.cog.bot_state["type_pings"])
        self.assertNotIn("999", self.cog.bot_state["quest_pings"])

    async def test_spawn_omits_pings_for_users_who_left_the_server(self):
        guild = SimpleNamespace(
            id=123,
            get_member=Mock(
                side_effect=lambda user_id: (
                    SimpleNamespace(id=user_id) if user_id == 456 else None
                )
            ),
        )
        self.cog.bot = SimpleNamespace(
            get_guild=Mock(return_value=guild),
            guilds=[guild],
        )
        self.cog.bot_state.update(
            {
                "shiny_hunts": {
                    "123": {
                        "456": {"pokemon": "Bulbasaur"},
                        "789": {"pokemon": "Bulbasaur"},
                    }
                },
                "collections": {
                    "123": {
                        "456": ["Bulbasaur"],
                        "789": ["Bulbasaur"],
                    }
                },
                "type_pings": {
                    "123": {
                        "456": ["grass"],
                        "789": ["grass"],
                    }
                },
                "quest_pings": {
                    "123": {
                        "456": ["Kanto"],
                        "789": ["Kanto"],
                    }
                },
            }
        )

        content, _ = self.cog.format_spawn_prediction("Bulbasaur", 99.0, 123)

        self.assertIn("Shiny hunt pings: <@456>", content)
        self.assertIn("Collection pings: <@456>", content)
        self.assertIn("Type pings: <@456>", content)
        self.assertIn("Quest pings: <@456>", content)
        self.assertNotIn("<@789>", content)

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
