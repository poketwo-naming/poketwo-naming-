import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot import (
    PokéTwoNamingBot,
    find_place_for_solar_phase,
    solar_phase_at_location,
    timezone_locations,
)


class TimezoneCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.ctx = SimpleNamespace(send=AsyncMock())

    async def test_tz_returns_one_place_with_copy_command_and_phase_emoji(self):
        with patch("bot.find_place_for_solar_phase", return_value="Tokyo"):
            await PokéTwoNamingBot.timezone_command.callback(
                self.cog,
                self.ctx,
                phase="NIGHT",
            )

        self.ctx.send.assert_awaited_once_with(
            "This Tokyo is night.\n"
            "Copy and paste: `@poketwo tz Tokyo` 🌙"
        )

    async def test_tz_rejects_unknown_phase(self):
        await PokéTwoNamingBot.timezone_command.callback(
            self.cog,
            self.ctx,
            phase="sunset",
        )

        self.ctx.send.assert_awaited_once_with(
            "Use `v!tz day`, `v!tz night`, `v!tz dawn`, or `v!tz dusk`."
        )

    def test_selected_place_matches_requested_solar_phase(self):
        now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
        locations = {
            place: (latitude, longitude)
            for place, latitude, longitude in timezone_locations()
        }

        for phase in ("day", "night", "dawn", "dusk"):
            with self.subTest(phase=phase):
                place = find_place_for_solar_phase(phase, now)

                self.assertIsNotNone(place)
                self.assertEqual(
                    solar_phase_at_location(now, *locations[place]),
                    phase,
                )


if __name__ == "__main__":
    unittest.main()
