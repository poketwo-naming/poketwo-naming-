import unittest
from collections import OrderedDict, deque
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from PIL import Image

from bot import TRAINING_REVIEW_CHANNEL_ID, PokéTwoNamingBot


class SpawnThumbnailTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), color="green").save(image_buffer, format="PNG")
        self.image_data = image_buffer.getvalue()

        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog._get_spawn_image = AsyncMock(
            return_value=(self.image_data, 0.01)
        )
        self.recognize = Mock()
        self.cog.recognize_spawn_image = self.recognize
        self.cog.shiny_hunters_for_spawn = Mock(return_value=[])
        self.cog.format_spawn_prediction = Mock(
            side_effect=lambda *args: ("prediction", discord.Embed())
        )
        self.cog.pokemon_sprite_ids = {
            "Mosslax": 143,
            "Ride Cyclizar": 967,
        }
        self.cog.spawn_response_times = deque(maxlen=100)
        self.cog.inference_times = deque(maxlen=100)
        self.cog.image_download_times = deque(maxlen=100)
        self.cog.message_send_times = deque(maxlen=100)
        self.cog.spawn_metrics = deque(maxlen=100)
        self.cog.spawn_prediction_cache = OrderedDict()
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
                self.cog.spawn_prediction_cache.clear()
                self.recognize.return_value = (
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

    async def test_custom_variant_reuses_spawn_url_without_uploading_file(self):
        self.message.attachments = []
        self.message.embeds = [
            SimpleNamespace(
                image=SimpleNamespace(url="https://cdn.example/spawn.png"),
                thumbnail=SimpleNamespace(url=None),
            )
        ]
        self.recognize.return_value = ("Mosslax", 99.0, 0.02)

        with patch("bot.os.path.isfile", return_value=False):
            await self.cog.handle_poketwo_spawn(self.message)

        sent = self.channel.send.await_args.kwargs
        self.assertEqual(
            sent["embed"].thumbnail.url,
            "https://cdn.example/spawn.png",
        )
        self.assertNotIn("file", sent)

    async def test_local_custom_sprite_uses_remote_url_without_uploading_file(self):
        self.recognize.return_value = ("Peakychu", 99.0, 0.02)

        with patch("bot.os.path.isfile", return_value=True):
            await self.cog.handle_poketwo_spawn(self.message)

        sent = self.channel.send.await_args.kwargs
        self.assertEqual(
            sent["embed"].thumbnail.url,
            (
                "https://raw.githubusercontent.com/"
                "poketwo-naming/poketwo-naming-/main/"
                "pokemon_sprites/Peakychu.png"
            ),
        )
        self.assertNotIn("file", sent)

    async def test_normal_spawn_records_network_timings(self):
        self.recognize.return_value = ("Pikachu", 99.0, 0.02)
        self.cog.pokemon_sprite_ids["Pikachu"] = 25
        with patch("bot.os.path.isfile", return_value=False):
            await self.cog.handle_poketwo_spawn(self.message)

        sent = self.channel.send.await_args.kwargs
        self.assertIn("/25.png", sent["embed"].thumbnail.url)
        self.assertEqual(list(self.cog.image_download_times), [0.01])
        self.assertEqual(len(self.cog.message_send_times), 1)
        assert self.cog.last_spawn_metrics is not None
        self.assertEqual(self.cog.last_spawn_metrics["send"], self.cog.message_send_times[0])
        self.assertEqual(list(self.cog.spawn_metrics), [self.cog.last_spawn_metrics])

    async def test_spawn_image_download_uses_discord_cached_media_url(self):
        attachment = SimpleNamespace(
            content_type="image/png",
            read=AsyncMock(return_value=self.image_data),
        )
        self.message.attachments = [attachment]

        image_data, _ = await PokéTwoNamingBot._get_spawn_image(
            self.cog,
            self.message,
        )

        self.assertEqual(image_data, self.image_data)
        attachment.read.assert_awaited_once_with(use_cached=True)

    async def test_spawn_image_download_falls_back_when_cached_url_fails(self):
        attachment = SimpleNamespace(
            content_type="image/png",
            read=AsyncMock(
                side_effect=[
                    discord.HTTPException(
                        SimpleNamespace(status=404, reason="Not Found"),
                        "cached media unavailable",
                    ),
                    self.image_data,
                ]
            ),
        )
        self.message.attachments = [attachment]

        image_data, _ = await PokéTwoNamingBot._get_spawn_image(
            self.cog,
            self.message,
        )

        self.assertEqual(image_data, self.image_data)
        self.assertEqual(
            attachment.read.await_args_list[0].kwargs,
            {"use_cached": True},
        )
        self.assertEqual(attachment.read.await_args_list[1].args, ())
        self.assertEqual(attachment.read.await_args_list[1].kwargs, {})

    async def test_low_confidence_spawn_still_sends_review(self):
        self.channel.id = TRAINING_REVIEW_CHANNEL_ID
        self.recognize.return_value = ("Pikachu", 20.0, 0.02)
        self.cog.pokemon_types = {"Pikachu": []}
        self.cog.reserve_user_ids = Mock(return_value=[])
        self.cog.collection_owners_for_spawn = Mock(return_value=[])

        await self.cog.handle_poketwo_spawn(self.message)

        sent = self.channel.send.await_args.kwargs
        self.assertEqual(sent["embed"].title, "Is this Pokémon correct?")
        self.assertEqual(sent["file"].filename, "spawn-review.webp")
        self.assertEqual(sent["view"].pokemon_name, "Pikachu")
        self.assertEqual(len(self.cog.message_send_times), 1)

    async def test_identical_images_reuse_prediction_but_changed_images_do_not(self):
        self.recognize.side_effect = [
            ("Pikachu", 99.0, 0.02),
            ("Eevee", 88.0, 0.03),
        ]

        first = await self.cog.recognize_cached_spawn_image(b"first")
        repeated = await self.cog.recognize_cached_spawn_image(b"first")
        changed = await self.cog.recognize_cached_spawn_image(b"second")

        self.assertEqual(first[:2], repeated[:2])
        self.assertEqual(changed[:2], ("Eevee", 88.0))
        self.assertEqual(self.recognize.call_count, 2)

    async def test_prediction_cache_evicts_least_recently_used_image(self):
        for index in range(1024):
            image_hash = sha256(str(index).encode()).digest()
            self.cog.spawn_prediction_cache[image_hash] = ("Pikachu", 99.0)
        await self.cog.recognize_cached_spawn_image(b"0")
        self.recognize.return_value = ("Eevee", 88.0, 0.02)

        await self.cog.recognize_cached_spawn_image(b"new")

        self.assertEqual(len(self.cog.spawn_prediction_cache), 1024)
        self.assertIn(sha256(b"0").digest(), self.cog.spawn_prediction_cache)
        self.assertNotIn(sha256(b"1").digest(), self.cog.spawn_prediction_cache)

    async def test_api_shows_download_and_send_times(self):
        self.cog.bot = SimpleNamespace(
            user=None,
            guilds=[SimpleNamespace(name="Private Server")],
        )
        self.cog.store_times = deque(maxlen=100)
        self.cog.json_load_seconds = 0.0
        self.cog.model_load_seconds = 0.0
        self.cog.active_incense_count = Mock(return_value=0)
        self.cog.image_download_times.extend([0.1, 0.2])
        self.cog.message_send_times.extend([0.3, 0.4])
        ctx = SimpleNamespace(send=AsyncMock())

        await PokéTwoNamingBot.api_status.callback(self.cog, ctx)

        fields = {field.name: field.value for field in ctx.send.await_args.kwargs["embed"].fields}
        self.assertEqual(fields["Download Avg"], "150 ms")
        self.assertEqual(fields["Download Latest"], "200 ms")
        self.assertEqual(fields["Send Avg"], "350 ms")
        self.assertEqual(fields["Send Latest"], "400 ms")
        self.assertNotIn(
            "Servers",
            ctx.send.await_args.kwargs["embed"].footer.text,
        )
        self.assertNotIn(
            "Private Server",
            ctx.send.await_args.kwargs["embed"].footer.text,
        )

    async def test_apislow_reports_breakdown_of_slowest_recent_response(self):
        self.cog.spawn_metrics.append(
            {"download": 1.0, "inference": 1.0, "send": 1.0, "total": 9.0}
        )
        self.cog.spawn_metrics.extend(
            [{"download": 0.1, "inference": 0.02, "send": 0.3, "total": 0.5}]
            * 99
        )
        self.cog.spawn_metrics.append(
            {"download": 0.2, "inference": 0.025, "send": 5.6, "total": 5.905}
        )
        ctx = SimpleNamespace(send=AsyncMock())

        await PokéTwoNamingBot.api_slowest.callback(self.cog, ctx)

        embed = ctx.send.await_args.kwargs["embed"]
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(
            fields,
            {
                "Download": "200 ms",
                "Inference": "25 ms",
                "Discord send": "5600 ms",
                "Other": "80 ms",
                "Total": "5905 ms",
            },
        )
        self.assertEqual(embed.footer.text, "Window: latest 100 recognitions")

    async def test_apislow_reports_when_no_response_has_been_recorded(self):
        ctx = SimpleNamespace(send=AsyncMock())

        await PokéTwoNamingBot.api_slowest.callback(self.cog, ctx)

        ctx.send.assert_awaited_once_with(
            "No spawn response timings have been recorded yet."
        )


if __name__ == "__main__":
    unittest.main()
