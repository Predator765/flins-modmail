# Modmail Discord Bot

A Discord Modmail bot (v4.2.1) that serves as a shared inbox for server staff to communicate with users via DMs. Similar to Reddit's Modmail.

## Project Structure

- `bot.py` - Main bot entry point (2267 lines)
- `core/` - Core modules (config, clients, models, thread management, utils, etc.)
- `cogs/` - Discord cog extensions (modmail, plugins, utility)
- `plugins/` - Plugin system with local registry
- `requirements.txt` - Python dependencies (pinned versions)
- `temp/` - Auto-created temp directory for logs and uploads

## Setup & Configuration

### Required Secrets (set in Replit Secrets)
- `TOKEN` - Discord bot token
- `GUILD_ID` - Discord server ID
- `OWNERS` - Comma-separated Discord user IDs of bot owners
- `CONNECTION_URI` - MongoDB connection string (mongodb+srv://...)

### Optional Secrets
- `LOG_URL` - URL of self-hosted log viewer
- `GITHUB_TOKEN` - GitHub personal access token (for plugin management)
- `DISABLE_AUTOUPDATES` - Set to `true` to disable auto-updates

## Dependencies

- **Language**: Python 3.12
- **Discord library**: discord.py v2.6.3
- **Database**: MongoDB via motor (async driver)
- **System libraries**: cairo, pango, gdk-pixbuf (for cairosvg image rendering)

## Running

The bot runs via the "Start application" workflow: `python3 bot.py`

No web frontend — this is a pure Discord bot (console output only).

## Key Features

- DM-based modmail system for Discord servers
- Thread management for staff-user communications
- Plugin system for extensibility
- Auto-updates from GitHub
- MongoDB for persistent storage
