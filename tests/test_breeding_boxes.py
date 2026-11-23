import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from bot import BREEDING_BOX_LIMIT, PokéTwoNamingBot


class BreedingBoxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {"breeding_boxes": {}}
        self.cog.save_bot_state = Mock()
        self.cog.class_names = {"pikachu": "Pikachu"}
        self.cog.pokemon_aliases = {}
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=456, display_name="Trainer"),
            message=SimpleNamespace(reference=None),
            send=AsyncMock(),
        )

    async def test_create_list_and_delete_box(self):
        await self.cog.breeding_box_command(self.ctx, "Daycare")
        boxes = self.cog.breeding_user_boxes(123, 456)
        self.assertIn("Daycare", boxes)

        await self.cog.breeding_box_command(self.ctx, "")
        embed = self.ctx.send.await_args.kwargs["embed"]
        self.assertIn("Daycare", embed.description)
        self.assertIn(f"0/{BREEDING_BOX_LIMIT}", embed.description)

        await self.cog.breeding_box_command(self.ctx, "delete Daycare")
        self.assertEqual(boxes, {})

    async def test_box_limit_is_enforced(self):
        box = self.cog.breeding_user_boxes(123, 456).setdefault(
            "Eggs",
            {"items": [{"name": "Pikachu", "tags": []}]},
        )
        box["items"] = [
            {"name": f"Pokemon {index}", "tags": []}
            for index in range(BREEDING_BOX_LIMIT)
        ]
        self.assertEqual(
            self.cog.breeding_box_item_count(box),
            BREEDING_BOX_LIMIT,
        )

    async def test_remove_and_rename_box(self):
        boxes = self.cog.breeding_user_boxes(123, 456)
        boxes["Eggs"] = {
            "items": [{"name": "Pikachu", "tags": []}],
        }
        await self.cog.breeding_box_command(self.ctx, "rename Eggs Hatch")
        self.assertIn("Hatch", boxes)
        await self.cog.breeding_box_command(self.ctx, "remove Hatch Pikachu")
        self.assertEqual(boxes["Hatch"]["items"], [])
