import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from bot import POKETWO_BOT_ID, PokéTwoNamingBot, ServerSettingsView
from starboard import StarboardService, StarboardSettingsView, main_category, parse_catch


class StarboardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {
            "guild_settings": {"123": {"starboard": {
                "main": 1, "shiny": 2, "vivillon": 3,
            }}}
        }
        self.cog.save_bot_state = Mock()
        self.cog.pokemon_spawn_chances = self.cog.load_pokemon_spawn_chances()
        self.cog.pokemon_sprite_ids = self.cog.load_pokemon_sprite_ids()
        self.channels = {
            i: SimpleNamespace(id=i, name=f"board-{i}", send=AsyncMock(), edit=AsyncMock())
            for i in (1, 2, 3)
        }
        self.channels[2].name = "shinyboard-355"

        async def edit_name(*, name, reason):
            self.channels[2].name = name

        self.channels[2].edit.side_effect = edit_name
        self.cog.bot = SimpleNamespace(
            user=SimpleNamespace(id=77),
            fetch_channel=AsyncMock(side_effect=lambda i: self.channels[i]),
        )
        self.service = StarboardService(self.cog)
        self.cog.starboard_service = self.service
        self.message = SimpleNamespace(
            id=100,
            author=SimpleNamespace(id=POKETWO_BOT_ID),
            guild=SimpleNamespace(id=123, get_channel=self.channels.get),
            content="Congratulations <@999>! You caught a Level 22 Charizard ♂ (52.15%)!",
            embeds=[],
            jump_url="https://discord.com/channels/123/4/100",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_screenshot_catch_parse_with_shiny_and_gmax(self):
        self.message.content += (
            "\nThese colors seem unusual... ✨\n"
            "Woah! It seems that this pokémon has the Gigantamax Factor... ✖️\n"
            "Chain: 1,349"
        )
        catch = parse_catch(self.message)
        self.assertEqual((catch.user_id, catch.pokemon, catch.level, catch.gender),
                         ("999", "Charizard", 22, "♂"))
        self.assertEqual((catch.iv_text, catch.shiny, catch.gigantamax, catch.chain),
                         ("52.15", True, True, "1,349"))

    def test_category_whitelist_and_all_forms(self):
        for name in ("Miraidon", "10% Zygarde", "Bug Arceus", "Zenith Marshadow",
                     "Partner Eevee", "PARTNER PIKACHU",
                     "High-speed Flight Configuration Genesect"):
            self.assertEqual(main_category(name), "rare", name)
        for name in ("Galarian Articuno", "Hisuian Arcanine", "Aqua Breed Tauros",
                     "Galarian Zen Darmanitan"):
            self.assertEqual(main_category(name), "regional", name)
        for name in ("Pikachu", "Eevee", "Partner Eevee Event", "Tauros",
                     "Galarian Rapidash Event", "Marshadow Costume"):
            self.assertIsNone(main_category(name), name)

    def test_poketwo_shiny_chain_format(self):
        self.message.content = (
            "Congratulations <@!999>! You caught a level 22 Charizard "
            "(IV: 9.99%)!\n\n+1 Shiny chain! (**42**)"
        )
        catch = parse_catch(self.message)
        self.assertEqual((catch.user_id, catch.pokemon, catch.iv_text, catch.chain),
                         ("999", "Charizard", "9.99", "42"))

    def test_gender_emoji_and_nidoran_names(self):
        for suffix, name, gender in (
            (":male:", "Galarian Ponyta", "♂"),
            ("<:unknown:123456>", "Rayquaza", ""),
            ("<:female:123456>", "Ralts", "♀"),
            (" ♂", "Charizard", "♂"),
            ("", "Nidoran♂", ""),
            (":female:", "Nidoran♀️", "♀"),
        ):
            with self.subTest(name=name, suffix=suffix):
                self.message.content = (
                    f"Congratulations <@999>! You caught a Level 21 {name}"
                    f"{suffix} (32.26%)!"
                )
                catch = parse_catch(self.message)
                self.assertEqual((catch.pokemon, catch.gender), (name, gender))

    async def test_reported_gender_emoji_catches_post_with_artwork(self):
        for index, (name, suffix) in enumerate((
            ("Galarian Ponyta", ":male:"),
            ("Rayquaza", ":unknown:"),
        )):
            self.message.id = 400 + index
            self.message.content = (
                f"Congratulations <@999>! You caught a Level 10 {name}"
                f"{suffix} (44.62%)!"
            )
            await self.service.handle(self.message)
        self.assertEqual(self.channels[1].send.await_count, 2)

        self.message.id = 402
        self.message.content = (
            "Congratulations <@999>! You caught a Level 21 Ralts:female: (32.26%)!"
            "\n\nShiny streak reset. (2090)"
            "\n\nThese colors seem unusual... ✨"
        )
        await self.service.handle(self.message)
        embed = self.channels[2].send.await_args.kwargs["embed"]
        self.assertIn("Ralts ♀", embed.description)
        self.assertIn("**Chain:** `2090`", embed.description)
        self.assertTrue(embed.thumbnail.url.endswith("/shiny/280.png"))

    async def test_shiny_female_nidoran_uses_female_artwork(self):
        self.message.content = (
            "Congratulations <@999>! You caught a Level 21 Nidoran♀️:female: "
            "(32.26%)!\nThese colors seem unusual... ✨"
        )
        await self.service.handle(self.message)
        embed = self.channels[2].send.await_args.kwargs["embed"]
        self.assertTrue(embed.thumbnail.url.endswith("/shiny/29.png"))

    async def test_main_board_only_listed_catches_with_metadata(self):
        await self.service.handle(self.message)
        self.channels[1].send.assert_not_awaited()
        self.message.content = "Congratulations <@999>! You caught a Level 3 Miraidon (50.54%)!"
        await self.service.handle(self.message)
        embed = self.channels[1].send.await_args.kwargs["embed"]
        self.assertEqual(embed.title, "⭐ Rare Catch Detected!")
        self.assertIn("<@999>", embed.description)
        self.assertIn("Miraidon", embed.description)
        self.assertIn("50.54%", embed.description)
        self.assertIn("1 out of", embed.description)
        self.assertTrue(embed.thumbnail.url)
        self.assertEqual(embed.timestamp, self.message.created_at)

    async def test_partner_catches_post_to_main_board(self):
        for index, name in enumerate(("Partner Eevee", "Partner Pikachu")):
            with self.subTest(name=name):
                self.message.id = 500 + index
                self.message.content = (
                    f"Congratulations <@999>! You caught a Level 10 {name}:female: (50.00%)!"
                )
                await self.service.handle(self.message)
                self.assertEqual(self.channels[1].send.await_count, index + 1)
                embed = self.channels[1].send.await_args.kwargs["embed"]
                self.assertEqual(embed.title, "⭐ Rare Catch Detected!")
                self.assertIn(f"{name} ♀", embed.description)
                self.assertIn("1 out of 69,043", embed.description)
                self.assertTrue(embed.thumbnail.url)
        self.channels[2].send.assert_not_awaited()
        self.channels[3].send.assert_not_awaited()

    async def test_iv_boundaries_and_gmax_overlap(self):
        for index, (iv, expected) in enumerate((
            ("9.99", "low"), ("10.00", None), ("90.00", None), ("90.01", "high")
        )):
            self.message.id = 200 + index
            self.message.content = f"Congratulations <@999>! You caught a Level 22 Charizard ({iv}%)!"
            before = self.channels[3].send.await_count
            await self.service.handle(self.message)
            self.assertEqual(self.channels[3].send.await_count - before, int(expected is not None))
        self.message.id = 300
        self.message.content = (
            "Congratulations <@999>! You caught a Level 22 Charizard (91.00%)!\n"
            "Woah! It seems that this pokémon has the Gigantamax Factor... ✖️"
        )
        await self.service.handle(self.message)
        gmax = self.channels[3].send.await_args_list[-2].kwargs["embed"]
        self.assertIn("Gigantamax Charizard", gmax.description)
        self.assertIn("/10196.png", gmax.thumbnail.url)
        self.assertIn("Unknown", gmax.description)
        self.assertIn("High IV", self.channels[3].send.await_args.kwargs["embed"].title)

    async def test_shiny_counter_and_deduplication_across_edits_and_restarts(self):
        self.message.content += "\nThese colors seem unusual... ✨\nChain: 1349"
        await asyncio.gather(self.service.handle(self.message), self.service.handle(self.message))
        self.assertEqual(self.channels[2].send.await_count, 1)
        self.assertEqual(self.channels[2].name, "shinyboard-356")
        embed = self.channels[2].send.await_args.kwargs["embed"]
        self.assertIn("**Chain:** `1349`", embed.description)
        self.assertIn("/shiny/6.png", embed.thumbnail.url)
        self.channels[2].name = "shinies-956"
        self.message.id += 1
        await StarboardService(self.cog).handle(self.message)
        self.assertEqual(self.channels[2].name, "shinies-957")
        self.channels[2].name = "shinies-5"
        self.message.id += 1
        await self.service.handle(self.message)
        self.assertEqual(self.channels[2].name, "shinies-958")

    async def test_edit_can_add_shiny_without_reposting_main(self):
        self.message.content = "Congratulations <@999>! You caught a Level 3 Miraidon (50.54%)!"
        await self.service.handle(self.message)
        self.message.content += "\nThese colors seem unusual... ✨"
        await self.service.handle(self.message)
        self.assertEqual(self.channels[1].send.await_count, 1)
        self.assertEqual(self.channels[2].send.await_count, 1)

    async def test_settings_open_and_authorization(self):
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42, guild_permissions=SimpleNamespace(manage_guild=False)),
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )
        root = ServerSettingsView(42, self.cog, 123)
        await root.open_starboard_settings(interaction)
        view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(view, StarboardSettingsView)
        self.assertTrue(view.has_components_v2())
        select = view.children[0].children[3].children[0]
        await select.callback(interaction)
        interaction.response.send_message.assert_awaited_once()
        self.assertEqual(view.settings()["main"], 1)

    async def test_channel_selection_saves_and_can_disable(self):
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42, guild_permissions=SimpleNamespace(manage_guild=True)),
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )
        view = StarboardSettingsView(self.cog, 42, 123)
        select = view.children[0].children[3].children[0]
        select._values = [SimpleNamespace(id=4)]
        await select.callback(interaction)
        self.assertEqual(view.settings()["main"], 4)
        select = view.children[0].children[3].children[0]
        select._values = []
        await select.callback(interaction)
        self.assertIsNone(view.settings()["main"])
        self.assertEqual(self.cog.save_bot_state.call_count, 2)

    async def test_listener_routes_catches_without_premium(self):
        self.cog.track_incense = Mock()
        self.cog.maybe_pause_after_incense_purchase = AsyncMock()
        self.cog.premium_tier = Mock(return_value=None)
        self.message.content = "Congratulations <@999>! You caught a Level 3 Miraidon (50.54%)!"
        await self.cog.on_message(self.message)
        self.channels[1].send.assert_awaited_once()

    async def test_poketwo_iv_label_routes_to_all_matching_boards(self):
        self.message.content = (
            "Congratulations <@999>! You caught a level 3 Miraidon (IV: 91.00%)!"
            "\n\nShiny streak reset. (**1,349**)"
            "\n\nThese colors seem unusual... ✨"
        )
        await self.service.handle(self.message)
        for channel in self.channels.values():
            channel.send.assert_awaited_once()
        shiny = self.channels[2].send.await_args.kwargs["embed"]
        self.assertIn("**Chain:** `1,349`", shiny.description)
        self.assertIn("91.00%", shiny.description)
        self.assertIn("High IV", self.channels[3].send.await_args.kwargs["embed"].title)


if __name__ == "__main__":
    unittest.main()
