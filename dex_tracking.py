"""Import missing Pokédex entries and manage their spawn-ping queue."""
import asyncio
from dataclasses import dataclass, field
import re
from time import monotonic

import discord

from breeding_boxes import APPEND_SESSION_SECONDS, component_text
from starboard import parse_catch


@dataclass
class DexSession:
    seen: set[int]
    expires_at: float
    status_message: discord.Message | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def dex_entries(message) -> list[dict]:
    """Read missing entries in Discord's field/component order."""
    sections = []
    for embed in message.embeds:
        sections.append("\n".join(filter(None, (embed.title, embed.description))))
        sections.extend(f"{field.name}\n{field.value}" for field in embed.fields)
    sections.extend(component_text(getattr(message, "components", [])))
    sections.insert(0, message.content or "")
    text = "\n".join(sections)
    if not re.search(r"\bpok[eé]dex\b", text, re.IGNORECASE):
        return []
    entries = []
    pattern = (
        r"(?m)^[ \t]*([^\n#]+?)\s*(?:\*\*|__|`)*#\s*(\d+)(?:\*\*|__|`)*\s*"
        r"(?:❌|:x:|<a?:[^:>\s]+:\d+>)?\s*(?:\*\*)?not\s+caught\s+yet"
    )
    for match in re.finditer(pattern, text, re.IGNORECASE):
        name = re.sub(r"<a?:[^:>]+:\d+>", "", match.group(1))
        name = name.replace("*", "").replace("`", "").strip()
        name = re.sub(r"^[^\w]+", "", name).strip()
        if name:
            entries.append({"id": int(match.group(2)), "name": name})
    return entries


def dex_ping_owners(cog, guild_id: int, pokemon_name: str) -> list[str]:
    species_id = getattr(cog, "pokemon_species", {}).get(pokemon_name)
    if species_id is None:
        return []
    owners = []
    for user_id, settings in cog.bot_state.get("dex_tracking", {}).get(
        str(guild_id), {}
    ).items():
        if settings.get("paused", False):
            continue
        queue = settings.get("queue", [])
        limit = settings.get("mode", 1)
        active = queue if limit == "all" else queue[:limit]
        if any(item["id"] == species_id for item in active):
            owners.append(user_id)
    return cog.current_guild_member_ids(guild_id, owners)


def remove_caught_dex_entry(cog, message) -> None:
    if message.guild is None:
        return
    users = cog.bot_state.get("dex_tracking", {}).get(str(message.guild.id), {})
    if not users:
        return
    catch = parse_catch(message)
    if catch is None:
        return
    settings = users.get(catch.user_id)
    if not settings:
        return
    name = catch.pokemon
    if name.casefold() == "nidoran" and catch.gender == "♂":
        name = "Nidoran male"
    canonical = cog.resolve_pokemon_name(name)
    species_id = cog.pokemon_species.get(canonical)
    if species_id is None:
        return
    service = getattr(cog, "dex_tracking_service", None)
    if service is not None:
        service.mark_caught(message.guild.id, int(catch.user_id), species_id)
    queue = settings.get("queue", [])
    remaining = [entry for entry in queue if entry["id"] != species_id]
    if len(remaining) != len(queue):
        settings["queue"] = remaining
        cog.save_bot_state()


class DexTrackingService:
    def __init__(self, cog, poketwo_id: int):
        self.cog = cog
        self.poketwo_id = poketwo_id
        self.sessions: dict[tuple[int, int, int, int], DexSession] = {}

    def settings(self, guild_id: int, user_id: int) -> dict:
        return self.cog.bot_state.setdefault("dex_tracking", {}).setdefault(
            str(guild_id), {}
        ).setdefault(str(user_id), {"queue": [], "paused": False, "mode": 1})

    def prune(self) -> None:
        now = monotonic()
        for key, session in list(self.sessions.items()):
            if session.expires_at <= now:
                del self.sessions[key]

    def clear(self, guild_id: int, user_id: int) -> int:
        settings = self.settings(guild_id, user_id)
        count = len(settings.get("queue", []))
        settings["queue"] = []
        self.cancel_sessions(guild_id, user_id)
        self.cog.save_bot_state()
        return count

    def cancel_sessions(self, guild_id: int, user_id: int) -> None:
        for key in list(self.sessions):
            if key[0] == guild_id and key[3] == user_id:
                del self.sessions[key]

    def mark_caught(self, guild_id: int, user_id: int, species_id: int) -> None:
        self.prune()
        for key, session in self.sessions.items():
            if key[0] == guild_id and key[3] == user_id:
                session.seen.add(species_id)

    def add_page(self, settings: dict, session: DexSession, entries: list[dict]) -> int:
        queue = settings.setdefault("queue", [])
        existing = {entry["id"] for entry in queue}
        added = 0
        for entry in entries:
            species_id = entry["id"]
            if species_id not in session.seen and species_id not in existing:
                queue.append(entry)
                existing.add(species_id)
                added += 1
            session.seen.add(species_id)
        if added:
            self.cog.save_bot_state()
        return added

    @staticmethod
    def status(added: int, total: int) -> str:
        return (
            f"✅ Added **{added}** missing Pokémon. Dex queue: **{total}**.\n"
            "Added Pokémon stay in your queue, even after a restart, until you "
            "catch them or clear it in `v!dexhelp`.\n"
            "Use the Pokétwo page arrows to add more. Only page tracking stops "
            "30 minutes after the last page change or when the bot restarts."
        )

    async def append(self, ctx) -> None:
        if ctx.guild is None:
            await ctx.send("❌ Dex tracking can only be used inside a server.")
            return
        reference = ctx.message.reference
        if reference is None or reference.message_id is None:
            await ctx.send("❌ Reply to your Pokétwo Pokédex with `v!dex append`.")
            return
        try:
            source = await ctx.channel.fetch_message(reference.message_id)
        except discord.HTTPException as error:
            await ctx.send(f"❌ Could not fetch the Pokédex message: {error}")
            return
        if source.author.id != self.poketwo_id:
            await ctx.send("❌ Reply to a Pokédex sent by Pokétwo.")
            return
        entries = dex_entries(source)
        if not entries:
            await ctx.send("❌ No missing Pokédex entries were recognized on this page.")
            return
        self.prune()
        key = (ctx.guild.id, ctx.channel.id, source.id, ctx.author.id)
        session = DexSession(set(), monotonic() + APPEND_SESSION_SECONDS)
        self.sessions[key] = session
        settings = self.settings(ctx.guild.id, ctx.author.id)
        async with session.lock:
            added = self.add_page(settings, session, entries)
            try:
                session.status_message = await ctx.send(
                    self.status(added, len(settings["queue"]))
                )
            except discord.HTTPException:
                self.sessions.pop(key, None)
                raise

    async def handle_list_edit(self, message) -> None:
        if message.guild is None:
            return
        self.prune()
        matching = [
            (key, session) for key, session in self.sessions.items()
            if key[:3] == (message.guild.id, message.channel.id, message.id)
        ]
        if not matching:
            return
        entries = dex_entries(message)
        for key, session in matching:
            async with session.lock:
                if self.sessions.get(key) is not session:
                    continue
                session.expires_at = monotonic() + APPEND_SESSION_SECONDS
                settings = self.settings(key[0], key[3])
                if entries:
                    added = self.add_page(settings, session, entries)
                    status = self.status(added, len(settings["queue"]))
                else:
                    status = "⚠️ No missing Pokédex entries were recognized on this page."
                if session.status_message is not None:
                    try:
                        await session.status_message.edit(content=status)
                    except discord.HTTPException as error:
                        print(f"Could not update dex import status: {error}")
                        await message.channel.send(status)


class DexSettingsView(discord.ui.View):
    def __init__(self, service: DexTrackingService, guild_id: int, user_id: int):
        super().__init__(timeout=300)
        self.service = service
        self.guild_id = guild_id
        self.user_id = user_id
        self.refresh()

    def embed(self) -> discord.Embed:
        settings = self.service.settings(self.guild_id, self.user_id)
        queue = settings.get("queue", [])
        mode = settings.get("mode", 1)
        active = queue if mode == "all" else queue[:mode]
        names = ", ".join(item["name"] for item in active[:20]) or "None"
        if len(active) > 20:
            names += f" and {len(active) - 20} more"
        return discord.Embed(
            title="Pokédex tracking settings",
            description=(
                "Reply to your Pokétwo Pokédex with `v!dex append`, then use its "
                "arrows to import more pages. Caught species are removed automatically.\n\n"
                f"**Pings:** {'Paused' if settings.get('paused') else 'On'}\n"
                f"**Targets:** {mode}\n"
                f"**Remaining:** {len(queue)}\n"
                f"**Active:** {names}\n\n"
                "Dex tracking is separate from your `v!cl` collection."
            ),
            color=discord.Color.blurple(),
        )

    def refresh(self) -> None:
        settings = self.service.settings(self.guild_id, self.user_id)
        self.pause.label = "Resume pings" if settings.get("paused") else "Pause pings"
        self.mode.label = f"Targets: {settings.get('mode', 1)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only the person who opened these settings can use them.", ephemeral=True
        )
        return False

    async def update(self, interaction: discord.Interaction) -> None:
        self.service.cog.save_bot_state()
        self.refresh()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Pause pings", style=discord.ButtonStyle.primary)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.service.settings(self.guild_id, self.user_id)
        settings["paused"] = not settings.get("paused", False)
        await self.update(interaction)

    @discord.ui.button(label="Targets: 1", style=discord.ButtonStyle.secondary)
    async def mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = self.service.settings(self.guild_id, self.user_id)
        settings["mode"] = {1: 2, 2: "all", "all": 1}[settings.get("mode", 1)]
        await self.update(interaction)

    @discord.ui.button(label="Clear dex queue", style=discord.ButtonStyle.danger)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.service.clear(self.guild_id, self.user_id)
        self.refresh()
        await interaction.response.edit_message(embed=self.embed(), view=self)
