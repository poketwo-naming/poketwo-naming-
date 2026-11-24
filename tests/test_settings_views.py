import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from bot import NamingSettingsView, ServerSettingsView


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
