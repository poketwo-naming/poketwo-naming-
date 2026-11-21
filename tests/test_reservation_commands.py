import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import discord

from bot import GrabConfirmView, GrabEmojiModal, GrabReservesView, PokéTwoNamingBot


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

    async def test_collection_add_accepts_woguru_for_braviary(self):
        self.cog.class_names["braviary"] = "Braviary"
        self.cog.pokemon_aliases = self.cog.load_pokemon_aliases()
        self.cog.bot_state["collections"] = {}
        self.ctx.author = SimpleNamespace(id=456)

        for name in ("woguru", "Wōguru"):
            await PokéTwoNamingBot.add_collection.callback(
                self.cog, self.ctx, pokemon_input=name
            )

        self.assertEqual(
            self.cog.bot_state["collections"]["123"]["456"], ["Braviary"]
        )
        self.assertNotIn("Unknown Pokémon", self.ctx.send.await_args.args[0])

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

    def test_umbreon_prediction_uses_working_catch_name(self):
        with Path("pokemon_best_names.json").open(encoding="utf-8") as source:
            best_names = json.load(source)
        self.cog.pokemon_types = {"Umbreon": []}
        self.cog.pokemon_best_names = best_names

        content, embed = self.cog.format_spawn_prediction("Umbreon", 98.0)

        self.assertIn("Best name: Blacky", content)
        assert embed.description is not None
        self.assertIn("@Pokétwo#8236 c blacky", embed.description)

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

    def test_grab_parser_ignores_numbered_heading_and_keeps_users_separate(self):
        self.cog.class_names.update({"archaludon": "Archaludon", "eevee": "Eevee"})
        self.cog.pokemon_aliases = {"booster": "Flareon", "eevee": "Eevee"}
        message = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            content="Booster 1 - <@456> - archaludon\n<@456> - Eevee <@789> - Pikachu",
            embeds=[],
            message_snapshots=[],
        )

        self.assertEqual(
            self.cog.parse_grab_list(message, 123),
            [
                ("456", "Archaludon", False, False, ""),
                ("456", "Eevee", False, False, ""),
                ("789", "Pikachu", False, False, ""),
            ],
        )
        self.assertEqual(
            self.cog.pokemon_names_from_grab_segment("Booster"),
            [("Flareon", False, "")],
        )

    async def test_grab_import_reserves_multiple_users_from_list(self):
        self.cog.class_names.update({
            name.casefold(): name
            for name in ("Buizel", "Miltank", "Mawile", "Absol", "Ditto", "Komala")
        })
        message = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            content=(
                "Rare- <@101> - buizel - <@102> miltank\n"
                "Res 2 - <@103> Mawile <@104> absol\n"
                "Res 3 - <@105> - ditto <@106> komala"
            ),
            embeds=[],
            message_snapshots=[],
        )

        entries = self.cog.parse_grab_list(message, 123)
        self.assertEqual(
            entries,
            [
                ("101", "Buizel", False, False, ""),
                ("102", "Miltank", False, False, ""),
                ("103", "Mawile", False, False, ""),
                ("104", "Absol", False, False, ""),
                ("105", "Ditto", False, False, ""),
                ("106", "Komala", False, False, ""),
            ],
        )
        class FakeChannel(discord.abc.Messageable):
            async def _get_channel(self):
                raise NotImplementedError

        channel = FakeChannel()
        channel.send = AsyncMock()
        guild = SimpleNamespace(
            id=123,
            get_member=lambda user_id: SimpleNamespace(id=user_id),
        )
        interaction = cast(
            discord.Interaction,
            SimpleNamespace(
                channel=channel,
                guild=guild,
                response=SimpleNamespace(edit_message=AsyncMock()),
            ),
        )
        self.cog.bot_state["reserves"]["123"] = {}
        grab_view = GrabReservesView(self.cog, 789, 101112, entries)
        confirm_view = GrabConfirmView(
            self.cog, 789, 101112, grab_view.expanded_entries(), False
        )

        await confirm_view.confirm.callback(interaction)

        self.assertEqual(
            self.cog.bot_state["reserves"]["123"],
            {
                "Buizel": ["101"],
                "Miltank": ["102"],
                "Mawile": ["103"],
                "Absol": ["104"],
                "Ditto": ["105"],
                "Komala": ["106"],
            },
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
            "all Pikachu",
        )
        view.custom_emoji = "<:my_pikachu:987654321>"
        emoji_description = view.build_embed().description or ""
        self.assertEqual(
            emoji_description,
            "<:my_pikachu:987654321> all Pikachu",
        )
        view.all_forms = False
        self.assertEqual(view.copy_text(), "<:my_pikachu:987654321> Pikachu")
        self.assertIn(
            "<@456>",
            view.format_line(
                "456",
                "Pikachu",
                custom_emoji="<:party_pikachu:123456789>",
            ),
        )

    async def test_custom_emoji_button_opens_modal(self):
        view = GrabReservesView(
            self.cog,
            789,
            101112,
            [("456", "Pikachu", False, False, "")],
        )
        send_modal = AsyncMock()
        interaction = cast(
            discord.Interaction,
            SimpleNamespace(
                response=SimpleNamespace(send_modal=send_modal),
            ),
        )

        await view.open_custom_emoji_modal(interaction)

        await_call = send_modal.await_args
        if await_call is None:
            self.fail("Custom emoji modal was not opened.")
        modal = await_call.args[0]
        self.assertIsInstance(modal, GrabEmojiModal)

    async def test_grab_confirmation_adds_all_forms_with_one_command(self):
        class FakeChannel(discord.abc.Messageable):
            async def _get_channel(self):
                raise NotImplementedError

        channel = FakeChannel()
        channel.send = AsyncMock()
        guild = SimpleNamespace(id=123)
        interaction = cast(
            discord.Interaction,
            SimpleNamespace(
                channel=channel,
                guild=guild,
                response=SimpleNamespace(edit_message=AsyncMock()),
            ),
        )
        self.cog.class_names.update({
            "articuno": "Articuno",
            "galarian articuno": "Galarian Articuno",
        })
        self.cog.add_reserve_direct = AsyncMock(return_value=True)
        view = GrabConfirmView(
            self.cog, 789, 101112, [("456", "all Articuno", False, "")], False
        )

        await view.confirm.callback(interaction)

        self.assertEqual(
            [call.args[1] for call in self.cog.add_reserve_direct.await_args_list],
            ["Articuno", "Galarian Articuno"],
        )
        channel.send.assert_awaited_once_with(
            "v!r add all Articuno <@456>\n"
            "Reserve **all Articuno** added to <@456>."
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

    async def test_exchange_all_forms_includes_regional_forms_and_moves_reserves(self):
        self.cog.class_names = {
            name.casefold(): name
            for name in (
                "Articuno",
                "Galarian Articuno",
                "Marshadow",
                "Zenith Marshadow",
                "Pikachu",
                "Zapdos",
                "Galarian Zapdos",
            )
        }
        source = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            content="",
            embeds=[],
            message_snapshots=[
                SimpleNamespace(
                    content=(
                        "<@456> - all articuno\n"
                        "<@456> - all marshadow\n"
                        "<@456> - pikachu\n"
                        "<@456> - zapdos"
                    ),
                    embeds=[],
                )
            ],
        )
        self.cog.referenced_grab_message = AsyncMock(return_value=source)
        self.cog.bot_state["reserves"]["123"] = {
            name: ["789"] for name in self.cog.class_names.values()
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
            [
                ("456", "Articuno"),
                ("456", "Galarian Articuno"),
                ("456", "Marshadow"),
                ("456", "Zenith Marshadow"),
                ("456", "Pikachu"),
                ("456", "Zapdos"),
            ],
        )
        self.assertIn("Articuno, Galarian Articuno", view.build_embed().description)
        interaction = cast(
            discord.Interaction,
            SimpleNamespace(
                user=SimpleNamespace(id=101),
                response=SimpleNamespace(edit_message=AsyncMock()),
            ),
        )

        await view.confirm.callback(interaction)

        self.assertEqual(
            self.cog.bot_state["reserves"]["123"],
            {
                name: ["789"] if name == "Galarian Zapdos" else ["456"]
                for name in self.cog.class_names.values()
            },
        )


if __name__ == "__main__":
    unittest.main()
