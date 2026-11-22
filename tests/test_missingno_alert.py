import unittest
from collections import OrderedDict, deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from bot import MISSINGNO_ALERT_ROLE_ID, PokéTwoNamingBot


class MissingNoAlertTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {"reserves": {"123": {}}}
        self.cog.pokemon_types = {"MissingNo": []}
        self.cog.pokemon_best_names = {"MissingNo": "MissingNo"}
        self.cog.pokemon_sprite_ids = {}
        self.cog._get_spawn_image = AsyncMock(return_value=(b"image", 0.01))
        self.cog.recognize_spawn_image = Mock(
            return_value=("MissingNo", 99.0, 0.02)
        )
        self.cog.pause_missingno_channel = AsyncMock(return_value=True)
        self.cog.shiny_hunters_for_spawn = Mock(return_value=[])
        self.cog.restricted_role_ids = Mock(return_value={987654321})
        self.cog.spawn_response_times = []
        self.cog.inference_times = []
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

    async def test_missingno_alert_pings_fixed_role_instead_of_restricted_role(self):
        await self.cog.handle_poketwo_spawn(self.message)

        self.assertEqual(self.channel.send.await_count, 2)
        alert = self.channel.send.await_args_list[1].args[0]
        self.assertIn(f"<@&{MISSINGNO_ALERT_ROLE_ID}>", alert)
        self.assertNotIn("<@&987654321>", alert)
        self.cog.restricted_role_ids.assert_not_called()


if __name__ == "__main__":
    unittest.main()
