import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from PIL import Image

from bot import PokéTwoNamingBot


class SpawnThumbnailTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), color="green").save(image_buffer, format="PNG")
        self.image_data = image_buffer.getvalue()

        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog._get_spawn_image = AsyncMock(
            return_value=(self.image_data, 0.01)
        )
        self.cog.recognize_spawn_image = Mock()
        self.cog.shiny_hunters_for_spawn = Mock(return_value=[])
        self.cog.format_spawn_prediction = Mock(
            side_effect=lambda *args: ("prediction", discord.Embed())
        )
        self.cog.pokemon_sprite_ids = {
            "Mosslax": 143,
            "Ride Cyclizar": 967,
        }
        self.cog.spawn_response_times = []
        self.cog.inference_times = []
        self.cog.recognized_spawn_count = 0
        self.channel = SimpleNamespace(id=1, send=AsyncMock())
        self.message = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            channel=self.channel,
        )

    async def test_custom_variant_thumbnails_use_the_spawn_image(self):
        for pokemon_name in ("Mosslax", "Ride Cyclizar"):
            with self.subTest(pokemon_name=pokemon_name):
                self.channel.send.reset_mock()
                self.cog.recognize_spawn_image.return_value = (
                    pokemon_name,
                    99.0,
                    0.02,
                )
                with patch("bot.os.path.isfile", return_value=False):
                    await self.cog.handle_poketwo_spawn(self.message)

                self.channel.send.assert_awaited_once()
                sent = self.channel.send.await_args.kwargs
                self.assertEqual(
                    sent["embed"].thumbnail.url,
                    "attachment://pokemon.webp",
                )
                self.assertEqual(sent["file"].filename, "pokemon.webp")


if __name__ == "__main__":
    unittest.main()
