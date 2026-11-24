import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from bot import PokéTwoNamingBot
from breeding_boxes import (
    BREEDING_BOX_LIMIT,
    BreedingBoxService,
    find_daycare_pairs,
)


class BreedingBoxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = SimpleNamespace(
            bot_state={"breeding_boxes": {}, "daycare_settings": {}},
            save_bot_state=Mock(),
            report_pokemon_names=lambda: ["Pikachu", "Eevee", "Ditto"],
            resolve_pokemon_name=lambda name: {
                "pikachu": "Pikachu",
                "eevee": "Eevee",
                "ditto": "Ditto",
            }.get(name.casefold()),
            pokemon_species={"Pikachu": 25, "Eevee": 133, "Ditto": 132},
            http_session=None,
            poketwo_bot_id=716390085896962058,
        )
        self.service = BreedingBoxService(self.cog, 716390085896962058)
        self.cog.breeding_box_service = self.service
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=456, display_name="Trainer"),
            message=SimpleNamespace(reference=None),
            channel=SimpleNamespace(id=789, fetch_message=AsyncMock(), send=AsyncMock()),
            send=AsyncMock(),
        )

    async def command(self, command, entry=""):
        await self.service.dispatch(self.ctx, command, entry)

    async def test_create_list_contents_delete_and_limit(self):
        await self.command("box", "create Daycare")
        boxes = self.service.user_boxes(123, 456)
        self.assertIn("Daycare", boxes)

        boxes["Daycare"]["items"] = [
            {"name": "Pikachu", "gender": "male", "tags": []}
        ]
        await self.command("box", "list Daycare")
        embed = self.ctx.send.await_args.kwargs["embed"]
        self.assertIn("Pikachu", embed.description)
        self.assertIn(f"1/{BREEDING_BOX_LIMIT}", embed.title)

        await self.command("box", "delete Daycare")
        self.assertEqual(boxes, {})

    async def test_boxhelp_is_sent_as_an_embed(self):
        await self.command("boxhelp")

        embed = self.ctx.send.await_args.kwargs["embed"]
        self.assertIsInstance(embed, discord.Embed)
        self.assertEqual(embed.title, "Breeding Boxes & Daycare")
        self.assertIn("`v!dc settings`", embed.description)

    async def test_append_adds_each_page_and_clear_flag_replaces_contents(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["Daycare"] = {"items": [{"name": "Eevee", "tags": []}]}

        async def message(content):
            return SimpleNamespace(
                id=555,
                author=SimpleNamespace(id=716390085896962058),
                guild=self.ctx.guild,
                channel=self.ctx.channel,
                content=content,
                embeds=[],
            )

        self.ctx.channel.fetch_message.return_value = await message(
            "`101` Pikachu ♂\n`102` Pikachu ♀"
        )
        self.ctx.message.reference = SimpleNamespace(
            message_id=555,
            resolved=await message("`999` Pikachu ♂"),
        )
        await self.command("box", "append Daycare")
        self.assertEqual(len(boxes["Daycare"]["items"]), 3)
        self.assertEqual(
            [item.get("gender") for item in boxes["Daycare"]["items"][1:]],
            ["male", "female"],
        )

        self.ctx.channel.fetch_message.return_value = await message("`103` Eevee")
        await self.command("box", "append Daycare --c")
        self.assertEqual(
            boxes["Daycare"]["items"],
            [{"name": "Eevee", "gender": None, "tags": [], "pokemon_id": "103"}],
        )

    async def test_append_reads_poketwo_component_list(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["purmel"] = {"items": []}
        self.cog.report_pokemon_names = lambda: ["Scatterbug"]
        self.cog.resolve_pokemon_name = lambda name: (
            "Scatterbug" if name.casefold() == "scatterbug" else None
        )
        container = discord.components.Container(
            {
                "type": 17,
                "components": [
                    {
                        "type": 10,
                        "content": (
                            "`16289` <:pokemon:123456789> **Scatterbug** ♀ • Lvl. 13 • 76.34%\n"
                            "`10501` <:pokemon:123456789> **Scatterbug** ♂ • Lvl. 17 • 76.34%"
                        ),
                    },
                    {
                        "type": 10,
                        "content": "Showing entries 1–20 out of 9529.",
                    },
                ],
            },
            None,
        )
        source = SimpleNamespace(
            id=555, author=SimpleNamespace(id=716390085896962058),
            guild=self.ctx.guild, channel=self.ctx.channel,
            content="", embeds=[], components=[container],
        )
        self.ctx.message.reference = SimpleNamespace(message_id=555, resolved=source)
        self.ctx.channel.fetch_message.return_value = source

        await self.command("box", "append purmel")

        self.assertEqual(
            boxes["purmel"]["items"],
            [
                {"name": "Scatterbug", "gender": "female", "tags": [], "pokemon_id": "16289"},
                {"name": "Scatterbug", "gender": "male", "tags": [], "pokemon_id": "10501"},
            ],
        )
        self.assertIn("Added **2**", self.ctx.send.await_args.args[0])
        next_page = discord.components.Container(
            {
                "type": 17,
                "components": [
                    {
                        "type": 10,
                        "content": "`11000` <:pokemon:123456789> **Scatterbug** ♂ • Lvl. 18 • 76.34%",
                    },
                ],
            },
            None,
        )
        edited = SimpleNamespace(
            id=555, guild=self.ctx.guild, channel=self.ctx.channel,
            content="", embeds=[], components=[next_page],
        )
        await PokéTwoNamingBot.on_raw_message_edit(
            self.cog,
            SimpleNamespace(data={"components": []}, message=edited),
        )
        self.assertEqual(
            [item["pokemon_id"] for item in boxes["purmel"]["items"]],
            ["16289", "10501", "11000"],
        )

    async def test_append_tracks_edits_and_deduplicates_by_pokemon_id(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["purmel"] = {"items": []}
        source = SimpleNamespace(
            id=555, author=SimpleNamespace(id=716390085896962058),
            guild=self.ctx.guild, channel=self.ctx.channel,
            content="`101` Pikachu ♂\n`102` Pikachu ♀", embeds=[], components=[],
        )
        self.ctx.message.reference = SimpleNamespace(message_id=555, resolved=source)
        self.ctx.channel.fetch_message.return_value = source
        confirmation = SimpleNamespace(edit=AsyncMock())
        self.ctx.send.return_value = confirmation
        await self.command("box", "append purmel")
        await self.command("box", "append purmel")
        self.assertEqual(len(boxes["purmel"]["items"]), 2)

        updated = SimpleNamespace(
            id=555, guild=self.ctx.guild, channel=self.ctx.channel,
            content="`102` Pikachu ♀\n`103` Pikachu ♂", embeds=[], components=[],
        )
        await self.service.handle_list_edit(updated)
        self.assertEqual(
            [item["pokemon_id"] for item in boxes["purmel"]["items"]],
            ["101", "102", "103"],
        )
        self.assertIn("3/7500", confirmation.edit.await_args.kwargs["content"])

        await self.service.handle_list_edit(updated)
        self.assertEqual(len(boxes["purmel"]["items"]), 3)

    async def test_append_uses_current_message_not_stale_reply_snapshot(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["purmel"] = {"items": []}
        self.ctx.message.reference = SimpleNamespace(
            message_id=555,
            resolved=SimpleNamespace(content="`101` Pikachu ♂", embeds=[]),
        )
        self.ctx.channel.fetch_message.return_value = SimpleNamespace(
            id=555, author=SimpleNamespace(id=716390085896962058),
            guild=self.ctx.guild, channel=self.ctx.channel,
            content="`141` Pikachu ♀", embeds=[], components=[],
        )
        await self.command("box", "append purmel")
        self.assertEqual(boxes["purmel"]["items"][0]["pokemon_id"], "141")

    async def test_page_arrows_accumulate_to_160_and_revisiting_does_not_duplicate(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["purmel"] = {"items": []}

        def page(start):
            return SimpleNamespace(
                id=555,
                author=SimpleNamespace(id=716390085896962058),
                guild=self.ctx.guild,
                channel=self.ctx.channel,
                content="\n".join(
                    f"`{number}` Pikachu ♂" for number in range(start, start + 20)
                ),
                embeds=[],
                components=[],
            )

        self.ctx.message.reference = SimpleNamespace(message_id=555)
        self.ctx.channel.fetch_message.return_value = page(1)
        confirmation = SimpleNamespace(edit=AsyncMock())
        self.ctx.send.return_value = confirmation
        await self.command("box", "append purmel")
        for start in range(21, 142, 20):
            payload = SimpleNamespace(
                data={"components": []},
                message=page(start),
            )
            await PokéTwoNamingBot.on_raw_message_edit(self.cog, payload)
        self.assertEqual(len(boxes["purmel"]["items"]), 160)
        self.assertIn("160/7500", confirmation.edit.await_args.kwargs["content"])

        await self.service.handle_list_edit(page(121))
        self.assertEqual(len(boxes["purmel"]["items"]), 160)
        self.assertIn("Added **0**", confirmation.edit.await_args.kwargs["content"])

    async def test_append_respects_box_capacity_after_deduplication(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["full"] = {
            "items": [
                {"name": "Pikachu", "pokemon_id": str(number), "tags": []}
                for number in range(1, BREEDING_BOX_LIMIT)
            ]
        }
        source = SimpleNamespace(
            id=555, author=SimpleNamespace(id=716390085896962058),
            guild=self.ctx.guild, channel=self.ctx.channel,
            content="`1` Pikachu ♂\n`7500` Pikachu ♀\n`7501` Pikachu ♂",
            embeds=[], components=[],
        )
        self.ctx.message.reference = SimpleNamespace(message_id=555)
        self.ctx.channel.fetch_message.return_value = source

        await self.command("box", "append full")

        self.assertEqual(len(boxes["full"]["items"]), BREEDING_BOX_LIMIT)
        self.assertEqual(boxes["full"]["items"][-1]["pokemon_id"], "7500")
        self.assertIn("1 Pokémon could not be added", self.ctx.send.await_args.args[0])

    async def test_removed_box_is_not_recreated_by_an_edit(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["purmel"] = {"items": []}
        source = SimpleNamespace(
            id=555, author=SimpleNamespace(id=716390085896962058),
            guild=self.ctx.guild, channel=self.ctx.channel,
            content="`1` Pikachu ♂", embeds=[], components=[],
        )
        self.ctx.message.reference = SimpleNamespace(message_id=555)
        self.ctx.channel.fetch_message.return_value = source
        await self.command("box", "append purmel")
        del boxes["purmel"]

        await self.service.handle_list_edit(source)

        self.assertEqual(boxes, {})
        self.assertEqual(self.service.append_sessions, {})

    async def test_remove_transfer_copy_tag_and_rename(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["Eggs"] = {
            "items": [
                {"name": "Pikachu", "gender": "male", "tags": []},
                {"name": "Eevee", "gender": "female", "tags": []},
            ]
        }
        boxes["Backup"] = {"items": []}

        await self.command("box", "tag Eggs 1 egg-move")
        self.assertEqual(boxes["Eggs"]["items"][0]["tags"], ["egg-move"])
        await self.command("box", "copy Eggs Backup 1")
        self.assertEqual(len(boxes["Backup"]["items"]), 1)
        await self.command("box", "transfer Eggs Backup Eevee")
        self.assertEqual(len(boxes["Eggs"]["items"]), 1)
        self.assertEqual(len(boxes["Backup"]["items"]), 2)
        await self.command("box", "remove Backup Pikachu")
        self.assertEqual(len(boxes["Backup"]["items"]), 1)
        await self.command("box", "rename Eggs Daycare")
        self.assertIn("Daycare", boxes)
        self.assertNotIn("Eggs", boxes)

    async def test_copy_box_and_reset_requires_confirmation(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["Main"] = {"items": [{"name": "Pikachu", "tags": []}]}
        await self.command("box", "copy Main 'Main backup'")
        self.assertEqual(boxes["Main backup"], boxes["Main"])

        await self.command("box", "reset")
        view = self.ctx.send.await_args.kwargs["view"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=456),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        await view.confirm.callback(interaction)
        self.assertEqual(boxes, {})

    async def test_tag_views_and_daycare_settings(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["Daycare"] = {
            "items": [
                {"name": "Pikachu", "gender": "male", "tags": ["spark"]},
            ]
        }
        await self.command("box", "tags")
        self.assertIn("spark", self.ctx.send.await_args.args[0])
        await self.command("box", "tagged spark")
        self.assertIn("Pikachu", self.ctx.send.await_args.args[0])

        await self.command("dc", "settings")
        view = self.ctx.send.await_args.kwargs["view"]
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=456),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        # Test changing pairing mode
        await view.pairing_high_compact.callback(interaction)
        self.assertEqual(
            self.service.daycare_settings(123, 456)["pairing_mode"],
            "high_compact",
        )

    def test_daycare_pair_selection_requires_compatible_gender_and_egg_group(self):
        items = [
            {"species_id": 25, "gender": "male"},
            {"species_id": 25, "gender": "female"},
            {"species_id": 132, "gender": None},
            {"species_id": 133, "gender": "female"},
            {"species_id": 999, "gender": "male"},
        ]
        species_data = {
            25: {"gender_rate": 4, "egg_groups": ("field", "fairy")},
            132: {"gender_rate": -1, "egg_groups": ("ditto",)},
            133: {"gender_rate": 1, "egg_groups": ("field",)},
            999: {"gender_rate": 4, "egg_groups": ("undiscovered",)},
        }
        self.assertEqual(
            find_daycare_pairs(items, species_data),
            [(0, 1), (2, 3)],
        )

    def test_tagged_pair_selection_prioritizes_tracked_egg_moves(self):
        items = [
            {"species_id": 25, "gender": "male", "tags": []},
            {"species_id": 25, "gender": "female", "tags": []},
            {"species_id": 25, "gender": "male", "tags": ["volt tackle"]},
            {"species_id": 25, "gender": "female", "tags": []},
        ]
        species_data = {
            25: {"gender_rate": 4, "egg_groups": ("field",)},
        }

        self.assertEqual(
            find_daycare_pairs(items, species_data, selection="tagged"),
            [(2, 1), (0, 3)],
        )

    async def test_daycare_command_returns_ready_to_paste_pairs(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["Daycare"] = {
            "items": [
                {"name": "Pikachu", "gender": "male", "tags": [], "pokemon_id": "23580"},
                {"name": "Pikachu", "gender": "female", "tags": [], "pokemon_id": "28179"},
            ]
        }
        self.service.species_cache[25] = {
            "gender_rate": 4,
            "egg_groups": ("field", "fairy"),
        }

        await self.service.daycare_command(self.ctx, "Daycare")

        output = self.ctx.send.await_args.args[0]
        self.assertIn("`@Pokétwo#8236 daycare add 23580 28179`", output)
        self.assertIn("```\n@Pokétwo#8236 daycare add 23580 28179\n```", output)
        self.assertIn("**Pair 1:** Pikachu (male) + Pikachu (female)", output)
        self.assertIn("Pairs formed: 1", output)
        self.assertNotIn("embed", self.ctx.send.await_args.kwargs)

    async def test_daycare_splits_many_pairs_within_discord_message_limit(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["purmel"] = {
            "items": [
                {"name": "Pikachu", "gender": "male" if number % 2 else "female",
                 "tags": [], "pokemon_id": str(number)}
                for number in range(1, 101)
            ]
        }
        self.service.species_cache[25] = {"gender_rate": 4, "egg_groups": ("field",)}

        await self.service.show_daycare_pairs(self.ctx, "purmel", limit=50)

        messages = [call.args[0] for call in self.ctx.send.await_args_list]
        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message.encode("utf-16-le")) // 2 <= 2000
                            for message in messages))
        self.assertIn("Pairs formed: 50", messages[0])
        for number in range(1, 101, 2):
            command = f"daycare add {number} {number + 1}"
            self.assertEqual(sum(message.count(command) for message in messages), 2)

    async def test_daycare_splits_single_pair_with_long_unicode_details(self):
        self.service.user_boxes(123, 456)["purmel"] = {
            "items": [
                {"name": "Pikachu", "gender": "male", "tags": ["😀" * 1500],
                 "pokemon_id": "1"},
                {"name": "Pikachu", "gender": "female", "tags": [],
                 "pokemon_id": "2"},
            ]
        }
        self.service.species_cache[25] = {"gender_rate": 4, "egg_groups": ("field",)}

        await self.service.show_daycare_pairs(self.ctx, "purmel", limit=1)

        messages = [call.args[0] for call in self.ctx.send.await_args_list]
        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message.encode("utf-16-le")) // 2 <= 2000
                            for message in messages))
        self.assertEqual(sum(message.count("😀") for message in messages), 1500)
        self.assertEqual(sum(message.count("daycare add 1 2") for message in messages), 2)

    async def test_daycare_message_limit_boundary(self):
        items = [
            {"name": "Pikachu", "gender": "male", "tags": ["x"], "pokemon_id": "1"},
            {"name": "Pikachu", "gender": "female", "tags": [], "pokemon_id": "2"},
        ]
        self.service.user_boxes(123, 456)["purmel"] = {"items": items}
        self.service.species_cache[25] = {"gender_rate": 4, "egg_groups": ("field",)}
        await self.service.show_daycare_pairs(self.ctx, "purmel", limit=1)
        base_length = len(self.ctx.send.await_args.args[0])

        items[0]["tags"] = ["x" * (2001 - base_length)]
        self.ctx.send.reset_mock()
        await self.service.show_daycare_pairs(self.ctx, "purmel", limit=1)
        self.assertEqual(self.ctx.send.await_count, 1)
        self.assertEqual(len(self.ctx.send.await_args.args[0]), 2000)

        items[0]["tags"][0] += "x"
        self.ctx.send.reset_mock()
        await self.service.show_daycare_pairs(self.ctx, "purmel", limit=1)
        self.assertEqual(self.ctx.send.await_count, 2)
        self.assertTrue(all(len(call.args[0]) <= 2000
                            for call in self.ctx.send.await_args_list))

    async def test_slash_daycare_returns_only_one_pair_from_named_box(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["Trainer's Box"] = {
            "items": [
                {"name": "Pikachu", "gender": gender, "tags": [], "pokemon_id": str(number)}
                for number, gender in [(1, "male"), (2, "female"), (3, "male"), (4, "female")]
            ]
        }
        self.service.species_cache[25] = {"gender_rate": 4, "egg_groups": ("field",)}
        interaction = SimpleNamespace(
            guild=self.ctx.guild,
            user=self.ctx.author,
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await PokéTwoNamingBot.slash_daycare.callback(
            self.cog, interaction, box="Trainer's Box"
        )

        interaction.response.defer.assert_awaited_once()
        output = interaction.followup.send.await_args.args[0]
        self.assertIn("Name: Trainer's Box", output)
        self.assertIn("Pairs formed: 1", output)
        self.assertIn("daycare add 1 2", output)
        self.assertNotIn("daycare add 3 4", output)

        await self.service.daycare_command(self.ctx, '"Trainer\'s Box"')
        self.assertIn("Pairs formed: 1", self.ctx.send.await_args.args[0])

    async def test_slash_daycare_count_limits_pairs_and_reports_shortfall(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["Daycare"] = {
            "items": [
                {"name": "Pikachu", "gender": gender, "tags": [], "pokemon_id": str(number)}
                for number, gender in [(1, "male"), (2, "female"), (3, "male"), (4, "female")]
            ]
        }
        self.service.species_cache[25] = {"gender_rate": 4, "egg_groups": ("field",)}
        interaction = SimpleNamespace(
            guild=self.ctx.guild,
            user=self.ctx.author,
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await PokéTwoNamingBot.slash_daycare.callback(
            self.cog, interaction, box="Daycare", count=2
        )

        output = interaction.followup.send.await_args.args[0]
        self.assertIn("Pairs formed: 2", output)
        self.assertIn("daycare add 1 2", output)
        self.assertIn("daycare add 3 4", output)

        await PokéTwoNamingBot.slash_daycare.callback(
            self.cog, interaction, box="Daycare", count=3
        )
        self.assertIn("Requested 3; only 2 available", interaction.followup.send.await_args.args[0])

    async def test_slash_box_autocomplete_is_scoped_and_limited(self):
        boxes = self.service.user_boxes(123, 456)
        boxes.update({f"Box {index}": {"items": []} for index in range(30)})
        boxes["2"] = {"items": []}
        self.service.user_boxes(123, 999)["Private"] = {"items": []}
        interaction = SimpleNamespace(guild=self.ctx.guild, user=self.ctx.author)

        choices = await PokéTwoNamingBot.daycare_box_autocomplete(self.cog, interaction, "box")
        self.assertEqual(len(choices), 25)
        self.assertTrue(all(choice.name.startswith("Box ") for choice in choices))
        numeric = await PokéTwoNamingBot.daycare_box_autocomplete(self.cog, interaction, "2")
        numeric_choice = next(choice for choice in numeric if choice.name == "2")
        self.assertEqual(self.service.resolve_box(boxes, numeric_choice.value)[0], "2")
        self.assertEqual(
            await PokéTwoNamingBot.daycare_box_autocomplete(self.cog, interaction, "Private"),
            [],
        )

    async def test_slash_daycare_treats_settings_as_a_box_name(self):
        self.service.user_boxes(123, 456)["settings"] = {"items": []}
        interaction = SimpleNamespace(
            guild=self.ctx.guild,
            user=self.ctx.author,
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await PokéTwoNamingBot.slash_daycare.callback(
            self.cog, interaction, box="settings"
        )

        self.assertIn("No compatible numbered pair", interaction.followup.send.await_args.args[0])

    async def test_slash_daycare_defaults_to_first_box(self):
        self.service.user_boxes(123, 456)["First Box"] = {"items": []}
        interaction = SimpleNamespace(
            guild=self.ctx.guild,
            user=self.ctx.author,
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await PokéTwoNamingBot.slash_daycare.callback(self.cog, interaction)

        self.assertIn("First Box", interaction.followup.send.await_args.args[0])

    async def test_slash_daycare_rejects_direct_messages(self):
        interaction = SimpleNamespace(
            guild=None,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        )

        await PokéTwoNamingBot.slash_daycare.callback(self.cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        interaction.response.defer.assert_not_awaited()

    async def test_daycare_does_not_pair_duplicate_numbers_or_old_numberless_entries(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["Daycare"] = {
            "items": [
                {"name": "Pikachu", "gender": "male", "tags": [], "pokemon_id": "5"},
                {"name": "Pikachu", "gender": "female", "tags": [], "pokemon_id": "5"},
                {"name": "Pikachu", "gender": "female", "tags": []},
            ]
        }
        self.service.species_cache[25] = {
            "gender_rate": 4,
            "egg_groups": ("field",),
        }

        await self.service.daycare_command(self.ctx, "Daycare")

        self.assertNotIn("embed", self.ctx.send.await_args.kwargs)
        self.assertIn("No compatible", self.ctx.send.await_args.args[0])
