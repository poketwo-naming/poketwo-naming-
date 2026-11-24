import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bot import (
    FFA_ANNOUNCEMENT_CHANNEL_ID,
    FFA_REVIEW_CHANNEL_ID,
    FFA_ROLE_ID,
    FFANameModal,
    FFAReserveView,
    FFAReviewView,
    PokéTwoNamingBot,
)


class ReserveFFATests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = PokéTwoNamingBot.__new__(PokéTwoNamingBot)
        self.cog.bot_state = {
            "reserves": {"123": {"Pikachu": ["456"], "Eevee": ["456", "789"]}},
            "restricted_roles": {"999": ["42"]},
            "ffa_requests": {},
        }
        self.cog.ffa_requests_in_flight = set()
        self.cog.save_bot_state = Mock()
        self.review_message = SimpleNamespace(id=100, edit=AsyncMock())
        self.review_channel = SimpleNamespace(send=AsyncMock(return_value=self.review_message))
        self.announce_channel = SimpleNamespace(send=AsyncMock())
        self.cog.bot = SimpleNamespace(
            get_channel=Mock(side_effect=lambda channel_id: {
                FFA_REVIEW_CHANNEL_ID: self.review_channel,
                FFA_ANNOUNCEMENT_CHANNEL_ID: self.announce_channel,
            }.get(channel_id)),
            fetch_channel=AsyncMock(),
        )

    def interaction(self, user_id=456):
        return SimpleNamespace(
            user=SimpleNamespace(id=user_id),
            response=SimpleNamespace(
                send_message=AsyncMock(), edit_message=AsyncMock(),
                send_modal=AsyncMock(), defer=AsyncMock(),
            ),
            followup=SimpleNamespace(send=AsyncMock()),
            message=SimpleNamespace(id=100, content="Review request", edit=AsyncMock()),
        )

    def reviewer(self, authorized=True):
        interaction = self.interaction(1000)
        member = Mock(spec=discord.Member)
        member.id = 1000
        member.guild_permissions = SimpleNamespace(administrator=False, manage_guild=False)
        member.roles = [SimpleNamespace(id=42 if authorized else 43)]
        interaction.user = member
        interaction.guild = SimpleNamespace(id=999, owner_id=111)
        return interaction

    async def open_view(self):
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=123, name="Source Server"),
            author=SimpleNamespace(id=456),
            send=AsyncMock(),
        )
        await PokéTwoNamingBot.reserve_afk_command.callback(self.cog, ctx)
        return ctx.send.await_args.kwargs["view"]

    async def request_pikachu(self):
        view = await self.open_view()
        await view.release(self.interaction(), "pikachu")
        interaction = self.interaction()
        await view.announcement.callback(interaction)
        return view, interaction

    async def test_list_and_choose_release_for_multiple_reserves(self):
        view = await self.open_view()
        self.assertIn("Pikachu", view.build_embed().description)
        self.assertIn("Eevee", view.build_embed().description)
        self.assertTrue(view.announcement.disabled)
        other = self.interaction(789)
        self.assertFalse(await view.interaction_check(other))
        other.response.send_message.assert_awaited_once()

        interaction = self.interaction()
        await view.ffa.callback(interaction)
        self.assertIsInstance(interaction.response.send_modal.await_args.args[0], FFANameModal)
        await view.release(self.interaction(), "not a reserve")
        self.assertEqual(self.cog.reserve_user_ids(123, "Eevee"), ["456", "789"])
        await view.release(self.interaction(), "eEvEe")
        self.assertEqual(self.cog.reserve_user_ids(123, "Eevee"), ["789"])
        self.assertEqual(self.cog.reserve_user_ids(123, "Pikachu"), ["456"])
        self.assertFalse(view.announcement.disabled)
        self.assertTrue(view.ffa.disabled)

    async def test_long_reserve_lists_can_be_paginated(self):
        self.cog.bot_state["reserves"]["123"] = {
            f"Pokémon {index:02}": ["456"] for index in range(25)
        }
        view = await self.open_view()
        self.assertIn("Pokémon 00", view.build_embed().description)
        self.assertNotIn("Pokémon 24", view.build_embed().description)
        interaction = self.interaction()
        await view.next.callback(interaction)
        self.assertIn("Pokémon 24", interaction.response.edit_message.await_args.kwargs["embed"].description)
        self.assertNotIn("Pokémon 00", view.build_embed().description)

    async def test_single_reserve_is_released_and_save_failure_rolls_back(self):
        self.cog.bot_state["reserves"]["123"].pop("Eevee")
        view = await self.open_view()
        self.cog.save_bot_state.side_effect = OSError("disk full")
        interaction = self.interaction()
        with self.assertLogs("bot", level="ERROR"):
            await view.ffa.callback(interaction)
        self.assertEqual(self.cog.reserve_user_ids(123, "Pikachu"), ["456"])
        self.assertEqual(self.cog.bot_state["ffa_releases"], {})
        self.assertTrue(view.announcement.disabled)
        self.assertIn("couldn't remove", interaction.response.send_message.await_args.args[0])

        self.cog.save_bot_state.side_effect = None
        await view.ffa.callback(self.interaction())
        self.assertEqual(self.cog.reserve_user_ids(123, "Pikachu"), [])

    async def test_missing_interaction_message_does_not_release_or_request(self):
        view = await self.open_view()
        interaction = self.interaction()
        interaction.message = None
        await view.release(interaction, "Pikachu")
        self.assertEqual(self.cog.reserve_user_ids(123, "Pikachu"), ["456"])
        self.cog.save_bot_state.assert_not_called()
        self.assertIn("message", interaction.response.send_message.await_args.args[0])

        await view.release(self.interaction(), "Pikachu")
        interaction = self.interaction()
        interaction.message = None
        await view.announcement.callback(interaction)
        self.review_channel.send.assert_not_awaited()
        self.assertIn("message", interaction.response.send_message.await_args.args[0])

    async def test_missing_review_message_does_not_decide_or_announce(self):
        await self.request_pikachu()
        view = self.review_channel.send.await_args.kwargs["view"]
        for button in (view.approve, view.deny):
            with self.subTest(button=button.label):
                reviewer = self.reviewer()
                reviewer.message = None
                await button.callback(reviewer)
                self.assertEqual(
                    self.cog.bot_state["ffa_requests"]["100"]["status"], "pending"
                )
                self.announce_channel.send.assert_not_awaited()
                self.assertIn("message", reviewer.response.send_message.await_args.args[0])

    async def test_missing_announcement_channel_keeps_review_pending(self):
        await self.request_pikachu()
        view = self.review_channel.send.await_args.kwargs["view"]
        reviewer = self.reviewer()
        self.cog.bot.get_channel = Mock(return_value=None)
        self.cog.bot.fetch_channel = AsyncMock(return_value=None)
        with self.assertLogs("bot", level="ERROR"):
            await view.approve.callback(reviewer)
        self.assertEqual(self.cog.bot_state["ffa_requests"]["100"]["status"], "pending")
        self.announce_channel.send.assert_not_awaited()
        self.assertIn("announcement channel", reviewer.followup.send.await_args.args[0])

    async def test_other_reserver_blocks_request_but_not_own_release(self):
        view = await self.open_view()
        await view.release(self.interaction(), "Eevee")
        interaction = self.interaction()
        await view.announcement.callback(interaction)
        self.assertEqual(self.cog.reserve_user_ids(123, "Eevee"), ["789"])
        self.review_channel.send.assert_not_awaited()
        self.assertIn("still reserved", interaction.response.send_message.await_args.args[0])

    async def test_shared_releases_cannot_request_duplicate_after_review(self):
        first = await self.open_view()
        await first.release(self.interaction(), "Eevee")
        second = FFAReserveView(self.cog, 123, "Source Server", 789)
        interaction = self.interaction(789)
        interaction.message.id = 101
        await second.release(interaction, "Eevee")
        await second.announcement.callback(interaction)
        review = self.review_channel.send.await_args.kwargs["view"]
        await review.approve.callback(self.reviewer())

        stale = self.interaction()
        await first.announcement.callback(stale)
        self.assertIn("already been requested", stale.response.send_message.await_args.args[0])
        self.review_channel.send.assert_awaited_once()
        self.announce_channel.send.assert_awaited_once()

    async def test_request_has_no_mentions_and_reviewer_must_have_permission(self):
        view, interaction = await self.request_pikachu()
        self.assertTrue(view.announcement.disabled)
        self.assertIn("approval", interaction.followup.send.await_args.args[0])
        review_args = self.review_channel.send.await_args
        self.assertIn("Source Server", review_args.args[0])
        self.assertFalse(review_args.kwargs["allowed_mentions"].roles)
        self.assertFalse(review_args.kwargs["allowed_mentions"].users)
        self.announce_channel.send.assert_not_awaited()

        review = review_args.kwargs["view"]
        unauthorized = self.reviewer(authorized=False)
        await review.approve.callback(unauthorized)
        self.announce_channel.send.assert_not_awaited()
        self.assertEqual(self.cog.bot_state["ffa_requests"]["100"]["status"], "pending")
        unauthorized.response.send_message.assert_awaited_once()

        reviewer = self.reviewer()
        await review.approve.callback(reviewer)
        announcement = self.announce_channel.send.await_args
        self.assertIn(f"<@&{FFA_ROLE_ID}> Pikachu is now FFA", announcement.args[0])
        self.assertIn("Source Server", announcement.args[0])
        mentions = announcement.kwargs["allowed_mentions"]
        self.assertEqual([role.id for role in mentions.roles], [FFA_ROLE_ID])
        self.assertFalse(mentions.users)
        self.assertFalse(mentions.everyone)
        self.assertEqual(self.cog.bot_state["ffa_requests"]["100"]["status"], "approved")
        await review.approve.callback(self.reviewer())
        self.announce_channel.send.assert_awaited_once()

    async def test_denial_does_not_restore_reserve_or_announce(self):
        await self.request_pikachu()
        view = self.review_channel.send.await_args.kwargs["view"]
        await view.deny.callback(self.reviewer())
        self.assertEqual(self.cog.bot_state["ffa_requests"]["100"]["status"], "denied")
        self.assertEqual(self.cog.reserve_user_ids(123, "Pikachu"), [])
        self.announce_channel.send.assert_not_awaited()

    async def test_approval_rechecks_reservations(self):
        await self.request_pikachu()
        self.cog.add_reserve_owner(123, "Pikachu", 789)
        view = self.review_channel.send.await_args.kwargs["view"]
        reviewer = self.reviewer()
        await view.approve.callback(reviewer)
        self.announce_channel.send.assert_not_awaited()
        self.assertEqual(self.cog.bot_state["ffa_requests"]["100"]["status"], "pending")
        self.assertIn("reserved again", reviewer.followup.send.await_args.args[0])

    async def test_unsaved_request_is_disabled_and_can_be_retried(self):
        view = await self.open_view()
        await view.release(self.interaction(), "Pikachu")
        self.cog.save_bot_state.side_effect = OSError("disk full")
        interaction = self.interaction()
        with self.assertLogs("bot", level="ERROR"):
            await view.announcement.callback(interaction)
        self.assertEqual(self.cog.bot_state["ffa_requests"], {})
        self.assertIn("100", self.cog.bot_state["ffa_releases"])
        self.review_message.edit.assert_awaited_once_with(view=None)
        self.assertFalse(view.announcement.disabled)
        self.assertIn("remains removed", interaction.followup.send.await_args.args[0])

    async def test_uncertain_delivery_is_not_retried(self):
        await self.request_pikachu()
        view = self.review_channel.send.await_args.kwargs["view"]
        self.announce_channel.send.side_effect = asyncio.TimeoutError()
        reviewer = self.reviewer()
        with self.assertLogs("bot", level="ERROR"):
            await view.approve.callback(reviewer)
        self.assertEqual(self.cog.bot_state["ffa_requests"]["100"]["status"], "sending")
        self.assertIn("could not be confirmed", reviewer.followup.send.await_args.args[0])
        await view.approve.callback(self.reviewer())
        self.announce_channel.send.assert_awaited_once()

    async def test_simultaneous_approvals_only_send_once(self):
        await self.request_pikachu()
        view = self.review_channel.send.await_args.kwargs["view"]

        async def slow_send(*args, **kwargs):
            await asyncio.sleep(0.01)

        self.announce_channel.send.side_effect = slow_send
        await asyncio.gather(
            view.approve.callback(self.reviewer()),
            view.approve.callback(self.reviewer()),
        )
        self.announce_channel.send.assert_awaited_once()
        self.assertEqual(self.cog.bot_state["ffa_requests"]["100"]["status"], "approved")

    async def test_pending_reviews_are_restored_on_cog_load(self):
        self.cog.bot_state["ffa_requests"] = {
            "100": {"status": "pending"},
            "101": {"status": "sending"},
            "102": {"status": "denied"},
        }
        self.cog.bot.add_view = Mock()
        with (
            patch("bot.aiohttp.TCPConnector"),
            patch("bot.aiohttp.ClientSession"),
        ):
            await self.cog.cog_load()
        calls = self.cog.bot.add_view.call_args_list
        self.assertEqual([call.kwargs["message_id"] for call in calls], [100, 101])
        self.assertTrue(all(isinstance(call.args[0], FFAReviewView) for call in calls))

    async def test_released_reserve_view_is_restored_after_restart(self):
        view = await self.open_view()
        await view.release(self.interaction(), "Pikachu")
        self.assertIsNone(view.timeout)
        self.cog.bot.add_view = Mock()
        with (
            patch("bot.aiohttp.TCPConnector"),
            patch("bot.aiohttp.ClientSession"),
        ):
            await self.cog.cog_load()
        restored = self.cog.bot.add_view.call_args.args[0]
        self.assertIsInstance(restored, FFAReserveView)
        self.assertEqual(restored.released, "Pikachu")
        self.assertFalse(restored.announcement.disabled)
        await restored.announcement.callback(self.interaction())
        self.assertEqual(self.cog.bot_state["ffa_releases"], {})
        self.assertEqual(self.cog.bot_state["ffa_requests"]["100"]["status"], "pending")

    async def test_release_and_review_state_round_trip_to_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("bot.BOT_STATE_FILE", str(Path(directory) / "state.json")):
                self.cog.save_bot_state = PokéTwoNamingBot.save_bot_state.__get__(self.cog)
                view = await self.open_view()
                await view.release(self.interaction(), "Pikachu")
                reloaded = self.cog.load_bot_state()
                self.assertEqual(reloaded["ffa_releases"]["100"]["pokemon"], "Pikachu")
                await view.announcement.callback(self.interaction())
                reloaded = self.cog.load_bot_state()
                self.assertEqual(reloaded["ffa_releases"], {})
                self.assertEqual(reloaded["ffa_requests"]["100"]["status"], "pending")
