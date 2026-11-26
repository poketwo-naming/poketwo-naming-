import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bot import ClearReservesView, PokéTwoNamingBot
from dex_tracking import (
    DexSettingsView, DexTrackingService, active_dex_entries, dex_entries, dex_ping_owners,
    remove_caught_dex_entry,
)


class DexTrackingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {
            "collections": {"123": {"456": ["Latios"]}},
            "dex_tracking": {},
        }
        self.cog.pokemon_species = {
            "Latios": 381, "Solgaleo": 791, "Poipole": 803,
            "Kubfu": 891, "Alolan Meowth": 52, "Meowth": 52,
        }
        self.cog.class_names = {name.casefold(): name for name in self.cog.pokemon_species}
        self.cog.pokemon_aliases = {}
        self.cog.save_bot_state = Mock()
        self.service = DexTrackingService(self.cog, 716390085896962058)
        self.cog.dex_tracking_service = self.service
        self.cog.breeding_box_service = SimpleNamespace(handle_list_edit=AsyncMock())
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=456),
            message=SimpleNamespace(reference=SimpleNamespace(message_id=555)),
            channel=SimpleNamespace(id=789, fetch_message=AsyncMock(), send=AsyncMock()),
            send=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock())),
        )

    def page(self, entries):
        embed = discord.Embed(title="Your pokédex")
        for name, species_id in entries:
            embed.add_field(
                name=f"<:pokemon:123456789> **{name}**\n#{species_id}",
                value="❌ Not caught yet!",
            )
        return SimpleNamespace(
            id=555, guild=self.ctx.guild, channel=self.ctx.channel,
            author=SimpleNamespace(id=716390085896962058),
            content="", embeds=[embed], components=[],
        )

    async def test_pages_are_ordered_deduplicated_and_caught_entries_stay_removed(self):
        first = self.page([("Latios", 381), ("Solgaleo", 791), ("Poipole", 803)])
        self.ctx.channel.fetch_message.return_value = first
        await self.service.append(self.ctx)
        settings = self.service.settings(123, 456)
        self.assertEqual([x["name"] for x in settings["queue"]], ["Latios", "Solgaleo", "Poipole"])

        message = SimpleNamespace(
            guild=self.ctx.guild, content="Congratulations <@456>! You caught a Level 22 Latios (52.15%)!",
            embeds=[],
        )
        remove_caught_dex_entry(self.cog, message)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Solgaleo"), ["456"])
        self.assertEqual(self.cog.bot_state["collections"]["123"]["456"], ["Latios"])

        await PokéTwoNamingBot.on_raw_message_edit(
            self.cog, SimpleNamespace(data={"embeds": []}, message=first)
        )
        next_page = self.page([("Poipole", 803), ("Kubfu", 891)])
        await PokéTwoNamingBot.on_raw_message_edit(
            self.cog, SimpleNamespace(data={"embeds": []}, message=next_page)
        )
        self.assertEqual([x["name"] for x in settings["queue"]], ["Solgaleo", "Poipole", "Kubfu"])
        self.assertIn("Added **1**", self.ctx.send.return_value.edit.await_args.kwargs["content"])

    async def test_modes_pause_and_clear_do_not_change_manual_collection(self):
        self.ctx.channel.fetch_message.return_value = self.page(
            [("Latios", 381), ("Solgaleo", 791), ("Poipole", 803)]
        )
        await self.service.append(self.ctx)
        view = DexSettingsView(self.service, 123, 456)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=456),
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )
        self.assertEqual(dex_ping_owners(self.cog, 123, "Solgaleo"), [])
        await view.mode.callback(interaction)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Solgaleo"), ["456"])
        self.assertEqual(dex_ping_owners(self.cog, 123, "Poipole"), [])
        await view.mode.callback(interaction)
        await view.mode.callback(interaction)
        await view.mode.callback(interaction)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Poipole"), ["456"])
        await view.pause.callback(interaction)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Latios"), [])
        await view.pause.callback(interaction)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Latios"), ["456"])
        other = SimpleNamespace(user=SimpleNamespace(id=999), response=interaction.response)
        self.assertFalse(await view.interaction_check(other))
        await view.clear.callback(interaction)
        self.assertEqual(self.service.settings(123, 456)["queue"], [])
        self.assertEqual(self.cog.bot_state["collections"]["123"]["456"], ["Latios"])
        await self.service.handle_list_edit(self.page([("Kubfu", 891)]))
        self.assertEqual(self.service.settings(123, 456)["queue"], [])

    async def test_member_removal_preserves_queue_and_cancels_page_tracking(self):
        self.ctx.channel.fetch_message.return_value = self.page([("Latios", 381)])
        await self.service.append(self.ctx)
        self.cog.bot = SimpleNamespace(guilds=[])
        self.cog.clear_member_server_data(123, 456)
        await self.service.handle_list_edit(self.page([("Solgaleo", 791)]))
        self.assertEqual(
            self.service.settings(123, 456)["queue"], [{"id": 381, "name": "Latios"}]
        )

    async def test_expired_session_and_restart_keep_saved_queue_until_caught_or_cleared(self):
        self.ctx.channel.fetch_message.return_value = self.page(
            [("Latios", 381), ("Solgaleo", 791)]
        )
        with TemporaryDirectory() as directory:
            with patch("bot.BOT_STATE_FILE", str(Path(directory) / "state.json")):
                self.cog.save_bot_state = PokéTwoNamingBot.save_bot_state.__get__(self.cog)
                await self.service.append(self.ctx)
                status = self.ctx.send.await_args.args[0]
                self.assertIn("Added Pokémon stay in your queue", status)
                self.assertIn("Only page tracking stops", status)

                for session in self.service.sessions.values():
                    session.expires_at = 0
                await self.service.handle_list_edit(self.page([("Poipole", 803)]))
                self.assertEqual(len(self.service.settings(123, 456)["queue"]), 2)

                self.cog.bot_state = self.cog.load_bot_state()
                self.service = DexTrackingService(self.cog, 716390085896962058)
                self.cog.dex_tracking_service = self.service
                self.assertEqual(dex_ping_owners(self.cog, 123, "Latios"), ["456"])
                self.assertEqual(
                    self.service.settings(123, 456)["queue"],
                    [{"id": 381, "name": "Latios"}, {"id": 791, "name": "Solgaleo"}],
                )
                catch = SimpleNamespace(
                    guild=self.ctx.guild,
                    content="Congratulations <@456>! You caught a Level 8 Latios (50.00%)!",
                    embeds=[],
                )
                remove_caught_dex_entry(self.cog, catch)
                self.cog.bot_state = self.cog.load_bot_state()
                self.assertEqual(
                    self.service.settings(123, 456)["queue"],
                    [{"id": 791, "name": "Solgaleo"}],
                )
                self.service.clear(123, 456)
                self.cog.bot_state = self.cog.load_bot_state()
                self.assertEqual(self.service.settings(123, 456)["queue"], [])

    async def test_species_matching_and_catch_from_inactive_queue(self):
        settings = self.service.settings(123, 456)
        settings["queue"] = [{"id": 381, "name": "Latios"}, {"id": 52, "name": "Meowth"}]
        self.assertEqual(dex_ping_owners(self.cog, 123, "Alolan Meowth"), [])
        message = SimpleNamespace(
            guild=self.ctx.guild,
            content="Congratulations <@456>! You caught a Level 8 Alolan Meowth (50.00%)!",
            embeds=[],
        )
        remove_caught_dex_entry(self.cog, message)
        self.assertEqual(settings["queue"], [{"id": 381, "name": "Latios"}])

    async def test_catch_listener_runs_without_premium_and_blocks_stale_pages(self):
        self.ctx.channel.fetch_message.return_value = self.page([("Latios", 381)])
        await self.service.append(self.ctx)
        self.cog.bot = SimpleNamespace(user=SimpleNamespace(id=1))
        self.cog.track_incense = Mock()
        self.cog.maybe_pause_after_incense_purchase = AsyncMock()
        self.cog.premium_tier = Mock(return_value=None)
        message = SimpleNamespace(
            guild=self.ctx.guild, author=SimpleNamespace(id=716390085896962058),
            content="Congratulations <@456>! You caught a Level 8 Solgaleo (50.00%)!",
            embeds=[],
        )
        await self.cog.on_message(message)
        await self.service.handle_list_edit(self.page([("Solgaleo", 791)]))
        self.assertEqual(
            self.service.settings(123, 456)["queue"], [{"id": 381, "name": "Latios"}]
        )

    async def test_spawn_output_respects_dex_pause_and_reservations(self):
        settings = self.service.settings(123, 456)
        settings["queue"] = [{"id": 381, "name": "Latios"}]
        self.cog.bot_state.update({"reserves": {}, "shiny_hunts": {}, "afk": {}})
        self.cog.pokemon_types = {"Latios": []}
        self.cog.pokemon_best_names = {"Latios": "Latios"}
        self.cog.type_ping_owners = Mock(return_value=[])
        self.cog.quest_ping_owners = Mock(return_value=[])
        content, _ = self.cog.format_spawn_prediction("Latios", 99, 123)
        self.assertIn("Dex pings: <@456>", content)
        settings["paused"] = True
        content, _ = self.cog.format_spawn_prediction("Latios", 99, 123)
        self.assertNotIn("Dex pings:", content)
        settings["paused"] = False
        self.cog.bot_state["reserves"] = {"123": {"Latios": ["789"]}}
        content, _ = self.cog.format_spawn_prediction("Latios", 99, 123)
        self.assertNotIn("Dex pings:", content)

    async def test_target_modes_and_reserved_queue_reactivates_in_order(self):
        settings = self.service.settings(123, 456)
        settings["queue"] = [
            {"id": number, "name": name} for name, number in
            [("Latios", 381), ("Solgaleo", 791), ("Poipole", 803), ("Kubfu", 891)]
        ]
        self.cog.bot_state["reserves"] = {"123": {"Latios": ["789", "999"]}}
        view = DexSettingsView(self.service, 123, 456)
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
        self.assertIn("**Active:** Solgaleo", view.embed().description)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Latios"), [])
        self.assertEqual(dex_ping_owners(self.cog, 123, "Solgaleo"), ["456"])
        self.cog.remove_reserve_owner(123, "Latios", 789)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Solgaleo"), ["456"])
        self.cog.remove_reserve_owner(123, "Latios", 999)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Latios"), ["456"])
        self.assertEqual(dex_ping_owners(self.cog, 123, "Solgaleo"), [])
        self.assertEqual(len(settings["queue"]), 4)
        for expected in (2, 5, 10, "all", 1):
            await view.mode.callback(interaction)
            self.assertEqual(settings["mode"], expected)

    async def test_target_limits_and_reserved_forms(self):
        self.cog.pokemon_species.update({f"Species {i}": 2000 + i for i in range(12)})
        self.cog.class_names.update({
            name.casefold(): name for name in self.cog.pokemon_species
        })
        settings = self.service.settings(123, 456)
        settings["queue"] = [{"id": 52, "name": "Meowth"}] + [
            {"id": 2000 + i, "name": f"Species {i}"} for i in range(12)
        ]
        self.cog.bot_state["reserves"] = {"123": {"Alolan Meowth": ["789"]}}
        for mode, count in ((1, 1), (2, 2), (5, 5), (10, 10), ("all", 13)):
            settings["mode"] = mode
            self.assertEqual(len(active_dex_entries(self.cog, 123, settings)), count)
            self.assertEqual(dex_ping_owners(self.cog, 123, "Meowth"), ["456"])
            self.assertEqual(dex_ping_owners(self.cog, 123, "Alolan Meowth"), [])
        self.cog.bot_state["reserves"]["123"]["Meowth"] = ["456"]
        settings["mode"] = 1
        self.assertEqual(active_dex_entries(self.cog, 123, settings)[0]["name"], "Species 0")
        self.assertEqual(len(settings["queue"]), 13)

    async def test_open_settings_refresh_on_reserve_changes_and_cleanup(self):
        settings = self.service.settings(123, 456)
        settings["queue"] = [{"id": 381, "name": "Latios"}, {"id": 791, "name": "Solgaleo"}]
        self.cog.bot_state["reserves"] = {"123": {}}
        with TemporaryDirectory() as directory:
            with patch("bot.BOT_STATE_FILE", str(Path(directory) / "state.json")):
                self.cog.save_bot_state = PokéTwoNamingBot.save_bot_state.__get__(self.cog)
                self.ctx.send.return_value = SimpleNamespace(edit=AsyncMock())
                await PokéTwoNamingBot.dex_help.callback(self.cog, self.ctx)
                view = self.ctx.send.await_args.kwargs["view"]
                self.cog.add_reserve_owner(123, "Latios", 789)
                self.cog.save_bot_state()
                await self.service.refresh_task
                self.assertIn("**Active:** Solgaleo", view.message.edit.await_args.kwargs["embed"].description)
                self.cog.remove_reserve_owner(123, "Latios")
                self.cog.save_bot_state()
                await self.service.refresh_task
                self.assertIn("**Active:** Latios", view.message.edit.await_args.kwargs["embed"].description)
                await view.on_timeout()
                self.assertNotIn(view, self.service.settings_views)

    async def test_reserve_changes_during_refresh_show_latest_state(self):
        settings = self.service.settings(123, 456)
        settings["queue"] = [{"id": 381, "name": "Latios"}, {"id": 791, "name": "Solgaleo"}]
        self.cog.bot_state["reserves"] = {"123": {}}
        started = asyncio.Event()
        release = asyncio.Event()

        async def edit(**kwargs):
            started.set()
            await release.wait()

        with TemporaryDirectory() as directory:
            with patch("bot.BOT_STATE_FILE", str(Path(directory) / "state.json")):
                self.cog.save_bot_state = PokéTwoNamingBot.save_bot_state.__get__(self.cog)
                self.ctx.send.return_value = SimpleNamespace(edit=AsyncMock(side_effect=edit))
                await PokéTwoNamingBot.dex_help.callback(self.cog, self.ctx)
                view = self.ctx.send.await_args.kwargs["view"]
                self.cog.add_reserve_owner(123, "Latios", 789)
                self.cog.save_bot_state()
                await started.wait()
                self.cog.remove_reserve_owner(123, "Latios")
                self.cog.save_bot_state()
                release.set()
                await self.service.refresh_task
                self.assertEqual(view.message.edit.await_count, 2)
                self.assertIn("**Active:** Latios", view.message.edit.await_args.kwargs["embed"].description)

    async def test_clear_all_reserves_refreshes_open_dex_settings(self):
        settings = self.service.settings(123, 456)
        settings["queue"] = [{"id": 381, "name": "Latios"}, {"id": 791, "name": "Solgaleo"}]
        self.cog.bot_state["reserves"] = {"123": {"Latios": ["789"]}}
        with TemporaryDirectory() as directory:
            with patch("bot.BOT_STATE_FILE", str(Path(directory) / "state.json")):
                self.cog.save_bot_state = PokéTwoNamingBot.save_bot_state.__get__(self.cog)
                self.ctx.send.return_value = SimpleNamespace(edit=AsyncMock())
                await PokéTwoNamingBot.dex_help.callback(self.cog, self.ctx)
                view = self.ctx.send.await_args.kwargs["view"]
                self.assertIn("**Active:** Solgaleo", view.embed().description)
                interaction = SimpleNamespace(
                    user=SimpleNamespace(id=456),
                    response=SimpleNamespace(edit_message=AsyncMock()),
                )
                await ClearReservesView(self.cog, 123, 456).confirm_clear.callback(interaction)
                await self.service.refresh_task
                self.assertIn("**Active:** Latios", view.message.edit.await_args.kwargs["embed"].description)

    def test_description_entries_and_caught_entries(self):
        embed = discord.Embed(
            title="Your pokédex",
            description="🛩️ **Latios**\n#381\n❌ Not caught yet!\n"
            "☀️ **Solgaleo**\n#791\n✅ Caught!",
        )
        message = SimpleNamespace(content="", embeds=[embed], components=[])
        self.assertEqual(dex_entries(message), [{"id": 381, "name": "Latios"}])

    def test_screenshot_style_nine_fields_and_component_text(self):
        names = [
            ("Latios", 381), ("Solgaleo", 791), ("Poipole", 803),
            ("Kubfu", 891), ("Spectrier", 897), ("Great Tusk", 984),
            ("Iron Moth", 994), ("Chien-Pao", 1002), ("Iron Valiant", 1006),
        ]
        embed = discord.Embed(title="Your pokédex")
        for name, species_id in names:
            embed.add_field(name=f"<:poke:123456789> **{name} #{species_id}**", value="❌ Not caught yet!")
        message = SimpleNamespace(content="", embeds=[embed], components=[])
        self.assertEqual(dex_entries(message), [{"id": number, "name": name} for name, number in names])
        embed = discord.Embed(title="Your pokédex")
        embed.add_field(name="🐉 **Latios**\n**#381**", value="❌ Not caught yet!")
        message = SimpleNamespace(content="", embeds=[embed], components=[])
        self.assertEqual(dex_entries(message), [{"id": 381, "name": "Latios"}])
        container = discord.components.Container(
            {"type": 17, "components": [
                {"type": 10, "content": "Your pokédex"},
                {"type": 10, "content": "**Great Tusk #984**\n❌ Not caught yet!"},
            ]}, None,
        )
        message = SimpleNamespace(content="", embeds=[], components=[container])
        self.assertEqual(dex_entries(message), [{"id": 984, "name": "Great Tusk"}])

    async def test_poketwo_custom_emoji_fields_import_and_follow_pages(self):
        names = [
            ("Kingler", 99), ("Marowak", 105), ("Zapdos", 145),
            ("Ariados", 168), ("Cleffa", 173), ("Quagsire", 195),
            ("Qwilfish", 211), ("Octillery", 224), ("Mantine", 226),
            ("Entei", 244), ("Suicune", 245), ("Ho-Oh", 250),
            ("Camerupt", 323), ("Cradily", 346), ("Walrein", 365),
            ("Relicanth", 369), ("Regirock", 377), ("Regice", 378),
            ("Registeel", 379), ("Latias", 380), ("Latios", 381),
        ]

        def page(entries):
            embed = discord.Embed(title="Your pokédex")
            for name, number in entries:
                embed.add_field(
                    name=f"<:_:123456789> {name} #{number}",
                    value="<:_:725819513119047822> Not caught yet!\n"
                    "<:_:725819513119047822> Not hatched yet!",
                )
            embed.add_field(
                name="<:_:123456789> Pikachu #25",
                value="<:_:725819513358254101> 1 caught!\n"
                "<:_:725819513119047822> Not hatched yet!",
            )
            return SimpleNamespace(
                id=555, guild=self.ctx.guild, channel=self.ctx.channel,
                author=SimpleNamespace(id=716390085896962058),
                content="", embeds=[embed], components=[],
            )

        self.ctx.channel.fetch_message.return_value = page(names)
        await self.service.append(self.ctx)
        queue = self.service.settings(123, 456)["queue"]
        self.assertEqual(queue, [{"id": number, "name": name} for name, number in names])
        await self.service.handle_list_edit(page([("Rayquaza", 384), ("Jirachi", 385)]))
        self.assertEqual(
            queue[-2:], [{"id": 384, "name": "Rayquaza"}, {"id": 385, "name": "Jirachi"}]
        )

    def counted_page(self, entries):
        embed = discord.Embed(title="Your pokédex")
        for name, species_id, count in entries:
            embed.add_field(
                name=f"<:_:123456789> {name} #{species_id}",
                value=f"<:_:725819513358254101> {count:,} caught!\n"
                "<:_:725819513119047822> Not hatched yet!",
            )
        return SimpleNamespace(
            id=555, guild=self.ctx.guild, channel=self.ctx.channel,
            author=SimpleNamespace(id=716390085896962058),
            content="", embeds=[embed], components=[],
        )

    async def test_catch_goals_import_counts_and_skip_at_threshold(self):
        entries = [
            ("Latios", 381, 9), ("Solgaleo", 791, 10),
            ("Poipole", 803, 99), ("Kubfu", 891, 1_000),
        ]
        page = self.counted_page(entries)
        for goal in (10, 100, 1_000, 10_000):
            with self.subTest(goal=goal):
                settings = self.service.settings(123, 456)
                settings["goal"] = goal
                settings["queue"] = []
                self.ctx.channel.fetch_message.return_value = page
                await self.service.append(self.ctx)
                self.assertEqual(
                    [entry["id"] for entry in settings["queue"]],
                    [species_id for _, species_id, count in entries if count < goal],
                )
                self.assertEqual(
                    [entry["caught"] for entry in settings["queue"]],
                    [count for _, _, count in entries if count < goal],
                )

    async def test_screenshot_page_goal_ten_imports_only_under_ten_in_order(self):
        counts = [
            ("Bulbasaur", 1, 537), ("Ivysaur", 2, 14), ("Venusaur", 3, 121),
            ("Charmander", 4, 29), ("Charmeleon", 5, 11), ("Charizard", 6, 31),
            ("Squirtle", 7, 14), ("Wartortle", 8, 21), ("Blastoise", 9, 151),
            ("Caterpie", 10, 67), ("Metapod", 11, 15), ("Butterfree", 12, 407),
            ("Weedle", 13, 66), ("Kakuna", 14, 13), ("Beedrill", 15, 4),
            ("Pidgey", 16, 80), ("Pidgeotto", 17, 20), ("Pidgeot", 18, 4),
            ("Rattata", 19, 68), ("Raticate", 20, 19), ("Spearow", 21, 23),
        ]
        settings = self.service.settings(123, 456)
        settings["goal"] = 10
        self.ctx.channel.fetch_message.return_value = self.counted_page(counts)
        await self.service.append(self.ctx)
        self.assertEqual(
            settings["queue"],
            [{"id": 15, "name": "Beedrill", "caught": 4},
             {"id": 18, "name": "Pidgeot", "caught": 4}],
        )

    async def test_catches_count_until_goal_and_pause_does_not_stop_progress(self):
        settings = self.service.settings(123, 456)
        settings["goal"] = 10
        self.ctx.channel.fetch_message.return_value = self.counted_page(
            [("Latios", 381, 8), ("Solgaleo", 791, 9)]
        )
        await self.service.append(self.ctx)
        catch = SimpleNamespace(
            guild=self.ctx.guild,
            content="Congratulations <@456>! You caught a Level 22 Latios (52.15%)!",
            embeds=[],
        )
        remove_caught_dex_entry(self.cog, catch)
        self.assertEqual(settings["queue"][0]["caught"], 9)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Latios"), ["456"])
        settings["paused"] = True
        remove_caught_dex_entry(self.cog, catch)
        self.assertEqual(settings["queue"], [{"id": 791, "name": "Solgaleo", "caught": 9}])
        self.assertEqual(dex_ping_owners(self.cog, 123, "Solgaleo"), [])
        settings["paused"] = False
        self.assertEqual(dex_ping_owners(self.cog, 123, "Solgaleo"), ["456"])
        await self.service.handle_list_edit(self.counted_page([("Latios", 381, 8)]))
        self.assertEqual([entry["id"] for entry in settings["queue"]], [791])

    async def test_all_goal_boundaries_and_persisted_counted_queue(self):
        catch = SimpleNamespace(
            guild=self.ctx.guild,
            content="Congratulations <@456>! You caught a Level 22 Latios (52.15%)!",
            embeds=[],
        )
        with TemporaryDirectory() as directory:
            with patch("bot.BOT_STATE_FILE", str(Path(directory) / "state.json")):
                self.cog.save_bot_state = PokéTwoNamingBot.save_bot_state.__get__(self.cog)
                for goal in (10, 100, 1_000, 10_000):
                    with self.subTest(goal=goal):
                        settings = self.service.settings(123, 456)
                        settings["goal"] = goal
                        settings["queue"] = [{"id": 381, "name": "Latios", "caught": goal - 2}]
                        self.cog.save_bot_state()
                        remove_caught_dex_entry(self.cog, catch)
                        self.cog.bot_state = self.cog.load_bot_state()
                        settings = self.service.settings(123, 456)
                        self.assertEqual(settings["queue"][0]["caught"], goal - 1)
                        remove_caught_dex_entry(self.cog, catch)
                        self.cog.bot_state = self.cog.load_bot_state()
                        self.assertEqual(self.service.settings(123, 456)["queue"], [])

    async def test_counted_queue_respects_two_and_all_ping_modes(self):
        settings = self.service.settings(123, 456)
        settings["goal"] = 100
        self.ctx.channel.fetch_message.return_value = self.counted_page(
            [("Latios", 381, 8), ("Solgaleo", 791, 9), ("Poipole", 803, 10)]
        )
        await self.service.append(self.ctx)
        settings["mode"] = 2
        self.assertEqual(dex_ping_owners(self.cog, 123, "Solgaleo"), ["456"])
        self.assertEqual(dex_ping_owners(self.cog, 123, "Poipole"), [])
        settings["mode"] = "all"
        self.assertEqual(dex_ping_owners(self.cog, 123, "Poipole"), ["456"])
        self.service.clear(123, 456)
        self.assertEqual(dex_ping_owners(self.cog, 123, "Latios"), [])

    async def test_goal_selection_updates_current_queue_and_retains_legacy_entries(self):
        settings = self.service.settings(123, 456)
        settings["goal"] = 10_000
        settings["queue"] = [
            {"id": 381, "name": "Latios"},
            {"id": 791, "name": "Solgaleo", "caught": 9},
            {"id": 803, "name": "Poipole", "caught": 10},
        ]
        view = DexSettingsView(self.service, 123, 456)
        settings_message = SimpleNamespace(edit=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=456),
            message=settings_message,
            response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        )
        await view.goal.callback(interaction)
        picker = interaction.response.send_message.await_args.kwargs["view"]
        for expected in (1, 10, 100, 1_000, 10_000):
            picker.select_goal._values = [str(expected)]
            await picker.select_goal.callback(interaction)
            self.assertEqual(settings["goal"], expected)
            if expected == 1:
                self.assertEqual(settings["queue"], [{"id": 381, "name": "Latios"}])
        self.assertIn("10,000", view.embed().description)
        self.assertEqual(view.goal.label, "Catch goal: 10,000")
        settings_message.edit.assert_awaited()

    async def test_import_of_completed_page_keeps_tracking_next_page(self):
        settings = self.service.settings(123, 456)
        settings["goal"] = 10
        self.ctx.channel.fetch_message.return_value = self.counted_page(
            [("Latios", 381, 10)]
        )
        await self.service.append(self.ctx)
        self.assertEqual(settings["queue"], [])
        self.assertIn("Added **0**", self.ctx.send.await_args.args[0])
        await self.service.handle_list_edit(self.counted_page([("Solgaleo", 791, 9)]))
        self.assertEqual(settings["queue"], [{"id": 791, "name": "Solgaleo", "caught": 9}])

    async def test_reimport_refreshes_progress_without_reducing_it(self):
        settings = self.service.settings(123, 456)
        settings["goal"] = 10
        self.ctx.channel.fetch_message.return_value = self.counted_page([("Latios", 381, 8)])
        await self.service.append(self.ctx)
        self.ctx.channel.fetch_message.return_value = self.counted_page([("Latios", 381, 9)])
        await self.service.append(self.ctx)
        self.assertEqual(settings["queue"][0]["caught"], 9)
        self.ctx.channel.fetch_message.return_value = self.counted_page([("Latios", 381, 8)])
        await self.service.append(self.ctx)
        self.assertEqual(settings["queue"][0]["caught"], 9)
        self.ctx.channel.fetch_message.return_value = self.counted_page([("Latios", 381, 10)])
        await self.service.append(self.ctx)
        self.assertEqual(settings["queue"], [])
