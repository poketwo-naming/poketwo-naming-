"""Post update announcements to the configured Discord channel."""
import hashlib
from typing import Protocol

import discord


ANNOUNCEMENT_CHANNEL_ID = 1574489953444827146
ANNOUNCEMENT_ROLE_ID = 1574502724370825286
ANNOUNCEMENT_STATE_KEY = "last_update_announcement"
PENDING_PUBLICATION_KEY = "pending_update_publication"
UPDATE_ANNOUNCEMENT = (
    "**What's new**\n"
    "✨ **Slash Commands** - Vivillon now works with `/` commands!\n"
    "  - Use `/ping`, `/typeping`, `/questping`, `/sr`, `/afk`, `/settings`, and more\n"
    "  - Works when added via 'Add to My Apps' in any server\n"
    "  - Prefix commands (`v!`) still work normally\n\n"
    "🌍 **Quest Pings** - Set which regions to receive quest pings for\n"
    "  - Supports 12 regions: Kanto, Johto, Hoenn, Sinnoh, Unova, Kalos, Alola, Galar, Hisui, Paldea, Kitakami, Paradox\n"
    "  - Use `/questping` or `v!qp` to configure\n\n"
    "💔 **Improved Daycare Pairing** - Shows all compatible breeding pairs\n"
    "  - Ditto takes priority: pairs with any compatible Pokémon first\n"
    "  - Male-female pairs: then matches remaining Pokémon by egg group\n"
    "  - Use `v!dc <boxname>` to see all pairs in your daycare box\n\n"
    "⚙️ **Naming Settings** - Customize Pokémon prediction behavior\n"
    "  - Use `v!settings` → Naming to access configuration\n"
    "  - Naming: Enable/disable predictions entirely\n"
    "  - Mode: Choose between Assisted (copy-paste) or Embed Mode (code block)\n"
    "  - Only Pings: Filter output to only names with configured pings\n"
    "  - Best Name: Show or hide the fastest normalized catch alias"
)


class AnnouncementCog(Protocol):
    bot_state: dict[str, object]

    def save_bot_state(self) -> None: ...


class AnnouncementBot(Protocol):
    def get_channel(self, channel_id: int) -> object | None: ...

    async def fetch_channel(self, channel_id: int) -> object: ...


async def post_update_announcement(bot: AnnouncementBot, cog: AnnouncementCog) -> bool:
    """Post and publish the update once, retrying any pending publication."""
    digest = hashlib.sha256(UPDATE_ANNOUNCEMENT.encode("utf-8")).hexdigest()
    pending = cog.bot_state.get(PENDING_PUBLICATION_KEY)
    if cog.bot_state.get(ANNOUNCEMENT_STATE_KEY) == digest and pending is None:
        return False

    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not isinstance(channel, discord.abc.Messageable):
        raise TypeError(
            f"Announcement channel {ANNOUNCEMENT_CHANNEL_ID} cannot receive messages"
        )

    async def publish_pending(message: discord.Message) -> None:
        if not message.flags.crossposted:
            await message.publish()
        pending_id = cog.bot_state.pop(PENDING_PUBLICATION_KEY)
        try:
            cog.save_bot_state()
        except OSError:
            cog.bot_state[PENDING_PUBLICATION_KEY] = pending_id
            raise

    if pending is not None:
        if not isinstance(pending, int):
            raise ValueError("Invalid pending update announcement message ID")
        await publish_pending(await channel.fetch_message(pending))
        if cog.bot_state.get(ANNOUNCEMENT_STATE_KEY) == digest:
            return False

    message = await channel.send(
        f"<@&{ANNOUNCEMENT_ROLE_ID}> {UPDATE_ANNOUNCEMENT}",
        allowed_mentions=discord.AllowedMentions(
            roles=[discord.Object(id=ANNOUNCEMENT_ROLE_ID)],
            users=False,
            everyone=False,
        ),
    )
    had_previous_digest = ANNOUNCEMENT_STATE_KEY in cog.bot_state
    previous_digest = cog.bot_state.get(ANNOUNCEMENT_STATE_KEY)
    cog.bot_state[ANNOUNCEMENT_STATE_KEY] = digest
    cog.bot_state[PENDING_PUBLICATION_KEY] = message.id
    try:
        cog.save_bot_state()
    except OSError:
        cog.bot_state.pop(PENDING_PUBLICATION_KEY)
        if had_previous_digest:
            cog.bot_state[ANNOUNCEMENT_STATE_KEY] = previous_digest
        else:
            cog.bot_state.pop(ANNOUNCEMENT_STATE_KEY)
        raise
    await publish_pending(message)
    return True
