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
    "🔧 **Daycare Pairing Fix** - Output now handles large pair lists\n"
    "  - Breeding pairs now split into multiple messages when there are many pairs\n"
    "  - Prevents Discord message length errors\n"
    "  - Use `v!dc <boxname>` to see all pairs in your daycare box"
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
    stored_digest = cog.bot_state.get(ANNOUNCEMENT_STATE_KEY)
    
    print(f"DEBUG: Announcement check - Current digest: {digest[:8]}..., Stored: {str(stored_digest)[:8]}..., Pending: {pending}")
    
    if stored_digest == digest and pending is None:
        print(f"DEBUG: Announcement already posted (digest matches)")
        return False
    
    print(f"DEBUG: Posting announcement (digest changed or pending publication)")

    try:
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
            print(f"DEBUG: Publishing pending message {pending}")
            if not isinstance(pending, int):
                raise ValueError("Invalid pending update announcement message ID")
            await publish_pending(await channel.fetch_message(pending))
            if cog.bot_state.get(ANNOUNCEMENT_STATE_KEY) == digest:
                print(f"DEBUG: Announcement already posted after publishing pending")
                return False

        print(f"DEBUG: Sending new announcement message")
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
            print(f"DEBUG: Announcement saved (message {message.id})")
        except OSError:
            cog.bot_state.pop(PENDING_PUBLICATION_KEY)
            raise
        return True
    except Exception as e:
        print(f"❌ Error posting announcement: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
        if had_previous_digest:
            cog.bot_state[ANNOUNCEMENT_STATE_KEY] = previous_digest
        else:
            cog.bot_state.pop(ANNOUNCEMENT_STATE_KEY)
        raise
    await publish_pending(message)
    return True
