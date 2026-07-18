import json
import logging
import os
import aiohttp
import io

import discord
from discord.ext import commands
from discord import app_commands

logger = logging.getLogger(__name__)

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "autoresponders.json")
MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "ar_media")
EMBED_COLOR = 16442070


def _load() -> dict:
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def _save_media(attachment: discord.Attachment) -> str:
    """Download and save media locally, return the local file path."""
    os.makedirs(MEDIA_DIR, exist_ok=True)
    filename = f"{attachment.id}_{attachment.filename}"
    filepath = os.path.join(MEDIA_DIR, filename)
    async with aiohttp.ClientSession() as session:
        async with session.get(attachment.url) as resp:
            data = await resp.read()
    with open(filepath, "wb") as f:
        f.write(data)
    return filepath


class AutoResponder(commands.Cog):
    """Keyword-triggered auto-responder with optional media support."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return

        responders = _load()
        content_lower = message.content.lower()

        for trigger, data in responders.items():
            if trigger.lower() in content_lower:
                response_text = data.get("response", "")
                local_path = data.get("local_path")

                if local_path and os.path.exists(local_path):
                    file = discord.File(local_path)
                    await message.channel.send(content=response_text or None, file=file)
                else:
                    await message.channel.send(content=response_text or None)
                break

    ar = app_commands.Group(name="autoresponder", description="Manage keyword auto-responders")

    @ar.command(name="add", description="Add a keyword auto-responder")
    @app_commands.describe(
        trigger="The word or phrase that triggers the response",
        response="The text to respond with",
        media="Optional image, GIF, or video to attach to the response",
    )
    async def ar_add(
        self,
        interaction: discord.Interaction,
        trigger: str,
        response: str,
        media: discord.Attachment = None,
    ):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)
            return

        await interaction.response.defer()

        responders = _load()
        entry = {"response": response}

        if media:
            local_path = await _save_media(media)
            entry["local_path"] = local_path
            mime = media.content_type or ""
            if "video" in mime:
                entry["media_type"] = "video"
            elif "gif" in mime or media.filename.lower().endswith(".gif"):
                entry["media_type"] = "gif"
            else:
                entry["media_type"] = "image"

        responders[trigger.lower()] = entry
        _save(responders)

        embed = discord.Embed(
            title="Auto-responder added",
            color=EMBED_COLOR,
        )
        embed.add_field(name="Trigger", value=f"`{trigger.lower()}`", inline=False)
        embed.add_field(name="Response", value=response, inline=False)
        if media:
            embed.add_field(name="Media", value=media.filename, inline=True)
        await interaction.followup.send(embed=embed)

    @ar.command(name="remove", description="Remove a keyword auto-responder")
    @app_commands.describe(trigger="The trigger word or phrase to remove")
    async def ar_remove(self, interaction: discord.Interaction, trigger: str):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)
            return

        responders = _load()
        key = trigger.lower()

        if key not in responders:
            await interaction.response.send_message(
                f"No auto-responder found for `{key}`.", ephemeral=True
            )
            return

        # Delete local media file if it exists
        local_path = responders[key].get("local_path")
        if local_path and os.path.exists(local_path):
            os.remove(local_path)

        del responders[key]
        _save(responders)

        embed = discord.Embed(
            description=f"Auto-responder for `{key}` removed.",
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed)

    @ar.command(name="list", description="List all active auto-responders")
    async def ar_list(self, interaction: discord.Interaction):
        responders = _load()

        if not responders:
            await interaction.response.send_message("No auto-responders set up yet.", ephemeral=True)
            return

        embed = discord.Embed(title="Auto-responders", color=EMBED_COLOR)
        for trigger, data in responders.items():
            value = data.get("response", "")
            if data.get("local_path"):
                value += f"\n[{data.get('media_type', 'media')}]"
            embed.add_field(name=f"`{trigger}`", value=value or "(no text)", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ar.command(name="edit", description="Edit the response text of an existing auto-responder")
    @app_commands.describe(
        trigger="The trigger to edit",
        response="New response text",
        media="New media attachment (replaces the old one if any)",
    )
    async def ar_edit(
        self,
        interaction: discord.Interaction,
        trigger: str,
        response: str = None,
        media: discord.Attachment = None,
    ):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You don't have permission to do that.", ephemeral=True)
            return

        responders = _load()
        key = trigger.lower()

        if key not in responders:
            await interaction.response.send_message(
                f"No auto-responder found for `{key}`. Use `/autoresponder add` to create one.", ephemeral=True
            )
            return

        await interaction.response.defer()

        if response is not None:
            responders[key]["response"] = response

        if media:
            # Delete old media file if it exists
            old_path = responders[key].get("local_path")
            if old_path and os.path.exists(old_path):
                os.remove(old_path)

            local_path = await _save_media(media)
            responders[key]["local_path"] = local_path
            mime = media.content_type or ""
            if "video" in mime:
                responders[key]["media_type"] = "video"
            elif "gif" in mime or media.filename.lower().endswith(".gif"):
                responders[key]["media_type"] = "gif"
            else:
                responders[key]["media_type"] = "image"

        _save(responders)

        embed = discord.Embed(
            title="Auto-responder updated",
            color=EMBED_COLOR,
        )
        embed.add_field(name="Trigger", value=f"`{key}`", inline=False)
        embed.add_field(name="Response", value=responders[key].get("response", ""), inline=False)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AutoResponder(bot))
    logger.info("AutoResponder cog loaded.")
