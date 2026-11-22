import unittest
from types import SimpleNamespace
from typing import Protocol, cast
from unittest.mock import AsyncMock

from discord.ext import commands

from bot import POKETWO_BOT_ID, PokéTwoNamingBot


class ReportCommandCallback(Protocol):
    async def __call__(
        self,
        cog: PokéTwoNamingBot,
        ctx: commands.Context,
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
        )

        self.assertEqual(evidence, [("Pikachu", {"456"})])
        self.assertEqual(channel.history_kwargs["limit"], 500)
        self.assertNotIn("before", channel.history_kwargs)

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
