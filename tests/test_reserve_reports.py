import json
import unittest
from types import SimpleNamespace
from typing import Protocol, cast
from unittest.mock import AsyncMock

import numpy as np
from discord.ext import commands

from bot import POKETWO_BOT_ID, PokéTwoNamingBot


class ReportCommandCallback(Protocol):
    async def __call__(
        self,
        cog: PokéTwoNamingBot,
        ctx: commands.Context,
    ) -> None: ...


class ReportErrorCallback(Protocol):
    async def __call__(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None: ...


class ReserveReportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.class_names = {"pikachu": "Pikachu"}
        self.cog.pokemon_species = {"Pikachu": 25}
        self.cog.pokemon_spawn_chances = {
            "pikachu": {
                "Pokemon": "Pikachu",
                "Chance": "1/899",
                "Chance percentage": "0.1112%",
                "Dex": "25",
            }
        }
        self.cog.bot_state = {
            "categories": {},
            "reserves": {"123": {"Pikachu": ["456"]}},
        }
        self.spawn = SimpleNamespace(
            id=100,
            author=SimpleNamespace(id=POKETWO_BOT_ID),
        )
        self.catch = SimpleNamespace(
            id=101,
            author=SimpleNamespace(id=POKETWO_BOT_ID),
            content="Congratulations <@999>! You caught a Level 5 Pikachu!",
            embeds=[],
            reference=SimpleNamespace(resolved=self.spawn),
            channel=SimpleNamespace(id=200),
        )
        self.cog.is_spawn_message = lambda message: message is not None
        self.report_spawn_evidence = AsyncMock(return_value=[])
        self.cog.report_spawn_evidence = self.report_spawn_evidence
        self.report_channel = SimpleNamespace(send=AsyncMock())
        self.cog.bot = SimpleNamespace(
            user=SimpleNamespace(id=77),
            get_channel=lambda channel_id: (
                self.report_channel
                if channel_id == 1532512015703085147
                else None
            ),
        )
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=456),
            message=SimpleNamespace(
                reference=SimpleNamespace(resolved=self.catch),
            ),
            channel=SimpleNamespace(),
            send=AsyncMock(),
        )

    async def submit_report(self):
        callback = cast(
            ReportCommandCallback,
            PokéTwoNamingBot.report_stolen_reserve.callback,
        )
        await callback(self.cog, cast(commands.Context, self.ctx))

    def test_reads_reserve_mentions_from_embedded_field(self):
        message = SimpleNamespace(
            content="Pikachu ⚡ 99.00%",
            embeds=[
                SimpleNamespace(
                    title="",
                    description="",
                    fields=[
                        SimpleNamespace(
                            name="Reserve pings",
                            value="<@456> <@!789>",
                        )
                    ],
                )
            ],
        )

        self.assertEqual(
            self.cog.report_naming_bot_evidence(message),
            ("Pikachu", {"456", "789"}),
        )

    def test_interpolates_spawn_rate_and_clamps_to_price_limits(self):
        self.cog.pokemon_spawn_chances["testmon"] = {
            "Pokemon": "Testmon",
            "Chance": "1/1100",
            "Chance percentage": "0.0909%",
            "Dex": "1000",
        }
        self.cog.pokemon_spawn_chances["commonmon"] = {
            "Pokemon": "Commonmon",
            "Chance": "1/100",
            "Chance percentage": "1%",
            "Dex": "1001",
        }
        self.cog.pokemon_spawn_chances["raremon"] = {
            "Pokemon": "Raremon",
            "Chance": "1/50000",
            "Chance percentage": "0.002%",
            "Dex": "1002",
        }

        self.assertEqual(self.cog.spawn_rate_report_price("Testmon"), 17_500)
        self.assertEqual(self.cog.spawn_rate_report_price("Commonmon"), 2_500)
        self.assertEqual(self.cog.spawn_rate_report_price("Raremon"), 50_000)

    def test_highest_overlapping_category_price_overrides_spawn_rate(self):
        self.cog.pokemon_spawn_chances["pikachu"]["Chance"] = "1/30000"
        self.cog.bot_state["categories"]["123"] = {
            "gmax": ["Pikachu"],
            "rare": ["Pikachu"],
        }

        self.assertEqual(
            self.cog.reserve_report_price(123, "Pikachu", ""),
            45_000,
        )

    async def test_only_external_bot_replies_to_the_spawn_are_evidence(self):
        def bot_message(message_id, reply_id, author_id, bot=True):
            return SimpleNamespace(
                id=message_id,
                author=SimpleNamespace(id=author_id, bot=bot),
                content="Pikachu ⚡ 99.00%\nReserved: <@456>",
                embeds=[],
                reference=SimpleNamespace(message_id=reply_id),
            )

        valid = bot_message(201, self.spawn.id, 88)
        wrong_spawn = bot_message(202, 999, 89)
        human_message = bot_message(203, self.spawn.id, 90, bot=False)

        class FakeChannel:
            def history(self, **kwargs):
                self.history_kwargs = kwargs

                async def messages():
                    for message in (valid, wrong_spawn, human_message):
                        yield message

                return messages()

        channel = FakeChannel()

        evidence = await PokéTwoNamingBot.report_spawn_evidence(
            self.cog,
            channel,
            self.spawn,
            self.catch,
        )

        self.assertEqual(evidence, [("Pikachu", {"456"})])
        self.assertEqual(channel.history_kwargs["limit"], 500)
        self.assertEqual(channel.history_kwargs["before"], self.catch)

    async def test_report_follows_catch_command_to_spawn(self):
        self.cog.bot_state["categories"]["123"] = {"rare": ["Pikachu"]}
        catch_command = SimpleNamespace(
            id=102,
            author=SimpleNamespace(id=456),
            reference=SimpleNamespace(resolved=self.spawn),
        )
        self.catch.reference = SimpleNamespace(resolved=catch_command)

        await self.submit_report()

        report = self.report_channel.send.await_args.args[0]
        self.assertIn("45,000 PC", report)
        self.assertIn("https://discord.com/channels/123/200/101", report)
        self.assertIn("<#1538294047095922748>", report)
        self.ctx.send.assert_awaited_once_with(
            "✅ Your stolen-reserve report was submitted."
        )

    async def test_unexpected_report_error_is_logged_and_reported(self):
        error = commands.CommandInvokeError(ValueError("test failure"))
        callback = cast(ReportErrorCallback, self.cog.report_stolen_reserve_error)

        with self.assertLogs("bot", level="ERROR") as logs:
            await callback(cast(commands.Context, self.ctx), error)

        self.assertIn("test failure", "\n".join(logs.output))
        self.ctx.send.assert_awaited_once_with(
            "❌ The report could not be completed. Check the bot logs."
        )

    async def test_unlinked_catch_uses_exact_vivillon_reserve_and_report_format(self):
        self.cog.class_names = {"eevee": "Eevee", "partner eevee": "Partner Eevee"}
        self.cog.pokemon_species = {"Eevee": 133, "Partner Eevee": 133}
        self.cog.pokemon_spawn_chances = {
            "eevee": {
                "Pokemon": "Eevee",
                "Chance": "1/899",
                "Chance percentage": "0.1112%",
                "Dex": "133",
            }
        }
        self.cog.bot_state["reserves"]["123"] = {"Eevee": ["456"]}
        self.catch.content = "Congratulations <@999>! You caught a Level 10 Eevee!"
        self.catch.reference = None

        await self.submit_report()

        report = self.report_channel.send.await_args.args[0]
        self.assertIn("<@999> hey you stole a reserved Pokémon", report)
        self.assertIn("Pokémon: Eevee", report)
        self.assertIn("PC: 15,000 PC", report)
        self.assertIn("<@999> trade <@456> in <#1538294047095922748>", report)
        self.assertIn("https://discord.com/channels/123/200/101", report)
        self.assertIn("form", report.casefold())
        self.assertIn("Other naming-bot reserves could not be verified.", report)
        allowed_mentions = self.report_channel.send.await_args.kwargs[
            "allowed_mentions"
        ].to_dict()
        self.assertEqual(allowed_mentions["users"], [999, 456])
        self.assertNotIn("everyone", allowed_mentions["parse"])
        self.assertNotIn("roles", allowed_mentions["parse"])
        self.report_spawn_evidence.assert_not_awaited()
        self.ctx.send.assert_awaited_once_with(
            "✅ Your stolen-reserve report was submitted."
        )

    async def test_unlinked_eevee_report_with_actual_species_data(self):
        with np.load("pokemon_image_model.npz", allow_pickle=False) as model:
            self.cog.class_names = {
                name.casefold(): name for name in model["classes"]
            }
        with open("pokemon_species.json", encoding="utf-8") as file:
            self.cog.pokemon_species = json.load(file)
        self.cog.pokemon_spawn_chances = self.cog.load_pokemon_spawn_chances()
        self.cog.bot_state["reserves"]["123"] = {"Eevee": ["456"]}
        self.catch.content = (
            "Congratulations <@999>! You caught a Level 10 Eevee ♂ (44.09%)!"
        )
        self.catch.reference = None

        await self.submit_report()

        self.report_channel.send.assert_awaited_once()
        self.ctx.send.assert_awaited_once_with(
            "✅ Your stolen-reserve report was submitted."
        )

    async def test_reporter_without_reserve_cannot_report_unlinked_catch(self):
        self.catch.reference = None
        self.ctx.author.id = 789

        await self.submit_report()

        self.report_channel.send.assert_not_awaited()
        self.assertIn("reserve", self.ctx.send.await_args.args[0].casefold())

    async def test_unlinked_base_catch_does_not_use_form_only_reserve(self):
        self.cog.class_names.update({
            "applin": "Applin",
            "enchanted applin": "Enchanted Applin",
        })
        self.cog.pokemon_species.update({"Applin": 840, "Enchanted Applin": 840})
        self.cog.pokemon_spawn_chances["applin"] = {
            "Pokemon": "Applin",
            "Chance": "1/899",
            "Chance percentage": "0.1112%",
            "Dex": "840",
        }
        self.cog.bot_state["reserves"]["123"] = {"Enchanted Applin": ["456"]}
        self.catch.content = "Congratulations <@999>! You caught an Applin!"
        self.catch.reference = None

        await self.submit_report()

        self.report_channel.send.assert_not_awaited()
        self.assertIn("reserve", self.ctx.send.await_args.args[0].casefold())

    async def test_report_fetches_uncached_destination_channel(self):
        self.catch.reference = None
        self.cog.bot.get_channel = lambda channel_id: None
        self.cog.bot.fetch_channel = AsyncMock(return_value=self.report_channel)

        await self.submit_report()

        self.cog.bot.fetch_channel.assert_awaited_once_with(1532512015703085147)
        self.report_channel.send.assert_awaited_once()

    async def test_reserved_catcher_cannot_be_reported(self):
        self.catch.reference = None
        self.cog.bot_state["reserves"]["123"]["Pikachu"].append("999")

        await self.submit_report()

        self.report_channel.send.assert_not_awaited()
        self.assertIn("reserved", self.ctx.send.await_args.args[0].casefold())

    async def test_naming_bot_evidence_can_show_catcher_is_reserved(self):
        self.report_spawn_evidence.return_value = [("Pikachu", {"999"})]

        await self.submit_report()

        self.report_channel.send.assert_not_awaited()
        self.assertIn("reserved", self.ctx.send.await_args.args[0].casefold())

    async def test_report_accepts_spawn_after_poketwo_edits_its_text(self):
        edited_spawn = SimpleNamespace(
            id=self.spawn.id,
            author=SimpleNamespace(id=POKETWO_BOT_ID),
            content="This Pokémon was caught!",
            embeds=[],
            reference=None,
        )
        self.catch.reference = SimpleNamespace(
            resolved=edited_spawn,
        )

        await self.submit_report()

        self.report_channel.send.assert_awaited_once()
        self.ctx.send.assert_awaited_once_with(
            "✅ Your stolen-reserve report was submitted."
        )

    async def test_custom_species_requires_one_matching_form_prediction(self):
        self.cog.class_names.update({
            "applin": "Applin",
            "enchanted applin": "Enchanted Applin",
            "rotten applin": "Rotten Applin",
        })
        self.cog.pokemon_species.update({
            "Applin": 840,
            "Enchanted Applin": 840,
            "Rotten Applin": 840,
        })
        self.cog.pokemon_spawn_chances = {
            "applin": {
                "Pokemon": "Applin",
                "Chance": "1/899",
                "Chance percentage": "0.1112%",
                "Dex": "840",
            }
        }
        self.cog.bot_state["reserves"]["123"] = {
            "Enchanted Applin": ["456"]
        }
        self.catch.content = "Congratulations <@999>! You caught an Applin!"
        self.report_spawn_evidence.return_value = [
            ("Enchanted Applin", {"456"})
        ]

        await self.submit_report()

        self.assertIn("Enchanted Applin", self.report_channel.send.await_args.args[0])

    async def test_catch_that_names_the_custom_form_needs_no_form_guess(self):
        self.cog.class_names.update({
            "applin": "Applin",
            "enchanted applin": "Enchanted Applin",
            "rotten applin": "Rotten Applin",
        })
        self.cog.pokemon_species.update({
            "Applin": 840,
            "Enchanted Applin": 840,
            "Rotten Applin": 840,
        })
        self.cog.pokemon_spawn_chances = {
            "applin": {
                "Pokemon": "Applin",
                "Chance": "1/899",
                "Chance percentage": "0.1112%",
                "Dex": "840",
            }
        }
        self.cog.bot_state["reserves"]["123"] = {
            "Enchanted Applin": ["456"]
        }
        self.catch.content = (
            "Congratulations <@999>! You caught an Enchanted Applin!"
        )

        await self.submit_report()

        self.assertIn(
            "Enchanted Applin",
            self.report_channel.send.await_args.args[0],
        )

    async def test_conflicting_form_evidence_does_not_send_report(self):
        self.cog.class_names.update({
            "applin": "Applin",
            "enchanted applin": "Enchanted Applin",
            "rotten applin": "Rotten Applin",
        })
        self.cog.pokemon_species.update({
            "Applin": 840,
            "Enchanted Applin": 840,
            "Rotten Applin": 840,
        })
        self.cog.pokemon_spawn_chances = {
            "applin": {
                "Pokemon": "Applin",
                "Chance": "1/899",
                "Chance percentage": "0.1112%",
                "Dex": "840",
            }
        }
        self.catch.content = "Congratulations <@999>! You caught an Applin!"
        self.report_spawn_evidence.return_value = [
            ("Enchanted Applin", {"456"}),
            ("Rotten Applin", {"789"}),
        ]

        await self.submit_report()

        self.report_channel.send.assert_not_awaited()
        self.assertIn(
            "no report was sent",
            self.ctx.send.await_args.args[0],
        )

    async def test_missing_spawn_rate_prevents_report(self):
        self.cog.pokemon_spawn_chances = {}

        await self.submit_report()

        self.report_channel.send.assert_not_awaited()
        self.assertIn("no report was sent", self.ctx.send.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
