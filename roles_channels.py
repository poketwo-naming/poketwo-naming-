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

    def __init__(self, cog, user_id, guild_id):
        super().__init__(timeout=300)
        self.cog, self.user_id, self.guild_id = cog, user_id, guild_id
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
            "Configure roles and channels for server features."
        ))

        # Missingno Alert Role
        role_id = self.settings().get("missingno_role")
        destination = f"<@&{role_id}>" if role_id else "Not set"
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**Missingno Alert Role**\nDestination: {destination}\n"
            "Role pinged when a Missingno spawn is detected."
        ))
        row = discord.ui.ActionRow()
        row.add_item(self.RoleSelect(self, "missingno_role", "Missingno alert role"))
        container.add_item(row)

        # FFA Approval Request Role
        role_id = self.settings().get("ffa_review_role")
        destination = f"<@&{role_id}>" if role_id else "Not set"
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**Approval Request Role**\nDestination: {destination}\n"
            "Role pinged when someone requests FFA approval via v!rafk → Announcement."
        ))
        row = discord.ui.ActionRow()
        row.add_item(self.RoleSelect(self, "ffa_review_role", "FFA approval role"))
        container.add_item(row)

        # FFA Approval Channel
        channel_id = self.settings().get("ffa_review_channel")
        destination = f"<#{channel_id}>" if channel_id else "Not set"
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**Approval Channel**\nDestination: {destination}\n"
            "Channel where FFA approval requests are sent for staff review."
        ))
        row = discord.ui.ActionRow()
        row.add_item(self.ChannelSelect(self, "ffa_review_channel", "FFA approval channel"))
        container.add_item(row)

        # FFA Announcement Channel
        channel_id = self.settings().get("ffa_announcement_channel")
        destination = f"<#{channel_id}>" if channel_id else "Not set"
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**FFA Announcement Channel**\nDestination: {destination}\n"
            "Channel where approved FFA announcements are posted."
        ))
        row = discord.ui.ActionRow()
        row.add_item(self.ChannelSelect(self, "ffa_announcement_channel", "FFA announcement channel"))
        container.add_item(row)

        # FFA Announcement Role
        role_id = self.settings().get("ffa_role")
        destination = f"<@&{role_id}>" if role_id else "Not set"
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**Announcement Role**\nDestination: {destination}\n"
            "Role pinged when an FFA is announced in the announcement channel."
        ))
        row = discord.ui.ActionRow()
        row.add_item(self.RoleSelect(self, "ffa_role", "FFA announcement role"))
        container.add_item(row)

        # Reserve Report Channel
        channel_id = self.settings().get("reserve_report_channel")
        destination = f"<#{channel_id}>" if channel_id else "Not set"
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**Reserve Report Channel**\nDestination: {destination}\n"
            "Channel where stolen reserve reports are sent when v!report is used."
        ))
        row = discord.ui.ActionRow()
        row.add_item(self.ChannelSelect(self, "reserve_report_channel", "Reserve report channel"))
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
