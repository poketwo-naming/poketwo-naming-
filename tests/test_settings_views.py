import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from bot import NamingSettingsView, PokéTwoNamingBot, ServerSettingsView
from roles_channels import RolesChannelsSettingsView


class SettingsViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = SimpleNamespace(bot_state={}, save_bot_state=Mock())
        self.interaction = SimpleNamespace(
            user=SimpleNamespace(id=42),
            response=SimpleNamespace(
                edit_message=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )

    async def test_naming_open_button_uses_components_v2_view(self):
        root = ServerSettingsView(42, self.cog, 123)
        naming_section = root.children[0].children[2]

        self.assertTrue(root.has_components_v2())
        self.assertEqual(
            naming_section.accessory.callback.__func__,
            ServerSettingsView.open_naming_settings,
        )

    async def test_open_replaces_layout_with_another_components_v2_view(self):
        root = ServerSettingsView(42, self.cog, 123)
        await root.open_naming_settings(self.interaction)

        self.interaction.response.edit_message.assert_awaited_once()
        new_view = self.interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(new_view, NamingSettingsView)
        self.assertTrue(new_view.has_components_v2())

    async def test_setting_button_saves_and_refreshes_layout(self):
        view = NamingSettingsView(self.cog, 42, 123)

        await view.toggle_setting(self.interaction, "only_pings")

        settings = self.cog.bot_state["guild_settings"]["123"]["naming"]
        self.assertTrue(settings["only_pings"])
        self.cog.save_bot_state.assert_called_once()
        self.interaction.response.edit_message.assert_awaited_once_with(view=view)

    async def test_back_reopens_root_with_current_naming_status(self):
        self.cog.bot_state["guild_settings"] = {
            "123": {"naming": {"enabled": False, "mode": "embed"}}
        }
        view = NamingSettingsView(self.cog, 42, 123)

        await view.go_back(self.interaction)

        root = self.interaction.response.edit_message.await_args.kwargs["view"]
        naming_text = root.children[0].children[2].children[0].content
        self.assertIn("Naming `Off`", naming_text)
        self.assertIn("Mode `Embed Mode`", naming_text)

    async def test_other_user_cannot_open_naming_settings(self):
        root = ServerSettingsView(42, self.cog, 123)
        self.interaction.user.id = 7

        await root.open_naming_settings(self.interaction)

        self.interaction.response.edit_message.assert_not_awaited()
        self.interaction.response.send_message.assert_awaited_once()

    async def test_roles_channels_pages_limit_single_settings_to_six(self):
        view = RolesChannelsSettingsView(self.cog, 42, 123)
        page_one_selects = [
            child.children[0]
            for child in view.children[0].children
            if isinstance(child, discord.ui.ActionRow)
            and child.children
            and isinstance(
                child.children[0],
                (RolesChannelsSettingsView.RoleSelect, RolesChannelsSettingsView.ChannelSelect),
            )
        ]

        self.assertEqual(len(page_one_selects), 6)
        await view.next_page(self.interaction)
        self.assertEqual(view.page, 1)
        self.assertIsInstance(
            view.children[0].children[3].children[0],
            RolesChannelsSettingsView.DisabledNamingChannelSelect,
        )

    async def test_disabled_naming_channel_selection_saves_multiple_channels(self):
        interaction = SimpleNamespace(
            user=SimpleNamespace(
                id=42,
                guild_permissions=SimpleNamespace(manage_guild=True),
            ),
            response=SimpleNamespace(
                edit_message=AsyncMock(),
                send_message=AsyncMock(),
            ),
        )
        view = RolesChannelsSettingsView(self.cog, 42, 123)
        view.page = 1
        view.rebuild()
        select = view.children[0].children[3].children[0]
        select._values = [SimpleNamespace(id=10), SimpleNamespace(id=20)]

        await select.callback(interaction)

        self.assertEqual(
            view.settings()["disabled_naming_channels"],
            [10, 20],
        )
        self.cog.save_bot_state.assert_called_once()

    def test_naming_channel_disabled_matches_saved_channel_ids(self):
        cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        cog.bot_state = {
            "guild_settings": {
                "123": {
                    "roles_channels": {
                        "disabled_naming_channels": [10, 20],
                    }
                }
            }
        }
        message = SimpleNamespace(
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=10),
        )

        self.assertTrue(cog.naming_channel_disabled(message))
        message.channel.id = 30
        self.assertFalse(cog.naming_channel_disabled(message))

    async def test_disabled_channel_skips_naming_but_not_starboard(self):
        cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        cog.bot = SimpleNamespace(user=SimpleNamespace(id=999))
        cog.bot_state = {
            "guild_settings": {
                "123": {
                    "starboard": {"main": 1},
                    "roles_channels": {
                        "disabled_naming_channels": [10],
                    },
                }
            }
        }
        cog.track_incense = Mock()
        cog.maybe_pause_after_incense_purchase = AsyncMock()
        cog.starboard_service = SimpleNamespace(handle=AsyncMock())
        cog.premium_tier = Mock(return_value=1)
        cog.handle_poketwo_spawn = AsyncMock()
        message = SimpleNamespace(
            author=SimpleNamespace(id=716390085896962058),
            content="A wild pokémon has appeared!",
            embeds=[],
            guild=SimpleNamespace(id=123),
            channel=SimpleNamespace(id=10),
        )

        await cog.on_message(message)

        cog.starboard_service.handle.assert_awaited_once_with(message)
        cog.handle_poketwo_spawn.assert_not_awaited()
