import asyncio
import logging
import os
import re
import typing

import discord
from discord.ext import commands
from discord import app_commands

logger = logging.getLogger(__name__)

TICKET_LOG_CHANNEL_ID = 1433100781652803586
LOG_CHANNEL_ID = 1433100781652803586
STAFF_ROLE_ID = 1386907069860548619
MOD_PING_ROLE_ID = 1386907069860548619
MOD_ROLE_ID = 1386941962422063174
TRIAL_MOD_ROLE_ID = 1386907069889908772
CLOSE_ALLOWED_ROLE_IDS = {MOD_ROLE_ID, TRIAL_MOD_ROLE_ID, STAFF_ROLE_ID}
MODMAIL_CATEGORY_ID = 1528056516307849347
TICKET_CATEGORY_ID = 1528056516307849347

EMBED_COLOR = 0x39438a
STAFF_PERMISSION_ROLE_ID = 1446431677739171916
DARK_GRAY = 0x2B2D31


def _can_close(member):
    """Return True if the member may close a ticket / bring-in / modmail."""
    if not isinstance(member, discord.Member):
        return False
    if any(r.id in CLOSE_ALLOWED_ROLE_IDS for r in member.roles):
        return True
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild


DIVIDER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "divider.png")


async def _close_role_global_check(ctx):
    """Restrict `=close` (modmail) to Mod, Trial Mod, or higher staff."""
    if ctx.command and ctx.command.qualified_name == "close":
        if not _can_close(ctx.author):
            raise commands.CheckFailure(
                "You need the Mod or Trial Mod role to close this modmail thread."
            )
    return True


def _div():
    return discord.File(DIVIDER_PATH, filename="divider.png")


def _is_bringin_channel(channel):
    topic = getattr(channel, "topic", None) or ""
    return "Bring-in for" in topic


def _is_ticket_channel(channel):
    return getattr(channel, "name", "").startswith("ticket-")


def _is_event_channel(channel):
    return getattr(channel, "name", "").startswith("event-")


def _channel_kind(channel):
    """Return one of 'Event', 'Ticket', 'Bring-In' or None."""
    if _is_event_channel(channel):
        return "Event"
    if _is_ticket_channel(channel):
        return "Ticket"
    if _is_bringin_channel(channel):
        return "Bring-In"
    return None


def _user_dict(user, *, mod=False, guild=None):
    """Serialise a discord.User/Member to our log format."""
    avatar_url = None
    if hasattr(user, "display_avatar") and user.display_avatar:
        avatar_url = str(user.display_avatar.url)
    elif hasattr(user, "avatar") and user.avatar:
        avatar_url = str(user.avatar.url)
    disc = getattr(user, "discriminator", "0") or "0"
    return {
        "id": str(user.id),
        "name": user.name,
        "discriminator": disc,
        "avatar_url": avatar_url,
        "mod": mod,
    }


async def _save_ticket_transcript(channel, closer, bot):
    """
    Fetch all messages from a ticket channel, save a transcript to MongoDB,
    and return the log URL string (or None on failure).
    """
    try:
        from datetime import datetime, timezone

        topic = getattr(channel, "topic", "") or ""
        match = re.search(r"\((\d+)\)\s*$", topic)
        opener_id = int(match.group(1)) if match else None

        opener_member = channel.guild.get_member(opener_id) if opener_id else None

        if opener_member:
            is_mod = any(r.id == STAFF_ROLE_ID for r in opener_member.roles)
            recipient = _user_dict(opener_member, mod=is_mod)
        elif opener_id:
            name_match = re.match(r"Ticket opened by (.+) \(\d+\)$", topic)
            raw_name = name_match.group(1) if name_match else "unknown"
            recipient = {
                "id": str(opener_id),
                "name": raw_name,
                "discriminator": "0",
                "avatar_url": None,
                "mod": False,
            }
        else:
            recipient = {"id": "0", "name": "unknown", "discriminator": "0", "avatar_url": None, "mod": False}

        raw_msgs = []
        async for msg in channel.history(limit=None, oldest_first=True):
            raw_msgs.append(msg)

        log_messages = []
        for msg in raw_msgs:
            is_staff = msg.author.bot or any(
                r.id == STAFF_ROLE_ID for r in getattr(msg.author, "roles", [])
            )
            attachments = [{"url": a.url, "filename": a.filename} for a in msg.attachments]
            log_messages.append(
                {
                    "timestamp": msg.created_at.isoformat(),
                    "message_id": str(msg.id),
                    "author": _user_dict(msg.author, mod=is_staff),
                    "content": msg.content or "",
                    "type": "thread_message",
                    "attachments": attachments,
                }
            )

        now_utc = datetime.now(timezone.utc)
        key = f"ticket-{channel.id}"

        doc = {
            "key": key,
            "type": "ticket",
            "open": False,
            "created_at": raw_msgs[0].created_at.isoformat() if raw_msgs else now_utc.isoformat(),
            "closed_at": now_utc.isoformat(),
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "channel_topic": topic,
            "guild_id": str(channel.guild.id),
            "bot_id": bot.user.id if bot and bot.user else None,
            "recipient": recipient,
            "closer": _user_dict(closer),
            "messages": log_messages,
        }

        await bot.db.logs.replace_one({"key": key}, doc, upsert=True)

        return f"https://ticket-logs-y894.onrender.com/{key}"

    except Exception:
        logger.exception("Failed to save ticket transcript for %s", channel.name)
        return None


_CLOSE_TITLES = {
    "Event": "Event Ticket Closed",
    "Ticket": "Ticket Closed",
    "Bring-In": "Bring-In Closed",
}


async def _do_close_channel(channel, closer, *, send_fn, bot=None):
    """Send the closing embed, save transcript (for tickets/events), log, wait 5 s, then delete."""
    kind = _channel_kind(channel) or "Ticket"
    save_transcript = kind in ("Ticket", "Event")

    # Save transcript before anything is deleted
    log_url = None
    if save_transcript and bot is not None:
        log_url = await _save_ticket_transcript(channel, closer, bot)

    embed = discord.Embed(
        title="Channel Closing",
        description=f"Closed by {closer.mention}. This channel will be deleted in 5 seconds.",
        color=DARK_GRAY,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_image(url="attachment://divider.png")
    await send_fn(embed=embed, file=_div())

    log_channel = channel.guild.get_channel(TICKET_LOG_CHANNEL_ID)
    if log_channel:
        log_embed = discord.Embed(
            title=_CLOSE_TITLES.get(kind, "Ticket Closed"),
            color=DARK_GRAY,
            timestamp=discord.utils.utcnow(),
        )
        log_embed.add_field(name="Closed By", value=f"{closer.mention} (`{closer.id}`)", inline=True)
        log_embed.add_field(name="Ticket Type", value=kind, inline=True)
        log_embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        log_embed.set_image(url="attachment://divider.png")
        view = None
        if log_url:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Transcript", url=log_url, style=discord.ButtonStyle.url))
        await log_channel.send(embed=log_embed, file=_div(), view=view)

    await asyncio.sleep(5)
    try:
        await channel.delete()
    except discord.HTTPException:
        pass


class TicketCreateModal(discord.ui.Modal, title="Create Ticket Panel"):
    embed_title = discord.ui.TextInput(
        label="Embed Title",
        placeholder="e.g. Open a Ticket",
        required=True,
        max_length=256,
    )
    embed_description = discord.ui.TextInput(
        label="Embed Description",
        placeholder="Describe what this ticket panel is for...",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )
    embed_color = discord.ui.TextInput(
        label="Embed Color (hex, e.g. #39438a)",
        placeholder="#39438a",
        required=False,
        max_length=7,
        default="#39438a",
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw_color = str(self.embed_color.value).strip()
        try:
            color_int = int(raw_color.lstrip("#"), 16)
        except ValueError:
            color_int = EMBED_COLOR

        embed = discord.Embed(
            title=str(self.embed_title.value),
            description=str(self.embed_description.value),
            color=color_int,
        )
        embed.set_image(url="attachment://divider.png")

        view = OpenTicketView()
        # Post the panel as a normal channel message (so Discord doesn't show
        # "<user> used /ticketpanel" above it) and confirm to the runner with
        # an ephemeral message.
        await interaction.channel.send(embed=embed, file=_div(), view=view)
        await interaction.response.send_message(
            "Ticket panel posted.", ephemeral=True
        )


class OpenTicketButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Open Ticket",
            style=discord.ButtonStyle.secondary,
            custom_id="serenity:open_ticket",
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        existing = None
        for ch in guild.text_channels:
            if f"Ticket opened by {member}" in (ch.topic or ""):
                existing = ch
                break

        if existing:
            await interaction.response.send_message(
                f"You already have an open ticket: {existing.mention}", ephemeral=True
            )
            return

        staff_role = guild.get_role(STAFF_ROLE_ID)
        mod_role = guild.get_role(MOD_ROLE_ID)
        trial_mod_role = guild.get_role(TRIAL_MOD_ROLE_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, manage_channels=True
            ),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if mod_role:
            overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if trial_mod_role:
            overwrites[trial_mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        category = guild.get_channel(TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            category = None

        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{member.name.lower()}",
                overwrites=overwrites,
                topic=f"Ticket opened by {member} ({member.id})",
                category=category,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(f"Failed to create ticket: {e}", ephemeral=True)
            return

        embed = discord.Embed(
            title="Ticket Opened",
            description=(
                f"Hello {member.mention}! A staff member will be with you shortly.\n\n"
                "To close this ticket, use `/closeticket` or press the button below."
            ),
            color=EMBED_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Opened By", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.set_image(url="attachment://divider.png")

        close_view = CloseTicketView()
        ping_role = guild.get_role(MOD_PING_ROLE_ID)
        mention_text = f"<@&{MOD_PING_ROLE_ID}>" if ping_role else ""
        await channel.send(
            mention_text,
            embed=embed,
            file=_div(),
            view=close_view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )

        await interaction.response.send_message(
            f"Your ticket has been created: {channel.mention}", ephemeral=True
        )

class CloseTicketButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Close Ticket",
            style=discord.ButtonStyle.secondary,
            custom_id="serenity:close_ticket",
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_close(interaction.user):
            await interaction.response.send_message(
                "You need the Mod or Trial Mod role to close this channel.",
                ephemeral=True,
            )
            return
        await _do_close_channel(
            interaction.channel,
            interaction.user,
            send_fn=lambda **kw: interaction.response.send_message(**kw),
            bot=interaction.client,
        )


class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(OpenTicketButton())


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CloseTicketButton())


_ROLE_ID_RE = re.compile(r"\d{15,25}")


def _parse_role_id(text: str):
    if not text:
        return None
    match = _ROLE_ID_RE.search(text)
    return int(match.group(0)) if match else None


class EventTicketModal(discord.ui.Modal, title="Create Event Ticket Panel"):
    embed_title = discord.ui.TextInput(
        label="Embed Title",
        placeholder="e.g. Sign up for the next Event",
        required=True,
        max_length=256,
    )
    embed_description = discord.ui.TextInput(
        label="Embed Description",
        placeholder="Describe what this event ticket panel is for...",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )
    embed_color = discord.ui.TextInput(
        label="Embed Color (hex, e.g. #39438a)",
        placeholder="#39438a",
        required=False,
        max_length=7,
        default="#39438a",
    )
    ping_role = discord.ui.TextInput(
        label="Ping Role (mention or ID)",
        placeholder="@EventTeam  or  1234567890123456789",
        required=True,
        max_length=64,
    )
    button_label = discord.ui.TextInput(
        label="Button Label",
        placeholder="Open Event Ticket",
        required=False,
        max_length=80,
        default="Open Event Ticket",
    )

    async def on_submit(self, interaction: discord.Interaction):
        role_id = _parse_role_id(str(self.ping_role.value))
        role = interaction.guild.get_role(role_id) if role_id else None
        if role is None:
            await interaction.response.send_message(
                "I couldn't find that role. Please paste a role mention or ID from this server.",
                ephemeral=True,
            )
            return

        raw_color = str(self.embed_color.value).strip()
        try:
            color_int = int(raw_color.lstrip("#"), 16)
        except ValueError:
            color_int = EMBED_COLOR

        label = str(self.button_label.value).strip() or "Open Event Ticket"

        embed = discord.Embed(
            title=str(self.embed_title.value),
            description=str(self.embed_description.value),
            color=color_int,
        )
        embed.set_image(url="attachment://divider.png")

        view = discord.ui.View(timeout=None)
        view.add_item(OpenEventTicketButton(role.id, label=label))

        await interaction.channel.send(embed=embed, file=_div(), view=view)
        await interaction.response.send_message(
            f"Event ticket panel posted. Pings: {role.mention}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class OpenEventTicketButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"serenity:open_event:(?P<role_id>\d+)",
):
    def __init__(self, role_id: int, *, label: str = "Open Event Ticket"):
        super().__init__(
            discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"serenity:open_event:{role_id}",
            )
        )
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["role_id"]))

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        for ch in guild.text_channels:
            if f"Event ticket opened by {member}" in (ch.topic or ""):
                await interaction.response.send_message(
                    f"You already have an open event ticket: {ch.mention}", ephemeral=True
                )
                return

        ping_role = guild.get_role(self.role_id)
        staff_role = guild.get_role(STAFF_ROLE_ID)
        mod_role = guild.get_role(MOD_ROLE_ID)
        trial_mod_role = guild.get_role(TRIAL_MOD_ROLE_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, manage_channels=True
            ),
        }
        for r in (staff_role, mod_role, trial_mod_role, ping_role):
            if r:
                overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        category = guild.get_channel(TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            category = None

        try:
            channel = await guild.create_text_channel(
                name=f"event-{member.name.lower()}",
                overwrites=overwrites,
                topic=f"Event ticket opened by {member} ({member.id})",
                category=category,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(f"Failed to create event ticket: {e}", ephemeral=True)
            return

        embed = discord.Embed(
            title="Event Ticket Opened",
            description=(
                f"Hello {member.mention}! A staff member will be with you shortly.\n\n"
                "To close this ticket, use `/closeticket` or press the button below."
            ),
            color=EMBED_COLOR,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Opened By", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.set_image(url="attachment://divider.png")

        close_view = CloseTicketView()
        mention_text = ping_role.mention if ping_role else ""
        await channel.send(
            mention_text,
            embed=embed,
            file=_div(),
            view=close_view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )

        await interaction.response.send_message(
            f"Your event ticket has been created: {channel.mention}", ephemeral=True
        )


class Extras(commands.Cog):
    """Extra slash commands and bring-in channel helpers."""

    def __init__(self, bot):
        self.bot = bot
        bot.add_view(OpenTicketView())
        bot.add_view(CloseTicketView())
        bot.add_dynamic_items(OpenEventTicketButton)
        bot.add_check(_close_role_global_check)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Allow =close to work inside bring-in channels."""
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        if not (_is_bringin_channel(message.channel) or _is_event_channel(message.channel)):
            return

        prefix = self.bot.config.get("prefix", "=")
        content = message.content.strip().lower()
        if content != f"{prefix}close" and not content.startswith(f"{prefix}close "):
            return

        member = message.author
        if not _can_close(member):
            try:
                await message.channel.send(
                    f"{member.mention} you need the Mod or Trial Mod role to close this channel.",
                    delete_after=8,
                )
            except discord.HTTPException:
                pass
            return

        await _do_close_channel(
            message.channel,
            member,
            send_fn=lambda **kw: message.channel.send(**kw),
            bot=self.bot,
        )

    @app_commands.command(name="bringin", description="Open a modmail thread with a member")
    @app_commands.describe(member="The member to bring in via modmail")
    async def bringin(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        if member.bot:
            await interaction.followup.send(
                "You cannot open a modmail thread with a bot.", ephemeral=True
            )
            return

        existing = await self.bot.threads.find(recipient=member)
        if existing:
            await existing.wait_until_ready()
            if existing.channel and self.bot.get_channel(existing.channel.id):
                await interaction.followup.send(
                    f"A modmail thread for {member.mention} already exists: {existing.channel.mention}",
                    ephemeral=True,
                )
                return

        # Probe whether the member's DMs are open before creating the thread.
        dms_open = True
        try:
            dm = await member.create_dm()
            test_msg = await dm.send("\u200b")
            await test_msg.delete()
        except discord.Forbidden:
            dms_open = False
        except Exception:
            pass

        if not dms_open:
            # DMs are closed — fall back to a channel-based bring-in so the
            # member can still see and respond to staff in the server.
            guild = interaction.guild
            staff_role = guild.get_role(STAFF_ROLE_ID)
            mod_role = guild.get_role(MOD_ROLE_ID)
            trial_mod_role = guild.get_role(TRIAL_MOD_ROLE_ID)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, attach_files=True
                ),
                guild.me: discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, manage_channels=True
                ),
            }
            for role in (staff_role, mod_role, trial_mod_role):
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True
                    )

            category = guild.get_channel(MODMAIL_CATEGORY_ID)
            if not isinstance(category, discord.CategoryChannel):
                category = None

            try:
                channel = await guild.create_text_channel(
                    name=f"bringin-{member.name.lower()}",
                    overwrites=overwrites,
                    topic=f"Bring-in for {member} ({member.id})",
                    category=category,
                )
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"Failed to create bring-in channel: {e}", ephemeral=True
                )
                return

            _div_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "divider.png"
            )
            embed = discord.Embed(
                title="Bring-In (DMs Closed)",
                description=(
                    f"{member.mention} has their DMs closed, so a channel was created instead.\n\n"
                    f"**Brought in by:** {interaction.user.mention}\n"
                    f"Both staff and the member can speak here directly.\n\n"
                    f"Use `=close` to close this bring-in when done."
                ),
                color=EMBED_COLOR,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(
                name=str(member),
                icon_url=member.display_avatar.url,
            )
            embed.set_footer(text=f"User ID: {member.id}")
            embed.set_image(url="attachment://divider.png")

            close_view = CloseTicketView()
            ping_role = guild.get_role(MOD_PING_ROLE_ID)
            mention_text = ping_role.mention if ping_role else ""
            await channel.send(
                mention_text,
                embed=embed,
                file=discord.File(_div_path, filename="divider.png"),
                view=close_view,
                allowed_mentions=discord.AllowedMentions(roles=True),
            )

            await interaction.followup.send(
                f"{member.mention}'s DMs are closed — opened a channel-based bring-in instead: {channel.mention}",
                ephemeral=True,
            )
            return

        thread = await self.bot.threads.create(member, creator=interaction.user)

        if getattr(thread, "cancelled", False):
            await interaction.followup.send(
                "Failed to create a modmail thread for that member.", ephemeral=True
            )
            return

        await thread.wait_until_ready()

        channel = thread.channel
        await interaction.followup.send(
            f"Modmail thread opened for {member.mention}: {channel.mention if channel else 'unknown channel'}",
            ephemeral=True,
        )

    @app_commands.command(name="ticketpanel", description="Post a custom embed with an Open Ticket button")
    async def ticketpanel(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketCreateModal())

    @app_commands.command(
        name="eventpanel",
        description="Post a custom embed with an Open Event Ticket button (you choose which role gets pinged)",
    )
    async def eventpanel(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EventTicketModal())

    @app_commands.command(name="setstatus", description="Set the bot's activity status (e.g. 'Reviewing the field journal entries').")
    @app_commands.describe(
        message="The text to display as the bot's activity (leave empty + clear=True to remove).",
        activity_type="What kind of activity to show. Defaults to a custom status.",
        clear="If True, clear the current activity status entirely.",
    )
    @app_commands.choices(
        activity_type=[
            app_commands.Choice(name="Custom (default)", value="custom"),
            app_commands.Choice(name="Playing", value="playing"),
            app_commands.Choice(name="Watching", value="watching"),
            app_commands.Choice(name="Listening", value="listening"),
            app_commands.Choice(name="Competing", value="competing"),
        ]
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setstatus(
        self,
        interaction: discord.Interaction,
        message: typing.Optional[str] = None,
        activity_type: typing.Optional[app_commands.Choice[str]] = None,
        clear: typing.Optional[bool] = False,
    ):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client

        if clear:
            bot.config["activity_message"] = ""
            bot.config["activity_type"] = None
            await bot.config.update()
            try:
                await bot.change_presence(activity=None)
            except Exception:
                pass
            await interaction.followup.send("Cleared the bot's activity status.", ephemeral=True)
            return

        if message is None or not message.strip():
            await interaction.followup.send(
                "Please provide a `message` (or set `clear: True` to remove the status).",
                ephemeral=True,
            )
            return

        type_map = {
            "custom": discord.ActivityType.custom,
            "playing": discord.ActivityType.playing,
            "watching": discord.ActivityType.watching,
            "listening": discord.ActivityType.listening,
            "competing": discord.ActivityType.competing,
        }
        chosen_type = type_map[activity_type.value] if activity_type else discord.ActivityType.custom

        bot.config["activity_message"] = message.strip()
        bot.config["activity_type"] = chosen_type.value
        await bot.config.update()

        await bot.apply_presence()

        type_label = (activity_type.name if activity_type else "Custom (default)")
        await interaction.followup.send(
            f"Activity status updated.\n**Type:** {type_label}\n**Message:** {message.strip()}",
            ephemeral=True,
        )

    @app_commands.command(name="closeticket", description="Close the current ticket, event or bring-in channel")
    async def closeticket(self, interaction: discord.Interaction):
        channel = interaction.channel

        if _channel_kind(channel) is None:
            await interaction.response.send_message(
                "This command can only be used inside a ticket, event or bring-in channel.", ephemeral=True
            )
            return

        if not _can_close(interaction.user):
            await interaction.response.send_message(
                "You need the Mod or Trial Mod role to close this channel.",
                ephemeral=True,
            )
            return

        await _do_close_channel(
            channel,
            interaction.user,
            send_fn=lambda **kw: interaction.response.send_message(**kw),
            bot=interaction.client,
        )


async def setup(bot):
    await bot.add_cog(Extras(bot))
    logger.info("Extras cog loaded.")
