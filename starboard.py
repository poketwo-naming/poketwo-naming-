"""Per-server catch starboards."""
import asyncio
from dataclasses import dataclass
import logging
import re

import discord


RARE_NAMES = {
    name.casefold() for name in (
        "Articuno, Zapdos, Moltres, Mewtwo, Mew, Raikou, Entei, Suicune, Lugia, "
        "Ho-oh, Celebi, Regirock, Regice, Registeel, Latias, Latios, Kyogre, Groudon, "
        "Rayquaza, Jirachi, Deoxys, Attack Deoxys, Defense Deoxys, Speed Deoxys, "
        "Uxie, Mesprit, Azelf, Dialga, Palkia, Heatran, Regigigas, Giratina, Cresselia, "
        "Phione, Manaphy, Darkrai, Shaymin, Victini, Cobalion, Terrakion, Virizion, "
        "Tornadus, Thundurus, Reshiram, Zekrom, Landorus, Kyurem, Keldeo, Meloetta, "
        "Pirouette Meloetta, Yveltal, Diancie, Hoopa, Volcanion, Type: Null, "
        "Tapu Koko, Tapu Lele, Tapu Bulu, Tapu Fini, Cosmog, Cosmoem, Solgaleo, "
        "Lunala, Nihilego, Buzzwole, Pheromosa, Xurkitree, Celesteela, Kartana, "
        "Guzzlord, Necrozma, Magearna, Marshadow, Poipole, Naganadel, Stakataka, "
        "Blacephalon, Zeraora, Meltan, Kubfu, Zarude, Dada Zarude, Regieleki, "
        "Regidrago, Glastrier, Spectrier, Calyrex, Enamorus, Wo-Chien, Chien-Pao, "
        "Ting-Lu, Chi-yu, Okidogi, Munkidori, Fezandipiti, Terapagos, Pecharunt, "
        "Zacian, Zamazenta, Eternatus, Melmetal, Zenith Marshadow"
    ).split(", ")
}
ALL_FORM_NAMES = {
    "arceus", "genesect", "xerneas", "zygarde", "silvally", "ogerpon",
    "urshifu", "koraidon", "miraidon",
}
REGIONAL_NAMES = {
    name.casefold() for name in (
        "Galarian Articuno, Galarian Moltres, Galarian Zapdos, "
        "Alolan Ninetales, Alolan Vulpix, Alolan Geodude, Alolan Graveler, "
        "Alolan Raticate, Alolan Rattata, Alolan Persian, Alolan Meowth, "
        "Alolan Exeggutor, Alolan Dugtrio, Alolan Diglett, Alolan Grimer, "
        "Alolan Golem, Alolan Sandshrew, Alolan Sandslash, Alolan Marowak, "
        "Alolan Raichu, Alolan Muk, Galarian Linoone, Galarian Yamask, "
        "Galarian Slowpoke, Galarian Slowbro, Galarian Slowking, "
        "Galarian Farfetch'd, Galarian Rapidash, Galarian Ponyta, Galarian Mr. Mime, "
        "Galarian Weezing, Galarian Zigzagoon, Galarian Corsola, Galarian Meowth, "
        "Galarian Darumaka, Galarian Stunfisk, Galarian Darmanitan, "
        "Galarian Zen Darmanitan, Obstagoon, Sirfetch'd, Cursola, Runerigus, "
        "Mr. Rime, Perrserker, Hisuian Growlithe, Hisuian Arcanine, "
        "Hisuian Electrode, Hisuian Voltorb, Hisuian Typhlosion, Hisuian Lilligant, "
        "Hisuian Samurott, Hisuian Sneasel, Hisuian Decidueye, Hisuian Qwilfish, "
        "Hisuian Braviary, Hisuian Avalugg, Hisuian Zoroark, Hisuian Zorua, "
        "Hisuian Sliggoo, Hisuian Goodra, Basculegion, Sneasler, Overqwil, "
        "Paldean Wooper, Combat Breed Tauros, Blaze Breed Tauros, Aqua Breed Tauros"
    ).split(", ")
}
# PokeAPI's Gigantamax form IDs, used by its official-artwork sprite repository.
GMAX_IDS = dict(zip(
    ("venusaur", "charizard", "blastoise", "butterfree", "pikachu", "meowth",
     "machamp", "gengar", "kingler", "lapras", "eevee", "snorlax", "garbodor",
     "melmetal", "rillaboom", "cinderace", "inteleon", "corviknight", "orbeetle",
     "drednaw", "coalossal", "flapple", "appletun", "sandaconda", "toxtricity",
     "centiskorch", "hatterene", "grimmsnarl", "alcremie", "copperajah",
     "duraludon", "urshifu", "rapid strike urshifu", "low key toxtricity"),
    range(10195, 10229),
))


@dataclass(frozen=True)
class Catch:
    user_id: str
    pokemon: str
    level: int
    iv_text: str
    gender: str
    shiny: bool
    gigantamax: bool
    chain: str | None


def parse_catch(message) -> Catch | None:
    text = message.content or ""
    for embed in message.embeds:
        text += "\n" + "\n".join(filter(None, (
            embed.title, embed.description,
            embed.footer.text if embed.footer else None,
        )))
    match = re.search(
        r"Congratulations\s+<@!?(\d+)>!\s*You caught an?\s+Level\s+(\d+)\s+"
        r"(.+?)\s*(?:([♂♀])\s*)?\((?:IV:\s*)?(\d+(?:\.\d+)?)%\)!",
        text, re.IGNORECASE,
    )
    if not match:
        return None
    name = match.group(3).strip(" *")
    chain = re.search(r"\bchain\s*[:#]?\s*([\d,]+)", text, re.IGNORECASE)
    if chain is None:
        chain = re.search(
            r"(?:shiny streak reset|shiny chain)[.!]?\s*\(\*\*([\d,]+)\*\*\)",
            text, re.IGNORECASE,
        )
    return Catch(
        match.group(1), name, int(match.group(2)), match.group(5),
        match.group(4) or "",
        bool(re.search(r"these colors seem unusual", text, re.IGNORECASE)),
        bool(re.search(r"\bgigantamax\b", text, re.IGNORECASE)),
        chain.group(1) if chain else None,
    )


def main_category(name: str) -> str | None:
    name = name.casefold()
    if name in REGIONAL_NAMES:
        return "regional"
    if name in RARE_NAMES or any(
        re.search(rf"(?<!\w){re.escape(form)}(?!\w)", name)
        for form in ALL_FORM_NAMES
    ):
        return "rare"
    return None


class StarboardSettingsView(discord.ui.LayoutView):
    class ChannelSelect(discord.ui.ChannelSelect):
        def __init__(self, owner, key, label):
            super().__init__(
                placeholder=f"Set {label} channel (clear to disable)",
                channel_types=[discord.ChannelType.text],
                min_values=0, max_values=1,
            )
            self.owner = owner
            self.key = key

        async def callback(self, interaction):
            if interaction.user.id != self.owner.user_id:
                await interaction.response.send_message(
                    "Only the person who ran v!settings can change these settings.",
                    ephemeral=True,
                )
                return
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "You need Manage Server permission to change starboard settings.",
                    ephemeral=True,
                )
                return
            settings = self.owner.settings()
            settings[self.key] = self.values[0].id if self.values else None
            self.owner.cog.save_bot_state()
            self.owner.rebuild()
            await interaction.response.edit_message(view=self.owner)

    def __init__(self, cog, user_id, guild_id):
        super().__init__(timeout=300)
        self.cog, self.user_id, self.guild_id = cog, user_id, guild_id
        self.rebuild()

    def settings(self):
        return self.cog.bot_state.setdefault("guild_settings", {}).setdefault(
            str(self.guild_id), {}
        ).setdefault("starboard", {})

    def rebuild(self):
        self.clear_items()
        container = discord.ui.Container()
        container.add_item(discord.ui.TextDisplay(
            "## Server Settings · Starboard\n"
            "Choose a channel for each board; clear its selection to disable it."
        ))
        for key, label, description in (
            ("main", "Main Starboard", "Rare and regional catches."),
            ("shiny", "Shiny Starboard", "Shiny catches and channel counter."),
            ("vivillon", "Vivillon Starboard", "Gigantamax, below 10% and above 90% IV catches."),
        ):
            channel_id = self.settings().get(key)
            destination = f"<#{channel_id}>" if channel_id else "Disabled"
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(
                f"**{label}**\nDestination: {destination}\n{description}"
            ))
            row = discord.ui.ActionRow()
            row.add_item(self.ChannelSelect(self, key, label.lower()))
            container.add_item(row)
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        back.callback = self.go_back
        row = discord.ui.ActionRow()
        row.add_item(back)
        container.add_item(row)
        self.add_item(container)

    async def go_back(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran v!settings can use this menu.", ephemeral=True
            )
            return
        from bot import ServerSettingsView
        await interaction.response.edit_message(
            view=ServerSettingsView(self.user_id, self.cog, self.guild_id)
        )


class StarboardService:
    def __init__(self, cog):
        self.cog = cog
        self.locks = {}

    def embed(self, catch, kind, message):
        titles = {
            "rare": ("⭐ Rare Catch Detected!", 0xFFD700),
            "regional": ("🌍 Regional Catch Detected!", 0x3498DB),
            "shiny": ("✨ Shiny Catch Detected ✨", 0xF5DCE5),
            "gmax": ("✖️ Gigantamax Catch Detected ✖️", 0xF5DCE5),
            "low": ("📉 Low IV Catch Detected 📉", 0xF5DCE5),
            "high": ("📈 High IV Catch Detected 📈", 0xF5DCE5),
        }
        name = catch.pokemon
        if kind == "gmax" and not name.casefold().startswith("gigantamax "):
            name = f"Gigantamax {name}"
        spawn = self.cog.pokemon_spawn_chances.get(name.casefold())
        chance = "Unknown"
        if spawn:
            numerator, separator, denominator = spawn["Chance"].partition("/")
            if separator and numerator == "1" and denominator.isdigit():
                chance = f"1 out of {int(denominator):,}"
            else:
                chance = spawn["Chance"]
        gender = f" {catch.gender}" if catch.gender else ""
        if kind in {"rare", "regional"}:
            description = (
                f"`Trainer  :` <@{catch.user_id}>\n`Pokemon  :` {name}{gender}\n"
                f"`Level    :` {catch.level}\n`IVs      :` {catch.iv_text}%\n"
                f"`Spawnrate:` {chance}"
            )
        else:
            description = (
                f"**Caught By:** <@{catch.user_id}>\n**Pokémon:** {name}{gender}\n"
                f"**Level:** {catch.level}\n**IV:** {catch.iv_text}%\n"
            )
            if kind == "shiny" and catch.chain:
                description += f"**Chain:** `{catch.chain}`\n"
            description += f"**Spawnrate:** {chance}"
        title, color = titles[kind]
        embed = discord.Embed(title=title, description=description, color=color,
                              timestamp=message.created_at)
        if kind in {"rare", "regional"}:
            embed.set_footer(text="Catch Detection System")
        sprite_name = catch.pokemon.removeprefix("Gigantamax ")
        sprite_id = (GMAX_IDS.get(sprite_name.casefold()) if kind == "gmax" else None)
        if sprite_id is None:
            sprite_id = self.cog.pokemon_sprite_ids.get(sprite_name)
        if sprite_id is None:
            data = self.cog.pokemon_spawn_chances.get(sprite_name.casefold())
            sprite_id = data["Dex"] if data else None
        if sprite_id is not None:
            shiny = "shiny/" if catch.shiny else ""
            embed.set_thumbnail(url=(
                "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
                f"sprites/pokemon/other/official-artwork/{shiny}{sprite_id}.png"
            ))
        return embed

    async def increment_shiny_channel(self, channel):
        current = await self.cog.bot.fetch_channel(channel.id)
        match = re.search(r"(\d+)$", current.name)
        counters = self.cog.bot_state.setdefault("starboard_shiny_counts", {})
        count = max(int(match.group(1)) if match else 0, counters.get(str(channel.id), 0)) + 1
        counters[str(channel.id)] = count
        self.cog.save_bot_state()
        prefix = current.name[:match.start()] if match else current.name + "-"
        await current.edit(name=f"{prefix}{count}", reason="Shiny starboard catch count")

    async def handle(self, message):
        if message.guild is None:
            return
        catch = parse_catch(message)
        if catch is None:
            return
        settings = (self.cog.bot_state.get("guild_settings", {})
                    .get(str(message.guild.id), {}).get("starboard", {}))
        category = main_category(catch.pokemon)
        kinds = []
        if category and settings.get("main"):
            kinds.append((settings["main"], category))
        if catch.shiny and settings.get("shiny"):
            kinds.append((settings["shiny"], "shiny"))
        if settings.get("vivillon"):
            if catch.gigantamax:
                kinds.append((settings["vivillon"], "gmax"))
            if float(catch.iv_text) < 10:
                kinds.append((settings["vivillon"], "low"))
            if float(catch.iv_text) > 90:
                kinds.append((settings["vivillon"], "high"))
        if not kinds:
            return
        lock = self.locks.setdefault(message.guild.id, asyncio.Lock())
        async with lock:
            seen = self.cog.bot_state.setdefault("starboard_posted", {})
            message_key = str(message.id)
            posted = seen.setdefault(message_key, [])
            for channel_id, kind in kinds:
                key = f"{channel_id}:{kind}"
                if key in posted:
                    continue
                channel = message.guild.get_channel(channel_id)
                if channel is None:
                    logging.getLogger(__name__).error("Starboard channel %s not found", channel_id)
                    continue
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Catch", url=message.jump_url))
                try:
                    await channel.send(embed=self.embed(catch, kind, message), view=view,
                                       allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    logging.getLogger(__name__).exception("Could not post to starboard %s", channel_id)
                    continue
                posted.append(key)
                while len(seen) > 1000:
                    del seen[next(iter(seen))]
                self.cog.save_bot_state()
                if kind == "shiny":
                    try:
                        await self.increment_shiny_channel(channel)
                    except (discord.HTTPException, ValueError):
                        logging.getLogger(__name__).exception(
                            "Could not update shiny starboard channel name %s", channel_id
                        )
