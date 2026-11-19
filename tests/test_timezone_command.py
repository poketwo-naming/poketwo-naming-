import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot import (
    PokéTwoNamingBot,
    find_place_for_phase,
    phase_at_location_time,
    timezone_locations,
)


class TimezoneCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.ctx = SimpleNamespace(send=AsyncMock())

    async def test_tz_returns_one_place_with_copy_command_and_phase_emoji(self):
        with patch("bot.find_place_for_phase", return_value="Tokyo"):
            await PokéTwoNamingBot.timezone_command.callback(
                self.cog,
                self.ctx,
                phase="NIGHT",
            )

        self.ctx.send.assert_awaited_once_with(
            "This Tokyo is night.\n"
            "Copy and paste: `<@716390085896962058> tz Tokyo` 🌙"
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

    def test_phase_uses_city_local_time_boundaries(self):
        timezone_name = "America/Sao_Paulo"
        for local_hour, expected_phase in (
            (4, "night"),
            (5, "dawn"),
            (6, "dawn"),
            (7, "day"),
            (16, "day"),
            (17, "dusk"),
            (18, "dusk"),
            (19, "night"),
        ):
            with self.subTest(local_hour=local_hour):
                now = datetime(
                    2026,
                    11,
                    19,
                    local_hour + 3,
                    tzinfo=timezone.utc,
                )
                self.assertEqual(
                    phase_at_location_time(now, timezone_name),
                    expected_phase,
                )

    def test_selected_place_matches_requested_local_phase(self):
        now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
        locations = timezone_locations()

        for phase in ("day", "night", "dawn", "dusk"):
            with self.subTest(phase=phase):
                place = find_place_for_phase(phase, now)

                self.assertIsNotNone(place)
                self.assertTrue(
                    any(
                        candidate == place
                        and phase_at_location_time(now, timezone_name) == phase
                        for candidate, timezone_name in locations
                    ),
                )


if __name__ == "__main__":
    unittest.main()
