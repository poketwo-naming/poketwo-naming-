"""Breeding box and daycare commands."""
from collections.abc import Sequence
from dataclasses import dataclass, field
import asyncio
import random
import re
import shlex
from time import monotonic

import aiohttp
import discord


BREEDING_BOX_LIMIT = 7_500
POKETWO_DAYCARE_COMMAND = "@Pokétwo#8236 daycare"
APPEND_SESSION_SECONDS = 30 * 60


@dataclass
class AppendSession:
    box: dict
    status_message: discord.Message | None
    expires_at: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _gender_from_line(line: str) -> str | None:
    male = "♂" in line or re.search(r"(?<!\w)male(?!\w)", line, re.I)
    female = "♀" in line or re.search(r"(?<!\w)female(?!\w)", line, re.I)
    if bool(male) == bool(female):
        return None
    return "male" if male else "female"


def _is_breedable_species(data: dict) -> bool:
    egg_groups = data.get("egg_groups", ())
    return bool(egg_groups) and "undiscovered" not in egg_groups


def component_text(components: Sequence[discord.components.Component]) -> list[str]:
    """Extract text displays from nested Discord message components."""
    texts = []
    for component in components:
        if isinstance(component, discord.components.TextDisplay):
            texts.append(component.content)
        elif isinstance(
            component,
            (discord.components.Container, discord.components.SectionComponent),
        ):
            texts.extend(component_text(component.children))
    return texts


def find_daycare_pairs(
    items: list[dict],
    species_data: dict[int, dict],
    selection: str = "first",
) -> list[tuple[int, int]]:
    """Find up to two compatible, non-repeating Pokémon pairs."""
    ditto_indices = []
    males: dict[str, list[int]] = {}
    females: dict[str, list[int]] = {}

    for index, item in enumerate(items):
        species_id = item.get("species_id")
        if species_id is None:
            continue
        data = species_data.get(species_id)
        if not data or not _is_breedable_species(data):
            continue
        egg_groups = data.get("egg_groups", ())
        if "ditto" in egg_groups:
            ditto_indices.append(index)
            continue
        gender_rate = data.get("gender_rate", -1)
        if gender_rate == -1:
            continue
        gender = item.get("gender")
        if gender_rate == 0:
            gender = "male"
        elif gender_rate == 8:
            gender = "female"
        if gender not in {"male", "female"}:
            continue
        groups = males if gender == "male" else females
        for egg_group in egg_groups:
            groups.setdefault(egg_group, []).append(index)

    if selection == "random":
        random.shuffle(ditto_indices)
        for group_indices in (*males.values(), *females.values()):
            random.shuffle(group_indices)
    elif selection == "tagged":
        ditto_indices.sort(key=lambda index: not items[index].get("tags"))
        for group_indices in (*males.values(), *females.values()):
            group_indices.sort(key=lambda index: not items[index].get("tags"))

    pairs = []
    used = set()
    for group in dict.fromkeys(
        [*males.keys(), *females.keys()]
    ):
        for male_index in males.get(group, ()):
            for female_index in females.get(group, ()):
                if male_index == female_index or male_index in used or female_index in used:
                    continue
                pairs.append((male_index, female_index))
                used.update((male_index, female_index))
                if len(pairs) == 2:
                    return pairs

    eligible = []
    for index, item in enumerate(items):
        species_id = item.get("species_id")
        if species_id is None:
            continue
        data = species_data.get(species_id)
        if (
            data
            and _is_breedable_species(data)
            and "ditto" not in data.get("egg_groups", ())
            and data.get("gender_rate") != -1
            and (
                item.get("gender") in {"male", "female"}
                or data.get("gender_rate") in {0, 8}
            )
        ):
            eligible.append(index)
    for ditto_index in ditto_indices:
        for other_index in eligible:
            if ditto_index == other_index or other_index in used:
                continue
            pairs.append((ditto_index, other_index))
            used.update((ditto_index, other_index))
            if len(pairs) == 2:
                return pairs
    return pairs


class BreedingBoxPagesView(discord.ui.View):
    """Navigate the contents of a breeding box."""

    def __init__(self, author_id: int, pages: list[discord.Embed]):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.pages = pages
        self.page = 0
        self.update_buttons()

    def update_buttons(self):
        self.previous_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Only the person who opened this list can change pages.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction, button):
        del button
        self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.page],
            view=self,
        )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction, button):
        del button
        self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.page],
            view=self,
        )


class ResetBreedingBoxesView(discord.ui.View):
    """Require confirmation before resetting all of a member's boxes."""

    def __init__(self, service, guild_id: int, user_id: int):
        super().__init__(timeout=120)
        self.service = service
        self.guild_id = guild_id
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only the person who requested this reset can confirm it.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Reset boxes", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        del button
        boxes = self.service.user_boxes(self.guild_id, self.user_id)
        count = len(boxes)
        boxes.clear()
        self.service.cog.save_bot_state()
        await interaction.response.edit_message(
            content=f"✅ Reset {count} breeding box(es).",
            embed=None,
            view=None,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        del button
        await interaction.response.edit_message(
            content="Breeding box reset cancelled.",
            embed=None,
            view=None,
        )


class DaycareSettingsView(discord.ui.View):
    """Update how daycare pairs are selected and displayed."""

    def __init__(self, service, guild_id: int, user_id: int):
        super().__init__(timeout=180)
        self.service = service
        self.guild_id = guild_id
        self.user_id = user_id

    def settings(self) -> dict:
        return self.service.daycare_settings(self.guild_id, self.user_id)

    def embed(self) -> discord.Embed:
        settings = self.settings()
        return discord.Embed(
            title="Daycare Settings",
            description=(
                f"Pair selection: **{settings['selection']}**\n"
                f"Display: **{settings['display']}**"
            ),
            color=discord.Color.green(),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only the person who opened these settings can change them.",
            ephemeral=True,
        )
        return False

    async def update_setting(self, interaction, key: str, value: str):
        self.settings()[key] = value
        self.service.cog.save_bot_state()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="First available", style=discord.ButtonStyle.primary)
    async def first(self, interaction, button):
        del button
        await self.update_setting(interaction, "selection", "first")

    @discord.ui.button(label="Random pairs", style=discord.ButtonStyle.primary)
    async def random_pairs(self, interaction, button):
        del button
        await self.update_setting(interaction, "selection", "random")

    @discord.ui.button(label="Tagged first", style=discord.ButtonStyle.primary)
    async def tagged_first(self, interaction, button):
        del button
        await self.update_setting(interaction, "selection", "tagged")

    @discord.ui.button(label="Commands", style=discord.ButtonStyle.secondary)
    async def commands(self, interaction, button):
        del button
        await self.update_setting(interaction, "display", "commands")

    @discord.ui.button(label="Details", style=discord.ButtonStyle.secondary)
    async def details(self, interaction, button):
        del button
        await self.update_setting(interaction, "display", "details")


class BreedingBoxService:
    """Implement the public v!box and v!dc command surfaces."""

    def __init__(self, cog, poketwo_bot_id: int):
        self.cog = cog
        self.poketwo_bot_id = poketwo_bot_id
        self.species_cache: dict[int, dict] = {}
        self.append_sessions: dict[tuple[int, int, int, int], AppendSession] = {}

    def user_boxes(self, guild_id: int, user_id: int) -> dict:
        return self.cog.bot_state.setdefault("breeding_boxes", {}).setdefault(
            str(guild_id), {}
        ).setdefault(str(user_id), {})

    def daycare_settings(self, guild_id: int, user_id: int) -> dict:
        settings = self.cog.bot_state.setdefault(
            "daycare_settings",
            {},
        ).setdefault(f"{guild_id}:{user_id}", {})
        settings.setdefault("selection", "first")
        settings.setdefault("display", "commands")
        return settings

    def resolve_box(
        self,
        boxes: dict,
        selector: str,
    ) -> tuple[str | None, dict | None]:
        if selector.isdigit():
            names = list(boxes)
            index = int(selector) - 1
            if 0 <= index < len(names):
                name = names[index]
                return name, boxes[name]
        name = next(
            (name for name in boxes if name.casefold() == selector.casefold()),
            None,
        )
        return (name, boxes[name]) if name is not None else (None, None)

    @staticmethod
    def item_count(box: dict) -> int:
        items = box.get("items", [])
        return len(items) if isinstance(items, list) else 0

    async def dispatch(self, ctx, command: str, entry: str = ""):
        if ctx.guild is None:
            await ctx.send("Breeding boxes and daycare can only be used in a server.")
            return
        if command == "boxhelp":
            await self.show_help(ctx)
        elif command == "dc":
            await self.daycare_command(ctx, entry)
        else:
            await self.box_command(ctx, entry)

    async def show_help(self, ctx):
        await ctx.send(
            embed=discord.Embed(
                title="Breeding Boxes & Daycare",
                description=(
                    "`v!box` — show your boxes and their capacity\n"
                    "`v!box create <name>` — make a box\n"
                    "Reply to a Pokétwo list with `v!box append [box] [--c]` "
                    "to store numbered Pokémon; page arrows keep adding for "
                    "30 minutes. `--c` clears first.\n"
                    "`v!box list [box]` — browse boxes or their contents\n"
                    "`v!box remove <box> <number|Pokémon> [all]` — delete stored Pokémon\n"
                    "`v!box transfer <from> <to> [number|Pokémon] [all]` — move Pokémon\n"
                    "`v!box copy <source> <new name>` — duplicate a box; use an "
                    "existing destination to copy entries\n"
                    "`v!box tag <box> <number|Pokémon> <tag>` / "
                    "`v!box untag <box> <number|Pokémon> [tag]`\n"
                    "`v!box tags [box]` / `v!box tagged <tag>`\n"
                    "`v!box rename <box> <new name>` / `v!box delete <box>`\n"
                    "`v!box clear <box>` — empty one box\n"
                    "`v!box reset` — confirm before removing all your boxes\n"
                    "`v!dc [box]` — get one compatible pair using Pokémon numbers\n"
                    "`v!dc settings` — choose first, random, or tagged-first pairs "
                    "and display\n"
                    "`v!boxhelp` — show this command list"
                ),
                color=discord.Color.green(),
            )
        )

    async def box_command(self, ctx, entry: str):
        text = entry.strip()
        try:
            parts = shlex.split(text)
        except ValueError as error:
            await ctx.send(f"❌ Invalid command syntax: {error}")
            return
        action = parts[0].casefold() if parts else ""
        arguments = parts[1:]
        boxes = self.user_boxes(ctx.guild.id, ctx.author.id)

        if action in {"", "list"} and not arguments:
            await self.show_boxes(ctx, boxes)
            return
        if action == "create":
            await self.create_box(ctx, boxes, " ".join(arguments))
            return
        if action == "append":
            await self.append_box(ctx, boxes, arguments)
            return
        if action == "list":
            await self.list_box(ctx, boxes, " ".join(arguments))
            return
        if action in {"remove", "transfer", "copy", "tag", "untag", "rename", "delete", "clear"}:
            await self.manage_box(ctx, boxes, action, arguments)
            return
        if action == "tags":
            await self.show_tags(ctx, boxes, " ".join(arguments))
            return
        if action == "tagged":
            await self.show_tagged(ctx, boxes, " ".join(arguments))
            return
        if action == "reset" and not arguments:
            if not boxes:
                await ctx.send("You have no breeding boxes to reset.")
                return
            await ctx.send(
                f"⚠️ Reset all **{len(boxes)}** of your breeding boxes?",
                view=ResetBreedingBoxesView(self, ctx.guild.id, ctx.author.id),
            )
            return
        if action:
            await ctx.send(
                f"Unknown box command `{action}`. Use `v!boxhelp`."
            )
            return
        await self.show_boxes(ctx, boxes)

    async def show_boxes(self, ctx, boxes: dict):
        if not boxes:
            await ctx.send("You have no boxes. Create one with `v!box create <name>`.")
            return
        lines = [
            f"{index}. **{name}** — {self.item_count(box)}/{BREEDING_BOX_LIMIT}"
            for index, (name, box) in enumerate(boxes.items(), start=1)
        ]
        await ctx.send(
            embed=discord.Embed(
                title=f"{ctx.author.display_name}'s Breeding Boxes",
                description="\n".join(lines),
                color=discord.Color.green(),
            )
        )

    async def create_box(self, ctx, boxes: dict, name: str):
        name = name.strip()[:100]
        if not name:
            await ctx.send("Usage: `v!box create <name>`")
            return
        if any(existing.casefold() == name.casefold() for existing in boxes):
            await ctx.send(f"❌ A box named **{name}** already exists.")
            return
        boxes[name] = {"items": []}
        self.cog.save_bot_state()
        await ctx.send(f"✅ Created box **{name}**.")

    async def replied_message(self, ctx):
        reference = ctx.message.reference
        if reference is None or reference.message_id is None:
            return None
        try:
            return await ctx.channel.fetch_message(reference.message_id)
        except discord.HTTPException as error:
            print(f"Could not fetch the replied-to Pokémon list: {error}")
            return None

    async def read_pokemon(self, message) -> list[dict]:
        names = sorted(
            self.cog.report_pokemon_names(),
            key=len,
            reverse=True,
        )
        text = "\n".join(
            [
                message.content or "",
                *(embed.title or "" for embed in message.embeds),
                *(embed.description or "" for embed in message.embeds),
                *(
                    f"{field.name or ''}\n{field.value or ''}"
                    for embed in message.embeds
                    for field in embed.fields
                ),
                *component_text(getattr(message, "components", [])),
            ]
        )
        found = []
        for line in text.splitlines():
            number_match = re.match(
                r"^\s*(?:[-•]\s*)?`?(\d+)`?(?=\s|[.):]|$)",
                line,
            )
            if number_match is None:
                continue
            for name in names:
                if not re.search(
                    rf"(?<![\w]){re.escape(name)}(?![\w])",
                    line,
                    re.I,
                ):
                    continue
                resolved = self.cog.resolve_pokemon_name(name)
                if resolved:
                    found.append(
                        {
                            "name": resolved,
                            "gender": _gender_from_line(line),
                            "tags": [],
                            "pokemon_id": str(int(number_match.group(1))),
                        }
                    )
                break
        return found

    @staticmethod
    def add_unique_items(box: dict, items: list[dict]) -> tuple[int, int]:
        """Append new Pokétwo numbers, retaining distinct same-species Pokémon."""
        stored = box.setdefault("items", [])
        seen = {
            str(item["pokemon_id"])
            for item in stored
            if item.get("pokemon_id") is not None
        }
        added = 0
        skipped_for_capacity = 0
        for item in items:
            pokemon_id = item["pokemon_id"]
            if pokemon_id in seen:
                continue
            seen.add(pokemon_id)
            if len(stored) >= BREEDING_BOX_LIMIT:
                skipped_for_capacity += 1
                continue
            stored.append(item)
            added += 1
        return added, skipped_for_capacity

    def prune_append_sessions(self):
        now = monotonic()
        for key, session in list(self.append_sessions.items()):
            if session.expires_at <= now:
                del self.append_sessions[key]

    async def handle_list_edit(self, message):
        """Append each edited page of a list that a user chose to follow."""
        if message.guild is None:
            return
        self.prune_append_sessions()
        matching = [
            (key, session)
            for key, session in self.append_sessions.items()
            if key[:3] == (message.guild.id, message.channel.id, message.id)
        ]
        if not matching:
            return
        items = await self.read_pokemon(message)
        for key, session in matching:
            async with session.lock:
                if self.append_sessions.get(key) is not session:
                    continue
                boxes = self.cog.bot_state.get("breeding_boxes", {}).get(
                    str(key[0]), {}
                ).get(str(key[3]), {})
                box_name = next(
                    (name for name, box in boxes.items() if box is session.box),
                    None,
                )
                if box_name is None:
                    self.append_sessions.pop(key, None)
                    continue
                session.expires_at = monotonic() + APPEND_SESSION_SECONDS
                if items:
                    added, overflow = self.add_unique_items(session.box, items)
                    if added:
                        self.cog.save_bot_state()
                    status = self.append_status(box_name, session.box, added, overflow)
                else:
                    status = (
                        f"⚠️ No numbered Pokémon were recognized on this page. "
                        f"Box **{box_name}** still has "
                        f"**{self.item_count(session.box)}/{BREEDING_BOX_LIMIT}**."
                    )
                if session.status_message is None:
                    continue
                try:
                    await session.status_message.edit(content=status)
                except discord.HTTPException as error:
                    print(f"Could not update breeding box import status: {error}")
                    try:
                        await message.channel.send(status)
                    except discord.HTTPException as send_error:
                        print(f"Could not send breeding box import status: {send_error}")

    def append_status(self, box_name: str, box: dict, added: int, overflow: int) -> str:
        status = (
            f"✅ Added **{added}** Pokémon to **{box_name}**. "
            f"Box total: **{self.item_count(box)}/{BREEDING_BOX_LIMIT}**.\n"
            "Use the Pokétwo page arrows to add more; duplicates are skipped. "
            "Tracking lasts 30 minutes after the last page change or until restart."
        )
        if overflow:
            status += f"\n⚠️ Box full; {overflow} Pokémon could not be added."
        if any(item.get("pokemon_id") is None for item in box.get("items", [])):
            status += (
                "\n⚠️ Older entries have no Pokétwo number and cannot be deduplicated. "
                "Clear and re-import the box to remove old duplicates."
            )
        return status

    async def append_box(self, ctx, boxes: dict, arguments: list[str]):
        copy_then_clear = bool(arguments and arguments[-1].casefold() == "--c")
        selectors = arguments[:-1] if copy_then_clear else arguments
        source = await self.replied_message(ctx)
        if source is None:
            await ctx.send(
                "❌ Reply to an accessible Pokétwo list with "
                "`v!box append [box] [--c]`."
            )
            return
        if source.author.id != self.poketwo_bot_id:
            await ctx.send("❌ Reply to a Pokémon list sent by Pokétwo.")
            return
        create_default_box = False
        if selectors:
            selector = " ".join(selectors)
            box_name, box = self.resolve_box(boxes, selector)
            if box is None:
                await ctx.send(f"❌ Box `{selector}` was not found.")
                return
            if box_name is None:
                await ctx.send("❌ Box lookup failed.")
                return
        elif len(boxes) == 1:
            box_name, box = next(iter(boxes.items()))
        elif not boxes:
            box_name = "Box 1"
            box = {"items": []}
            create_default_box = True
        else:
            await ctx.send("Choose a box: `v!box append <box> [--c]`.")
            return

        items = await self.read_pokemon(source)
        if not items:
            await ctx.send(
                "❌ No numbered Pokémon were recognized in the current list page."
            )
            return
        if copy_then_clear:
            box["items"] = []
        if create_default_box:
            boxes[box_name] = box
        added, overflow = self.add_unique_items(box, items)
        if added or copy_then_clear:
            self.cog.save_bot_state()
        self.prune_append_sessions()
        key = (ctx.guild.id, ctx.channel.id, source.id, ctx.author.id)
        session = AppendSession(box, None, monotonic() + APPEND_SESSION_SECONDS)
        self.append_sessions[key] = session
        async with session.lock:
            try:
                session.status_message = await ctx.send(
                    self.append_status(box_name, box, added, overflow)
                )
            except discord.HTTPException:
                self.append_sessions.pop(key, None)
                raise

    async def list_box(self, ctx, boxes: dict, selector: str):
        if not selector:
            await self.show_boxes(ctx, boxes)
            return
        box_name, box = self.resolve_box(boxes, selector)
        if box is None:
            await ctx.send(f"❌ Box `{selector}` was not found.")
            return
        if box_name is None:
            await ctx.send("❌ Box lookup failed.")
            return
        items = box.get("items", [])
        if not items:
            await ctx.send(f"Box **{box_name}** is empty.")
            return
        pages = []
        for start in range(0, len(items), 25):
            lines = []
            for index, item in enumerate(items[start : start + 25], start=start + 1):
                name = item.get("name", "Unknown Pokémon")
                gender = {"male": " ♂", "female": " ♀"}.get(item.get("gender"), "")
                tags = item.get("tags", [])
                tag_text = f" — {', '.join(f'`{tag}`' for tag in tags)}" if tags else ""
                lines.append(f"`{index}.` **{name}**{gender}{tag_text}")
            pages.append(
                discord.Embed(
                    title=f"{box_name} ({len(items)}/{BREEDING_BOX_LIMIT})",
                    description="\n".join(lines),
                    color=discord.Color.green(),
                ).set_footer(
                    text=(
                        f"{start + 1}-{min(start + 25, len(items))} "
                        f"of {len(items)} Pokémon"
                    )
                )
            )
        await ctx.send(
            embed=pages[0],
            view=BreedingBoxPagesView(ctx.author.id, pages),
        )

    async def manage_box(self, ctx, boxes: dict, action: str, args: list[str]):
        if action in {"transfer", "copy"}:
            await self.move_or_copy(ctx, boxes, action, args)
            return
        if action in {"rename", "delete", "clear"}:
            await self.manage_box_itself(ctx, boxes, action, args)
            return
        if not args:
            await ctx.send(f"Usage: `v!box {action} <box> <number|Pokémon>`")
            return
        box_name, box = self.resolve_box(boxes, args[0])
        if box is None:
            await ctx.send(f"❌ Box `{args[0]}` was not found.")
            return
        if box_name is None:
            await ctx.send("❌ Box lookup failed.")
            return
        if len(args) < 2:
            await ctx.send(f"Usage: `v!box {action} <box> <number|Pokémon>`")
            return
        selector = args[1]
        all_matches = args[-1].casefold() == "all" and len(args) > 2
        tag = " ".join(args[2:-1] if all_matches else args[2:])
        if action in {"tag", "untag"}:
            if action == "tag" and not tag:
                await ctx.send("Usage: `v!box tag <box> <number|Pokémon> <tag>`")
                return
            if not self.update_item_tags(box, selector, action, tag):
                await ctx.send(f"❌ `{selector}` was not found in **{box_name}**.")
                return
            await ctx.send("✅ Updated stored Pokémon tags.")
            self.cog.save_bot_state()
            return
        if selector.casefold() == "all":
            removed = len(box.get("items", []))
            box["items"] = []
            self.cog.save_bot_state()
            await ctx.send(f"✅ Removed **{removed}** Pokémon from **{box_name}**.")
            return
        indices = self.match_item_indices(box, selector, all_matches)
        if not indices:
            await ctx.send(f"❌ `{selector}` was not found in **{box_name}**.")
            return
        for index in reversed(indices):
            box["items"].pop(index)
        self.cog.save_bot_state()
        await ctx.send(
            f"✅ Removed **{len(indices)}** Pokémon entry/entries from **{box_name}**."
        )

    @staticmethod
    def match_item_indices(box: dict, selector: str, all_matches: bool) -> list[int]:
        items = box.get("items", [])
        if selector.isdigit():
            index = int(selector) - 1
            return [index] if 0 <= index < len(items) else []
        matches = [
            index
            for index, item in enumerate(items)
            if str(item.get("name", "")).casefold() == selector.casefold()
        ]
        return matches if all_matches else matches[:1]

    def update_item_tags(
        self,
        box: dict,
        selector: str,
        action: str,
        tag: str,
    ) -> bool:
        indices = self.match_item_indices(box, selector, all_matches=False)
        if not indices:
            return False
        item = box["items"][indices[0]]
        tags = {str(value) for value in item.get("tags", [])}
        if action == "tag":
            tags.add(tag)
        elif tag:
            tags = {value for value in tags if value.casefold() != tag.casefold()}
        else:
            tags.clear()
        item["tags"] = sorted(tags, key=str.casefold)
        return True

    async def manage_box_itself(
        self,
        ctx,
        boxes: dict,
        action: str,
        args: list[str],
    ):
        if not args:
            await ctx.send(f"Usage: `v!box {action} <box>`")
            return
        box_name, box = self.resolve_box(boxes, args[0])
        if box is None:
            await ctx.send(f"❌ Box `{args[0]}` was not found.")
            return
        if box_name is None:
            await ctx.send("❌ Box lookup failed.")
            return
        if action == "rename":
            new_name = " ".join(args[1:]).strip()[:100]
            if not new_name:
                await ctx.send("Usage: `v!box rename <box> <new name>`")
                return
            if any(
                name.casefold() == new_name.casefold() and name != box_name
                for name in boxes
            ):
                await ctx.send(f"❌ Box **{new_name}** already exists.")
                return
            boxes[new_name] = boxes.pop(box_name)
            self.cog.save_bot_state()
            await ctx.send(f"✅ Renamed **{box_name}** to **{new_name}**.")
        elif action == "delete":
            boxes.pop(box_name)
            self.cog.save_bot_state()
            await ctx.send(f"✅ Deleted box **{box_name}**.")
        else:
            box["items"] = []
            self.cog.save_bot_state()
            await ctx.send(f"✅ Cleared **{box_name}**.")

    async def move_or_copy(self, ctx, boxes: dict, action: str, args: list[str]):
        if len(args) < 2:
            await ctx.send(f"Usage: `v!box {action} <source> <destination>`")
            return
        source_name, source = self.resolve_box(boxes, args[0])
        if source is None:
            await ctx.send(f"❌ Box `{args[0]}` was not found.")
            return
        if source_name is None:
            await ctx.send("❌ Source box lookup failed.")
            return
        destination_name, destination = self.resolve_box(boxes, args[1])
        if destination is None and action == "copy":
            destination_name = " ".join(args[1:])[:100]
            if any(name.casefold() == destination_name.casefold() for name in boxes):
                await ctx.send(f"❌ Box **{destination_name}** already exists.")
                return
            boxes[destination_name] = {
                **source,
                "items": [dict(item) for item in source.get("items", [])],
            }
            self.cog.save_bot_state()
            await ctx.send(
                f"✅ Copied **{source_name}** to **{destination_name}**."
            )
            return
        if destination is None:
            await ctx.send(f"❌ Destination box `{args[1]}` was not found.")
            return
        if destination_name is None:
            await ctx.send("❌ Destination box lookup failed.")
            return
        if source_name == destination_name:
            await ctx.send("❌ Choose two different boxes.")
            return
        if len(args) == 2:
            selections = list(range(len(source.get("items", []))))
        else:
            selector = args[2]
            move_all = len(args) > 3 and args[3].casefold() == "all"
            selections = self.match_item_indices(source, selector, move_all)
        if not selections:
            await ctx.send("❌ No matching Pokémon were found in the source box.")
            return
        if self.item_count(destination) + len(selections) > BREEDING_BOX_LIMIT:
            await ctx.send(f"❌ Box **{destination_name}** would exceed its limit.")
            return
        selected_items = [source["items"][index] for index in selections]
        destination.setdefault("items", []).extend(
            dict(item) for item in selected_items
        )
        if action == "transfer":
            for index in reversed(selections):
                source["items"].pop(index)
        self.cog.save_bot_state()
        verb = "Transferred" if action == "transfer" else "Copied"
        await ctx.send(
            f"✅ {verb} **{len(selected_items)}** Pokémon from **{source_name}** "
            f"to **{destination_name}**."
        )

    async def show_tags(self, ctx, boxes: dict, selector: str):
        selected_boxes = boxes
        if selector:
            name, box = self.resolve_box(boxes, selector)
            if box is None:
                await ctx.send(f"❌ Box `{selector}` was not found.")
                return
            if name is None:
                await ctx.send("❌ Box lookup failed.")
                return
            selected_boxes = {name: box}
        tags = sorted(
            {
                str(tag)
                for box in selected_boxes.values()
                for item in box.get("items", [])
                for tag in item.get("tags", [])
            },
            key=str.casefold,
        )
        await ctx.send(
            "No tags yet."
            if not tags
            else "Tags: " + ", ".join(f"`{tag}`" for tag in tags)
        )

    async def show_tagged(self, ctx, boxes: dict, tag: str):
        if not tag:
            await ctx.send("Usage: `v!box tagged <tag>`")
            return
        matches = [
            f"**{item.get('name', 'Unknown Pokémon')}** — {box_name}"
            for box_name, box in boxes.items()
            for item in box.get("items", [])
            if any(
                str(value).casefold() == tag.casefold()
                for value in item.get("tags", [])
            )
        ]
        await ctx.send(
            "\n".join(matches) if matches else f"No Pokémon are tagged `{tag}`."
        )

    async def species_breeding_data(self, species_id: int) -> dict:
        if species_id in self.species_cache:
            return self.species_cache[species_id]
        session = self.cog.http_session
        if session is None:
            raise RuntimeError("Daycare data HTTP session is not initialized.")
        url = f"https://pokeapi.co/api/v2/pokemon-species/{species_id}/"
        async with session.get(url) as response:
            response.raise_for_status()
            payload = await response.json()
        data = {
            "gender_rate": payload["gender_rate"],
            "egg_groups": tuple(
                group["name"] for group in payload["egg_groups"]
            ),
        }
        self.species_cache[species_id] = data
        return data

    async def daycare_command(self, ctx, entry: str):
        try:
            args = shlex.split(entry)
        except ValueError as error:
            await ctx.send(f"❌ Invalid command syntax: {error}")
            return
        if args and args[0].casefold() == "settings":
            if len(args) != 1:
                await ctx.send("Use `v!dc settings` to open daycare settings.")
                return
            view = DaycareSettingsView(self, ctx.guild.id, ctx.author.id)
            await ctx.send(embed=view.embed(), view=view)
            return

        boxes = self.user_boxes(ctx.guild.id, ctx.author.id)
        if args:
            box_name, box = self.resolve_box(boxes, " ".join(args))
        elif boxes:
            box_name, box = next(iter(boxes.items()))
        else:
            box_name, box = None, None
        if box is None:
            await ctx.send(
                "Choose a box with `v!dc <box>`, or create one with "
                "`v!box create <name>`."
            )
            return
        if box_name is None:
            await ctx.send("❌ Box lookup failed.")
            return
        items = box.get("items", [])
        candidates = []
        seen_ids = set()
        for index, item in enumerate(items):
            pokemon_id = item.get("pokemon_id")
            if not isinstance(pokemon_id, str) or not pokemon_id.isdigit():
                continue
            if pokemon_id in seen_ids:
                continue
            seen_ids.add(pokemon_id)
            name = self.cog.resolve_pokemon_name(str(item.get("name", "")))
            species_id = self.cog.pokemon_species.get(name) if name else None
            if species_id is not None:
                candidates.append(
                    {
                        **item,
                        "name": name,
                        "species_id": species_id,
                        "source_index": index,
                    }
                )
        species_ids = {item["species_id"] for item in candidates}
        semaphore = asyncio.Semaphore(8)

        async def fetch_species(species_id: int):
            async with semaphore:
                return species_id, await self.species_breeding_data(species_id)

        try:
            results = await asyncio.gather(
                *(fetch_species(species_id) for species_id in species_ids)
            )
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError) as error:
            print(f"Could not load Pokémon daycare compatibility data: {error}")
            await ctx.send(
                "❌ I couldn't load daycare compatibility data. Please try again."
            )
            return
        species_data = dict(results)
        settings = self.daycare_settings(ctx.guild.id, ctx.author.id)
        pairs = find_daycare_pairs(
            candidates,
            species_data,
            settings["selection"],
        )
        if not pairs:
            await ctx.send(
                f"No compatible numbered pair was found in **{box_name}**. "
                "Append a current Pokétwo list to store Pokémon numbers and "
                "visible genders."
            )
            return
        output = []
        for pair_number, (left, right) in enumerate(pairs[:1], start=1):
            first = candidates[left]
            second = candidates[right]
            daycare_command = (
                f"{POKETWO_DAYCARE_COMMAND} add {first['pokemon_id']} "
                f"{second['pokemon_id']}"
            )
            if settings["display"] == "details":
                genders = (
                    first.get("gender") or "fixed gender",
                    second.get("gender") or "fixed gender",
                )
                tags = [
                    *first.get("tags", []),
                    *second.get("tags", []),
                ]
                tag_text = (
                    f"; tracked egg moves: {', '.join(dict.fromkeys(tags))}"
                    if tags
                    else ""
                )
                output.append(
                    f"**Pair {pair_number}:** {first['name']} ({genders[0]}) + "
                    f"{second['name']} ({genders[1]}){tag_text}\n"
                    f"`{daycare_command}`"
                )
            else:
                output.append(f"`{daycare_command}`")
        await ctx.send(
            embed=discord.Embed(
                title=f"Daycare Pairs — {box_name}",
                description="\n".join(output),
                color=discord.Color.green(),
            )
        )
