import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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
        )
        self.service = BreedingBoxService(self.cog)
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=456, display_name="Trainer"),
            message=SimpleNamespace(reference=None),
            channel=SimpleNamespace(),
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

    async def test_append_adds_each_page_and_clear_flag_replaces_contents(self):
        boxes = self.service.user_boxes(123, 456)
        boxes["Daycare"] = {"items": [{"name": "Eevee", "tags": []}]}

        async def message(content):
            return SimpleNamespace(
                content=content,
                embeds=[],
            )

        self.ctx.message.reference = SimpleNamespace(
            resolved=await message("Pikachu ♂\nPikachu ♀"),
        )
        await self.command("box", "append Daycare")
        self.assertEqual(len(boxes["Daycare"]["items"]), 3)
        self.assertEqual(
            [item.get("gender") for item in boxes["Daycare"]["items"][1:]],
            ["male", "female"],
        )

        self.ctx.message.reference = SimpleNamespace(
            resolved=await message("Eevee"),
        )
        await self.command("box", "append Daycare --c")
        self.assertEqual(
            boxes["Daycare"]["items"],
            [{"name": "Eevee", "gender": None, "tags": []}],
        )

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
        await view.random_pairs.callback(interaction)
        self.assertEqual(
            self.service.daycare_settings(123, 456)["selection"],
            "random",
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
                {"name": "Pikachu", "gender": "male", "tags": []},
                {"name": "Pikachu", "gender": "female", "tags": []},
                {"name": "Pikachu", "gender": "male", "tags": []},
                {"name": "Pikachu", "gender": "female", "tags": []},
            ]
        }
        self.service.species_cache[25] = {
            "gender_rate": 4,
            "egg_groups": ("field", "fairy"),
        }

        await self.service.daycare_command(self.ctx, "Daycare")

        embed = self.ctx.send.await_args.kwargs["embed"]
        self.assertIn("@Pokétwo#8236 daycare pikachu pikachu", embed.description)
        self.assertEqual(embed.description.count("`@Pokétwo#8236 daycare"), 2)
