"""Server-specific roles and channels configuration."""
import discord


class RolesChannelsSettingsView(discord.ui.LayoutView):
    """Settings view for configuring roles and channels."""

    class RoleSelect(discord.ui.RoleSelect):
        def __init__(self, owner, key, label):
            super().__init__(
                placeholder=f"Set {label} (clear to disable)",
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
                    "You need Manage Server permission to change roles and channels settings.",
                    ephemeral=True,
                )
                return
            settings = self.owner.settings()
            settings[self.key] = self.values[0].id if self.values else None
            self.owner.cog.save_bot_state()
            self.owner.rebuild()
            await interaction.response.edit_message(view=self.owner)

    class ChannelSelect(discord.ui.ChannelSelect):
        def __init__(self, owner, key, label):
            super().__init__(
                placeholder=f"Set {label} (clear to disable)",
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
                    "You need Manage Server permission to change roles and channels settings.",
                    ephemeral=True,
                )
                return
            settings = self.owner.settings()
            settings[self.key] = self.values[0].id if self.values else None
            self.owner.cog.save_bot_state()
            self.owner.rebuild()
            await interaction.response.edit_message(view=self.owner)

    class DisabledNamingChannelSelect(discord.ui.ChannelSelect):
        def __init__(self, owner):
            super().__init__(
                placeholder="Set disabled naming channels (clear to enable all)",
                channel_types=[discord.ChannelType.text],
                min_values=0,
                max_values=25,
            )
            self.owner = owner

        async def callback(self, interaction):
            if interaction.user.id != self.owner.user_id:
                await interaction.response.send_message(
                    "Only the person who ran v!settings can change these settings.",
                    ephemeral=True,
                )
                return
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "You need Manage Server permission to change roles and channels settings.",
                    ephemeral=True,
                )
                return
            self.owner.settings()["disabled_naming_channels"] = [
                channel.id for channel in self.values
            ]
            self.owner.cog.save_bot_state()
            self.owner.rebuild()
            await interaction.response.edit_message(view=self.owner)

    def __init__(self, cog, user_id, guild_id):
        super().__init__(timeout=300)
        self.cog, self.user_id, self.guild_id = cog, user_id, guild_id
        self.page = 0
        self.rebuild()

    def settings(self):
        return self.cog.bot_state.setdefault("guild_settings", {}).setdefault(
            str(self.guild_id), {}
        ).setdefault("roles_channels", {})

    def rebuild(self):
        self.clear_items()
        container = discord.ui.Container()
        container.add_item(discord.ui.TextDisplay(
            "## Server Settings · Roles & Channels\n"
            f"Configure roles and channels for server features. Page {self.page + 1} of 2."
        ))

        if self.page == 0:
            self.add_single_settings(container)
        else:
            channel_ids = self.settings().get("disabled_naming_channels", [])
            if isinstance(channel_ids, list):
                destinations = ", ".join(f"<#{channel_id}>" for channel_id in channel_ids)
            else:
                destinations = ""
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(
                "**Disabled Naming Channels**\n"
                f"Channels: {destinations or 'None'}\n"
                "Vivillon will not identify Pokétwo spawns in selected channels. "
                "Starboards and other bot features are unaffected."
            ))
            row = discord.ui.ActionRow()
            row.add_item(self.DisabledNamingChannelSelect(self))
            container.add_item(row)

        row = discord.ui.ActionRow()
        if self.page == 0:
            next_page = discord.ui.Button(
                label="Next", style=discord.ButtonStyle.secondary
            )
            next_page.callback = self.next_page
            row.add_item(next_page)
        else:
            previous_page = discord.ui.Button(
                label="Previous", style=discord.ButtonStyle.secondary
            )
            previous_page.callback = self.previous_page
            row.add_item(previous_page)
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        back.callback = self.go_back
        row.add_item(back)
        container.add_item(row)
        self.add_item(container)

    def add_single_settings(self, container):
        for key, label, description, kind, select_label in (
            (
                "missingno_role",
                "Missingno Alert Role",
                "Role pinged when a Missingno spawn is detected.",
                "role",
                "Missingno alert role",
            ),
            (
                "ffa_review_role",
                "Approval Request Role",
                "Role pinged when someone requests FFA approval via "
                "v!rafk → Announcement.",
                "role",
                "FFA approval role",
            ),
            (
                "ffa_review_channel",
                "Approval Channel",
                "Channel where FFA approval requests are sent for staff review.",
                "channel",
                "FFA approval channel",
            ),
            (
                "ffa_announcement_channel",
                "FFA Announcement Channel",
                "Channel where approved FFA announcements are posted.",
                "channel",
                "FFA announcement channel",
            ),
            (
                "ffa_role",
                "Announcement Role",
                "Role pinged when an FFA is announced in the announcement channel.",
                "role",
                "FFA announcement role",
            ),
            (
                "reserve_report_channel",
                "Reserve Report Channel",
                "Channel where stolen reserve reports are sent when v!report is used.",
                "channel",
                "Reserve report channel",
            ),
        ):
            selected_id = self.settings().get(key)
            destination = (
                f"<@&{selected_id}>"
                if selected_id and kind == "role"
                else f"<#{selected_id}>"
                if selected_id
                else "Not set"
            )
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(
                f"**{label}**\nDestination: {destination}\n{description}"
            ))
            row = discord.ui.ActionRow()
            if kind == "role":
                row.add_item(self.RoleSelect(self, key, select_label))
            else:
                row.add_item(self.ChannelSelect(self, key, select_label))
            container.add_item(row)

    async def next_page(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran v!settings can use this menu.",
                ephemeral=True,
            )
            return
        self.page = 1
        self.rebuild()
        await interaction.response.edit_message(view=self)

    async def previous_page(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran v!settings can use this menu.",
                ephemeral=True,
            )
            return
        self.page = 0
        self.rebuild()
        await interaction.response.edit_message(view=self)

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
